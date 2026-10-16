"""FlareSolverr's native Windows log window and notification-area controls."""
import json
import logging
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .runtime import configure_logging, get_log_file, set_log_file
from .process import ProcessControl
from .tray import TrayIcon, keep_browser_children_with_app


class DesktopApp:
    def __init__(self, settings, start_core):
        from .runtime import SessionStream
        self.settings = settings
        self.start_core = start_core
        self.control = ProcessControl()
        self.commands = queue.SimpleQueue()
        self.stream = SessionStream()
        self.old_stdout, self.old_stderr = sys.stdout, sys.stderr
        self.tray = None
        self.editor = None
        self.exiting = False
        self.finished = threading.Event()
        self.browser_job = None
        self.root = tk.Tk(className='FlareSolverr')
        self.root.withdraw()
        self.root.title('FlareSolverr Console')
        self.root.geometry('1000x580')
        self.root.minsize(600, 300)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_console)
        self.root.report_callback_exception = self._callback_error
        resource_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
        self.icon_path = resource_root / 'resources' / 'flaresolverr_logo.ico'
        self.root.iconbitmap(default=str(self.icon_path))
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill='x')
        self.status = tk.StringVar(value='Starting FlareSolverr…')
        ttk.Label(toolbar, textvariable=self.status).pack(side='left')
        ttk.Button(toolbar, text='Hide console', command=self.hide_console).pack(side='right')
        self.console = scrolledtext.ScrolledText(self.root, state='disabled', wrap='word',
                                                font=('Consolas', 10), background='#15191e',
                                                foreground='#e6edf3', insertbackground='#e6edf3')
        self.console.pack(fill='both', expand=True)
        self.console.bind('<Control-a>', self._select_all)

    def _select_all(self, _event):
        self.console.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def show_console(self):
        self.root.deiconify()
        self.root.lift()
        self.console.focus_set()

    def hide_console(self):
        if self.tray is None:
            self.request_exit()
        else:
            self.root.withdraw()

    def toggle_console(self):
        if self.root.state() == 'withdrawn':
            self.show_console()
        else:
            self.hide_console()

    def _append_output(self):
        output = self.stream.drain()
        if output:
            follow = self.console.yview()[1] >= 0.99
            self.console.configure(state='normal')
            self.console.insert('end', output)
            self.console.configure(state='disabled')
            if follow:
                self.console.see('end')

    def _poll(self):
        self._append_output()
        for _ in range(100):
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            actions = {'show': self.show_console, 'toggle': self.toggle_console,
                       'config': self.edit_config, 'logging': self.toggle_disk_logging,
                       'exit': self.request_exit, 'failed': self._startup_failed,
                       'ready': lambda: self.status.set('FlareSolverr is running')}
            if not self.exiting and command in actions:
                actions[command]()
        if self.exiting and self.finished.is_set():
            self.root.destroy()
            return
        self.root.after(100, self._poll)

    def disk_logging_enabled(self):
        return get_log_file() is not None

    def toggle_disk_logging(self):
        previous = get_log_file()
        path = None if previous else self.settings.default_log_file
        try:
            # Open the destination before recording it as enabled in configuration.
            set_log_file(path)
            self.settings.set_log_file(path)
            logging.info('Disk logging %s%s', 'enabled: ' if path else 'disabled', path or '')
        except Exception as error:
            set_log_file(previous)
            logging.exception('Could not change disk logging')
            messagebox.showerror('FlareSolverr logging', str(error), parent=self.root)

    def edit_config(self):
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.deiconify()
            self.editor.lift()
            return
        self.editor = tk.Toplevel(self.root)
        self.editor.title('FlareSolverr Configuration')
        self.editor.geometry('720x500')
        self.editor.iconbitmap(default=str(self.icon_path))
        ttk.Label(self.editor, text=str(self.settings.path), padding=8).pack(anchor='w')
        ttk.Label(self.editor, text='Changes apply after restarting FlareSolverr. Environment variables take priority.',
                  padding=(8, 0, 8, 8)).pack(anchor='w')
        text = scrolledtext.ScrolledText(self.editor, wrap='none', font=('Consolas', 10), undo=True)
        text.pack(fill='both', expand=True, padx=8)
        content = (self.settings.path.read_text(encoding='utf-8-sig') if self.settings.path.exists()
                   else json.dumps(self.settings.data, indent=4))
        text.insert('1.0', content)

        def save():
            try:
                self.settings.save(json.loads(text.get('1.0', 'end')))
            except (ValueError, TypeError, OSError) as error:
                messagebox.showerror('Cannot save configuration', str(error), parent=self.editor)
                return
            logging.info('Configuration saved; restart FlareSolverr to apply changes.')
            self.editor.destroy()

        buttons = ttk.Frame(self.editor, padding=8)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Save', command=save).pack(side='right')
        ttk.Button(buttons, text='Cancel', command=self.editor.destroy).pack(side='right', padx=6)

    def _startup_failed(self):
        self.status.set('Startup failed — see the log below')
        self.show_console()

    def _callback_error(self, kind, error, traceback):
        logging.error('Desktop interface error', exc_info=(kind, error, traceback))
        self.show_console()

    def _serve(self):
        try:
            self.settings.load()
            self.settings.apply_environment()
            configure_logging(self.stream)
            self.start_core(self.control, lambda: self.commands.put('ready'))
        except BaseException:
            if not self.exiting:
                logging.exception('FlareSolverr could not start')
                self.commands.put('failed')

    def request_exit(self):
        if self.exiting:
            return
        self.exiting = True
        self.status.set('Stopping FlareSolverr…')
        logging.info('Stopping FlareSolverr.')
        if self.tray is not None:
            self.tray.close()
            self.tray = None
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.destroy()

        def stop():
            try:
                self.control.stop()
            except Exception:
                logging.exception('Error stopping FlareSolverr')
            finally:
                self.finished.set()

        threading.Thread(target=stop, name='FlareSolverr shutdown', daemon=True).start()

    def run(self):
        sys.stdout = sys.stderr = self.stream
        logging.basicConfig(level=logging.INFO, stream=self.stream,
                            format='%(asctime)s %(levelname)-8s %(message)s', force=True)
        try:
            try:
                self.browser_job = keep_browser_children_with_app()
            except OSError:
                logging.exception('Could not enable automatic browser process cleanup')
            try:
                self.tray = TrayIcon(self.commands, self.disk_logging_enabled)
            except Exception:
                logging.exception('Could not create the tray icon; keeping the console visible.')
                self.show_console()
            threading.Thread(target=self._serve, name='FlareSolverr server', daemon=True).start()
            self.root.after(100, self._poll)
            self.root.mainloop()
        finally:
            if self.tray is not None:
                self.tray.close()
            logging.shutdown()
            self.stream.set_log_file(None)
            sys.stdout, sys.stderr = self.old_stdout, self.old_stderr
