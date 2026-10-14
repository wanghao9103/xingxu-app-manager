import unittest
from app_manager.errors import connection_error, diagnostic_text, friendly_error


class ErrorTests(unittest.TestCase):
    def test_certificate_log_is_readable_without_url_ip_or_openssl_text(self):
        message = 'E: Failed to fetch https://dbeaver.io/debs/dbeaver-ce/InRelease SSL connection failed: error:0A000086:SSL routines::certificate verify failed [IP: 198.18.0.54 443]'
        readable = friendly_error(message)
        self.assertIn('安全连接', readable)
        for raw in ('https://', '198.18.', 'certificate', 'SSL', 'error:'):
            self.assertNotIn(raw, readable)
        self.assertTrue(connection_error(message))

    def test_authorization_and_lock_errors_are_not_network_retries(self):
        for error in ('系统授权已取消或未能取得权限。', 'Could not get lock /var/lib/dpkg/lock'):
            self.assertFalse(connection_error(error))
        self.assertIn('授权', friendly_error('系统授权已取消或未能取得权限。'))
        self.assertIn('其他软件管理操作', friendly_error('Could not get lock /var/lib/dpkg/lock'))

    def test_friendly_chinese_explanations_are_preserved(self):
        message = '更新版本或影响范围已变化，请重新检查并确认。'
        self.assertEqual(friendly_error(message), message)

    def test_unknown_command_errors_and_timeouts_are_readable(self):
        self.assertEqual(friendly_error('E: unexpected command failure'), '操作未完成，请查看详情后重试。')
        self.assertEqual(friendly_error('Unable to download summary'), '操作未完成，请查看详情后重试。')
        self.assertIn('超时', friendly_error('connection timed out'))

    def test_repository_credentials_are_redacted_only_in_diagnostics(self):
        message = 'Failed to fetch https://username:secret@example.org/repository/InRelease'
        redacted = diagnostic_text(message)
        self.assertNotIn('username', redacted)
        self.assertNotIn('secret', redacted)
        self.assertIn('example.org/repository', redacted)
        self.assertEqual(diagnostic_text('https://example.org/path'), 'https://example.org/path')
