"""Small Win32 notification icon; uses the icon embedded in the packaged exe."""
import ctypes
from ctypes import wintypes as w
import logging
import os
from pathlib import Path
import sys


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class WindowClass(ctypes.Structure):
    _fields_ = [('style', w.UINT), ('proc', WNDPROC), ('class_extra', ctypes.c_int),
                ('window_extra', ctypes.c_int), ('instance', w.HINSTANCE), ('icon', w.HICON),
                ('cursor', w.HANDLE), ('background', w.HBRUSH), ('menu', w.LPCWSTR), ('name', w.LPCWSTR)]


class IconData(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('window', w.HWND), ('id', w.UINT), ('flags', w.UINT),
                ('callback', w.UINT), ('icon', w.HICON), ('tip', w.WCHAR * 128),
                ('state', w.DWORD), ('state_mask', w.DWORD), ('info', w.WCHAR * 256),
                ('version', w.UINT), ('info_title', w.WCHAR * 64), ('info_flags', w.DWORD),
                ('guid', ctypes.c_byte * 16), ('balloon_icon', w.HICON)]


class JobLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', w.DWORD), ('min_working_set', ctypes.c_size_t),
                ('max_working_set', ctypes.c_size_t), ('active_processes', w.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedJobLimits(ctypes.Structure):
    _fields_ = [('basic', JobLimits), ('io_counters', ctypes.c_uint64 * 6),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


def keep_browser_children_with_app():
    """Windows reaps our Chrome/driver children even if Exit interrupts startup.

    Keep the non-inheritable job handle open until process exit: closing it
    explicitly would terminate this process too. Other applications are not in
    this private job, including any already-running user browser.
    """
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [w.LPVOID, w.LPCWSTR], w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
    kernel.SetInformationJobObject.restype = w.BOOL
    kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedJobLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        error = ctypes.WinError(ctypes.get_last_error())
        kernel.CloseHandle(job)  # Assignment failed; no processes belong to it.
        raise error
    return job


class TrayIcon:
    CALLBACK = 0x8001

    def __init__(self, commands, disk_logging_enabled):
        self.commands = commands
        self.disk_logging_enabled = disk_logging_enabled
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self._declare_functions()
        self.instance = self.kernel.GetModuleHandleW(None)
        self.class_name = f'FlareSolverrTray-{os.getpid()}'
        self.taskbar_created = self.user.RegisterWindowMessageW('TaskbarCreated')
        self.callback = WNDPROC(self._window_proc)  # Retain the callback for the whole window lifetime.
        self.window_class = WindowClass(proc=self.callback, instance=self.instance, name=self.class_name)
        self.window = None
        self.icon = None
        self.data = None
        if not self.user.RegisterClassW(ctypes.byref(self.window_class)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # A hidden top-level window receives TaskbarCreated after Explorer restarts.
            self.window = self.user.CreateWindowExW(0, self.class_name, 'FlareSolverr', 0,
                                                    0, 0, 0, 0, None, None, self.instance, None)
            if not self.window:
                raise ctypes.WinError(ctypes.get_last_error())
            self.icon = self._load_icon()
            self.data = IconData(size=ctypes.sizeof(IconData), window=self.window, id=1,
                                 flags=1 | 2 | 4 | 0x80, callback=self.CALLBACK,
                                 icon=self.icon, tip='FlareSolverr — click to show or hide console')
            self._add()
        except BaseException:
            self.close()
            raise

    def _declare_functions(self):
        prototypes = {
            'RegisterClassW': ([ctypes.POINTER(WindowClass)], w.ATOM),
            'UnregisterClassW': ([w.LPCWSTR, w.HINSTANCE], w.BOOL),
            'CreateWindowExW': ([w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID], w.HWND),
            'DefWindowProcW': ([w.HWND, w.UINT, w.WPARAM, w.LPARAM], LRESULT),
            'DestroyWindow': ([w.HWND], w.BOOL),
            'DestroyIcon': ([w.HICON], w.BOOL),
            'RegisterWindowMessageW': ([w.LPCWSTR], w.UINT),
            'LoadImageW': ([w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT], w.HANDLE),
            'CreatePopupMenu': ([], w.HMENU),
            'AppendMenuW': ([w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR], w.BOOL),
            'GetCursorPos': ([ctypes.POINTER(w.POINT)], w.BOOL),
            'SetForegroundWindow': ([w.HWND], w.BOOL),
            'TrackPopupMenu': ([w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, ctypes.POINTER(w.RECT)], w.UINT),
            'DestroyMenu': ([w.HMENU], w.BOOL),
            'PostMessageW': ([w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
        }
        for name, (arguments, result) in prototypes.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.kernel.GetModuleHandleW.argtypes = [w.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = w.HMODULE
        self.shell.ExtractIconExW.argtypes = [w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.HICON),
                                             ctypes.POINTER(w.HICON), w.UINT]
        self.shell.ExtractIconExW.restype = w.UINT
        self.shell.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(IconData)]
        self.shell.Shell_NotifyIconW.restype = w.BOOL

    def _load_icon(self):
        if getattr(sys, 'frozen', False):
            icon = w.HICON()
            if self.shell.ExtractIconExW(sys.executable, 0, None, ctypes.byref(icon), 1) and icon:
                return icon.value
        resource_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
        path = resource_root / 'resources' / 'flaresolverr_logo.ico'
        icon = self.user.LoadImageW(None, str(path), 1, 16, 16, 0x10)
        if not icon:
            raise ctypes.WinError(ctypes.get_last_error())
        return icon

    def _add(self):
        if not self.shell.Shell_NotifyIconW(0, ctypes.byref(self.data)):
            raise OSError('Windows could not add the FlareSolverr notification icon.')
        self.data.version = 4
        self.shell.Shell_NotifyIconW(4, ctypes.byref(self.data))

    def _window_proc(self, window, message, wparam, lparam):
        try:
            if message == 0x10:  # WM_CLOSE on the hidden tray owner requests application exit.
                self.commands.put('exit')
                return 0
            if message == self.CALLBACK:
                event = lparam & 0xffff
                if event in (0x400, 0x401):  # NIN_SELECT / NIN_KEYSELECT: one activation.
                    self.commands.put('toggle')
                elif event == 0x7b:  # WM_CONTEXTMENU, mouse or keyboard.
                    self._menu()
                return 0
            if message == self.taskbar_created and self.data is not None:
                self._add()
                return 0
        except Exception:
            logging.exception('Notification icon error')
        return self.user.DefWindowProcW(window, message, wparam, lparam)

    def _menu(self):
        menu = self.user.CreatePopupMenu()
        try:
            self.user.AppendMenuW(menu, 0, 1, 'View console')
            self.user.AppendMenuW(menu, 0, 2, 'Edit configuration')
            self.user.AppendMenuW(menu, 8 if self.disk_logging_enabled() else 0, 3, 'Log to disk')
            self.user.AppendMenuW(menu, 0x800, 0, None)
            self.user.AppendMenuW(menu, 0, 4, 'Exit')
            position = w.POINT()
            self.user.GetCursorPos(ctypes.byref(position))
            self.user.SetForegroundWindow(self.window)
            command = self.user.TrackPopupMenu(menu, 0x100 | 0x80 | 2, position.x, position.y,
                                               0, self.window, None)
            self.user.PostMessageW(self.window, 0, 0, 0)
            action = {1: 'show', 2: 'config', 3: 'logging', 4: 'exit'}.get(command)
            if action:
                self.commands.put(action)
        finally:
            self.user.DestroyMenu(menu)

    def close(self):
        if self.data is not None:
            self.shell.Shell_NotifyIconW(2, ctypes.byref(self.data))
            self.data = None
        if self.window:
            self.user.DestroyWindow(self.window)
            self.window = None
        if self.icon:
            self.user.DestroyIcon(self.icon)
            self.icon = None
        self.user.UnregisterClassW(self.class_name, self.instance)
