"""Supervise the unchanged upstream FlareSolverr executable."""
import os
from pathlib import Path
import subprocess
import sys
import threading


def core_command():
    if getattr(sys, 'frozen', False):
        core = Path(sys.executable).parent / 'core' / 'flaresolverr.exe'
        if not core.is_file():
            raise FileNotFoundError(f'FlareSolverr core executable is missing: {core}')
        return [str(core)]
    interpreter = Path(sys.executable)
    if interpreter.name.lower() == 'pythonw.exe':
        interpreter = interpreter.with_name('python.exe')
    return [str(interpreter), str(Path(__file__).resolve().parents[1] / 'flaresolverr.py')]


class ProcessControl:
    def __init__(self):
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.process = None

    def attach(self, process):
        with self.lock:
            self.process = process
            stopping = self.stopping.is_set()
        if stopping:
            self.stop()
        return not stopping

    def stop(self):
        self.stopping.set()
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def run_core(control, ready):
    environment = os.environ.copy()
    # The desktop stream owns disk logging so its tray switch takes effect
    # immediately and also captures stderr, without patching the core logger.
    environment.pop('LOG_FILE', None)
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUNBUFFERED'] = '1'
    process = subprocess.Popen(core_command(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace',
                               creationflags=subprocess.CREATE_NO_WINDOW, env=environment)
    try:
        if control.attach(process):
            ready()
        for line in process.stdout:
            sys.stdout.write(line)
        code = process.wait()
        if not control.stopping.is_set():
            raise RuntimeError(f'FlareSolverr stopped with exit code {code}. See the console log above.')
    finally:
        process.stdout.close()
        if process.poll() is None:
            control.stop()
