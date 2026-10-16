"""Focused checks for Windows settings and logging; no browser is launched."""
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fork_windows.runtime import DesktopSettings, SessionStream, configure_logging, set_log_file


class DesktopRuntimeTests(unittest.TestCase):
    def tearDown(self):
        for handler in logging.getLogger().handlers[:]:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def test_config_preserves_environment_overrides_and_boolean_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'PORT': 8200, 'HEADLESS': False}), encoding='utf-8')
            settings = DesktopSettings(path)
            settings.load()
            with patch.dict(os.environ, {'PORT': '8199'}, clear=True):
                settings.apply_environment()
                self.assertEqual(os.environ['PORT'], '8199')
                self.assertEqual(os.environ['HEADLESS'], 'false')
            for invalid in (True, 8191.5, None):
                with self.assertRaises(ValueError):
                    settings.validate({'PORT': invalid})

    def test_log_toggle_preserves_other_config_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = DesktopSettings(Path(directory) / 'config.json')
            settings.load()
            data = json.loads(settings.path.read_text(encoding='utf-8'))
            data['PORT'] = 8201
            settings.path.write_text(json.dumps(data), encoding='utf-8')
            settings.set_log_file('session.log')
            restored = DesktopSettings(settings.path)
            restored.load()
            self.assertEqual(restored.data['PORT'], 8201)
            self.assertEqual(restored.data['LOG_FILE'], 'session.log')

    def test_output_is_retained_until_console_consumes_it(self):
        stream = SessionStream()
        print('logged while hidden', file=stream)
        stream.write('next request\n')
        self.assertEqual(stream.drain(), 'logged while hidden\nnext request\n')
        self.assertEqual(stream.drain(), '')

    def test_disk_logging_can_be_enabled_and_disabled_without_losing_console(self):
        stream = SessionStream()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'LOG_LEVEL': 'info', 'LOG_FILE': ''}):
            configure_logging(stream)
            path = Path(directory) / 'logs' / 'session.log'
            set_log_file(path)
            logging.info('written to both')
            stream.write('raw core stdout\n')
            set_log_file(None)
            logging.info('console only')
            self.assertIn('written to both', path.read_text(encoding='utf-8'))
            self.assertNotIn('console only', path.read_text(encoding='utf-8'))
            self.assertIn('raw core stdout', path.read_text(encoding='utf-8'))
            self.assertIn('console only', stream.drain())
            set_log_file(path)
            stream.disk_handler.maxBytes = 1
            with patch.object(stream.disk_handler, 'doRollover', side_effect=OSError('disk full')):
                stream.write('capture continues after disk failure\n')
            self.assertIsNone(stream.disk_handler)
            output = stream.drain()
            self.assertIn('capture continues after disk failure', output)
            self.assertIn('Disk logging stopped', output)


if __name__ == '__main__':
    unittest.main()
