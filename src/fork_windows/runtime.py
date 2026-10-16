"""Settings and log destinations shared by Windows desktop and service modes."""
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading


DEFAULT_SETTINGS = {
    'HOST': '0.0.0.0', 'PORT': 8191, 'HEADLESS': True,
    'LOG_LEVEL': 'info', 'LOG_FILE': '',
}
ENVIRONMENT_SETTINGS = set(DEFAULT_SETTINGS) | {
    'LOG_HTML', 'PROXY_URL', 'PROXY_USERNAME', 'PROXY_PASSWORD',
    'CAPTCHA_SOLVER', 'TZ', 'LANG', 'DISABLE_MEDIA',
    'BROWSER_WAIT_TIMEOUT', 'TEST_URL', 'PROMETHEUS_ENABLED', 'PROMETHEUS_PORT',
}


class DesktopSettings:
    def __init__(self, path=None):
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'FlareSolverr'
        self.path = Path(path).expanduser().resolve() if path else base / 'config.json'
        self.data = dict(DEFAULT_SETTINGS)

    @property
    def default_log_file(self):
        return self.path.parent / 'logs' / 'flaresolverr.log'

    @staticmethod
    def validate(data):
        if not isinstance(data, dict):
            raise ValueError('Configuration must be a JSON object.')
        for name, value in data.items():
            if name not in ENVIRONMENT_SETTINGS:
                raise ValueError(f'Unknown configuration option: {name}')
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f'{name} must be a string, number, boolean, or null.')
        for name in ('PORT', 'PROMETHEUS_PORT'):
            if name not in data:
                continue
            value = data[name]
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                raise ValueError(f'{name} must be an integer between 1 and 65535.')
            try:
                valid = 1 <= int(value) <= 65535
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f'{name} must be an integer between 1 and 65535.')
        if str(data.get('LOG_LEVEL', 'info')).upper() not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            raise ValueError('LOG_LEVEL must be debug, info, warning, error, or critical.')
        return data

    def load(self):
        if self.path.exists():
            self.data = self.validate(json.loads(self.path.read_text(encoding='utf-8-sig')))
        else:
            self.save(self.data)

    def save(self, data):
        self.validate(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.config-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, indent=4, ensure_ascii=False)
                handle.write('\n')
            os.replace(temporary, self.path)
            self.data = dict(data)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def apply_environment(self):
        for name, value in self.data.items():
            if value is None:
                continue
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if name == 'LOG_FILE' and value:
                value = str((self.path.parent / Path(value).expanduser()).resolve())
            os.environ.setdefault(name, value)

    def set_log_file(self, path):
        # Reload so a tray toggle cannot overwrite changes saved in the editor.
        self.load()
        self.save({**self.data, 'LOG_FILE': str(path) if path else ''})


class SessionFileHandler(RotatingFileHandler):
    def handleError(self, record):
        # Default logging error reporting writes to stderr, which is this same
        # session stream in desktop mode. Propagate instead of recursing.
        raise OSError('Disk log write failed') from sys.exc_info()[1]


class SessionStream(io.TextIOBase):
    """Workers write here; only the GUI thread consumes and displays output."""
    def __init__(self):
        super().__init__()
        self.messages = queue.SimpleQueue()
        self.disk_handler = None
        self.disk_lock = threading.RLock()

    @property
    def encoding(self):
        return 'utf-8'

    def writable(self):
        return True

    def write(self, text):
        if text:
            self.messages.put(text)
            with self.disk_lock:
                if self.disk_handler is not None:
                    record = logging.LogRecord('session', logging.INFO, '', 0, text, (), None)
                    try:
                        self.disk_handler.handle(record)
                    except Exception as error:
                        failed, self.disk_handler = self.disk_handler, None
                        try:
                            failed.close()
                        except OSError:
                            pass
                        self.messages.put(f'\nDisk logging stopped: {error.__cause__ or error}\n')
        return len(text)

    def flush(self):
        with self.disk_lock:
            if self.disk_handler is not None:
                self.disk_handler.flush()

    def set_log_file(self, path):
        handler = None
        if path:
            path = Path(path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = SessionFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            handler.terminator = ''
        with self.disk_lock:
            previous, self.disk_handler = self.disk_handler, handler
            if previous is not None:
                previous.close()

    def drain(self):
        messages = []
        for _ in range(1000):
            try:
                messages.append(self.messages.get_nowait())
            except queue.Empty:
                break
        return ''.join(messages)


def set_log_file(path):
    root = logging.getLogger()
    for output in root.handlers:
        stream = getattr(output, 'stream', None)
        if isinstance(stream, SessionStream):
            stream.set_log_file(path)
            return
    previous = [handler for handler in root.handlers if getattr(handler, '_desktop_log_file', False)]
    if path:
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
        handler._desktop_log_file = True
        if root.handlers:
            handler.setFormatter(root.handlers[0].formatter)
        root.addHandler(handler)
    for handler in previous:
        root.removeHandler(handler)
        handler.close()


def get_log_file():
    for handler in logging.getLogger().handlers:
        stream = getattr(handler, 'stream', None)
        if isinstance(stream, SessionStream) and stream.disk_handler is not None:
            return stream.disk_handler.baseFilename
        if getattr(handler, '_desktop_log_file', False):
            return handler.baseFilename
    return None


def configure_logging(stream=None):
    level = os.environ.get('LOG_LEVEL', 'info').upper()
    format_string = '%(asctime)s %(levelname)-8s %(message)s'
    if level == 'DEBUG':
        format_string = '%(asctime)s %(levelname)-8s ReqId %(thread)s %(message)s'
    output = stream if stream is not None else sys.stdout
    handlers = [logging.StreamHandler(output)] if output is not None else [logging.NullHandler()]
    logging.basicConfig(format=format_string, level=level, datefmt='%Y-%m-%d %H:%M:%S',
                        handlers=handlers, force=True)
    set_log_file(os.environ.get('LOG_FILE'))
