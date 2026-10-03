import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from func_timeout import FunctionTimedOut

import flaresolverr_service as service


class TestSolveTimeout(unittest.TestCase):
    def setUp(self):
        self.req = SimpleNamespace(maxTimeout=55000, session=None, proxy=None)
        self.driver = Mock()

    def test_browser_startup_consumes_challenge_budget(self):
        with patch.object(service.time, 'monotonic', side_effect=[100, 115]), \
                patch.object(service.utils, 'get_webdriver', return_value=self.driver), \
                patch.object(service, 'func_timeout', return_value='solution') as solve:
            result = service._resolve_challenge(self.req, 'GET')

        self.assertEqual('solution', result)
        solve.assert_called_once_with(40, service._evil_logic, (self.req, self.driver, 'GET'))
        self.driver.quit.assert_called_once_with()
        self.driver.close.assert_not_called()

    def test_expired_startup_does_not_start_navigation(self):
        with patch.object(service.time, 'monotonic', side_effect=[100, 156]), \
                patch.object(service.utils, 'get_webdriver', return_value=self.driver), \
                patch.object(service, 'func_timeout') as solve:
            with self.assertRaisesRegex(Exception, r'Timeout after 55.0 seconds'):
                service._resolve_challenge(self.req, 'GET')

        solve.assert_not_called()
        self.driver.quit.assert_called_once_with()

    def test_challenge_timeout_still_cleans_up_browser(self):
        with patch.object(service.utils, 'get_webdriver', return_value=self.driver), \
                patch.object(service, 'func_timeout', side_effect=FunctionTimedOut()):
            with self.assertRaisesRegex(Exception, r'Timeout after 55.0 seconds'):
                service._resolve_challenge(self.req, 'GET')

        self.driver.quit.assert_called_once_with()

    def test_cleanup_failure_does_not_replace_challenge_error(self):
        self.driver.quit.side_effect = RuntimeError('browser already gone')
        with patch.object(service.utils, 'get_webdriver', return_value=self.driver), \
                patch.object(service, 'func_timeout', side_effect=ValueError('challenge failed')), \
                self.assertLogs(level='WARNING'):
            with self.assertRaisesRegex(Exception, 'challenge failed'):
                service._resolve_challenge(self.req, 'GET')

        self.driver.quit.assert_called_once_with()

    def test_cleanup_failure_preserves_successful_solution(self):
        self.driver.quit.side_effect = RuntimeError('browser already gone')
        with patch.object(service.utils, 'get_webdriver', return_value=self.driver), \
                patch.object(service, 'func_timeout', return_value='solution'), \
                self.assertLogs(level='WARNING'):
            self.assertEqual('solution', service._resolve_challenge(self.req, 'GET'))

    def test_session_startup_consumes_budget_without_destroying_session(self):
        self.req.session = 'existing-session'
        self.req.session_ttl_minutes = None
        session = SimpleNamespace(driver=self.driver)
        with patch.object(service.time, 'monotonic', side_effect=[100, 110]), \
                patch.object(service.SESSIONS_STORAGE, 'get', return_value=(session, True)), \
                patch.object(service, 'func_timeout', return_value='solution') as solve:
            service._resolve_challenge(self.req, 'GET')

        solve.assert_called_once_with(45, service._evil_logic, (self.req, self.driver, 'GET'))
        self.driver.quit.assert_not_called()

    def test_browser_startup_failure_keeps_original_error(self):
        with patch.object(service.utils, 'get_webdriver', side_effect=RuntimeError('startup failed')):
            with self.assertRaisesRegex(Exception, 'startup failed'):
                service._resolve_challenge(self.req, 'GET')


if __name__ == '__main__':
    unittest.main()
