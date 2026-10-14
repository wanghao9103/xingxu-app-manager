from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from app_manager import privileged_helper as helper
from app_manager import privileges
from app_manager.backend import HARD_PROTECTED


class HelperTests(unittest.TestCase):
    def test_privileged_and_preview_core_protections_agree(self):
        self.assertEqual(helper.HARD_PROTECTED, HARD_PROTECTED)

    def test_only_fixed_actions_and_strict_identifiers(self):
        bad = [[], ['bash', '-c', 'id'], ['apt-refresh', '-o', 'evil'],
               ['apt-upgrade', '-o', '1.0'], ['apt-upgrade', 'editor', '1.0;id'],
               ['apt-upgrade', '/tmp/editor.deb', '1.0'], ['apt-upgrade', 'editor', '1.0\n'],
               ['apt-remove', 'apt'], ['apt-remove', 'dpkg:amd64'],
               ['snap-remove', '--purge'], ['snap-upgrade', 'editor', '-1'],
               ['flatpak-remove', '--all'], ['flatpak-upgrade', 'org.example.App', 'a' * 64],
               ['flatpak-upgrade', 'app/org.example.App/x86_64/stable', '--system']]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(ValueError):
                helper.command(request)

    def test_supported_commands_have_fixed_scope_flags_and_no_shell(self):
        requests = [(['apt-refresh'], '/usr/bin/apt-get'),
                    (['apt-upgrade', 'editor:arm64', '1:2.0~rc1-1'], '/usr/bin/apt-get'),
                    (['apt-remove', 'editor'], '/usr/bin/apt-get'),
                    (['snap-upgrade', 'editor', '123'], '/usr/bin/snap'),
                    (['snap-remove', 'editor'], '/usr/bin/snap'),
                    (['flatpak-upgrade', 'app/org.example.App/aarch64/stable', 'a' * 64], '/usr/bin/flatpak'),
                    (['flatpak-remove', 'org.example.App'], '/usr/bin/flatpak')]
        for request, binary in requests:
            args = helper.command(request)
            self.assertEqual(args[0], binary)
            self.assertNotIn('sh', args)
        args = helper.command(['apt-upgrade', 'editor', '2.0'])
        self.assertIn('--no-remove', args)
        self.assertIn('--only-upgrade', args)
        self.assertEqual(helper.ENV['HOME'], '/root')
        self.assertNotIn('APT_CONFIG', helper.ENV)

    def test_root_rechecks_holds_candidate_and_protected_dependencies(self):
        def query(args):
            if args[0] == '/usr/bin/dpkg-query':
                return 'installed' if 'Status' in args[2] else 'yes\trequired'
            if args[0] == '/usr/bin/apt-mark':
                return 'editor\n'
            return ''
        with patch.object(helper, 'query', side_effect=query):
            request = ['apt-upgrade', 'editor', '2.0']
            with self.assertRaises(ValueError):
                helper.validate_state(request, helper.command(request))
        with patch.object(helper, 'query', side_effect=['installed', '', ' Candidate: 3.0\n']):
            with self.assertRaises(ValueError):
                helper.validate_state(request, helper.command(request))
        request = ['apt-remove', 'editor']
        with patch.object(helper, 'query', side_effect=['installed', 'Remv editor [1.0]\nRemv apt [3.0]', 'no\toptional']):
            with self.assertRaises(ValueError):
                helper.validate_state(request, helper.command(request))
        with patch.object(helper, 'query', side_effect=['installed', 'Remv editor [1.0]\nRemv essential-lib [1.0]', 'no\toptional', 'yes\trequired']):
            with self.assertRaises(ValueError):
                helper.validate_state(request, helper.command(request))

    def test_no_privilege_operation_before_validation(self):
        with patch.object(helper.os, 'geteuid', return_value=0), patch.object(helper.os, 'execve') as execute, patch('builtins.print'):
            self.assertEqual(helper.main(['apt-remove', '--all']), 1)
            execute.assert_not_called()

    def test_policy_only_caches_dedicated_helper_for_active_session(self):
        policy = ET.parse(Path(__file__).resolve().parents[1] / 'assets/polkit/io.miemie.AppManager.policy')
        actions = policy.findall('action')
        self.assertEqual(len(actions), 2)
        action = next(a for a in actions if a.attrib['id'] == 'io.miemie.AppManager.manage')
        self.assertEqual(action.attrib['id'], 'io.miemie.AppManager.manage')
        self.assertEqual(action.findtext('defaults/allow_active'), 'auth_admin_keep')
        self.assertEqual(action.findtext('defaults/allow_any'), 'auth_admin')
        self.assertEqual(action.findtext('defaults/allow_inactive'), 'auth_admin')
        self.assertEqual(action.findtext('annotate'), str(privileges.HELPER))
        authorizer = next(a for a in actions if a.attrib['id'] == 'io.miemie.AppManager.authorize')
        self.assertEqual(authorizer.findtext('defaults/allow_active'), 'auth_admin')
        self.assertEqual(authorizer.findtext('defaults/allow_any'), 'no')
        self.assertEqual(authorizer.findtext('annotate'), str(privileges.AUTHORIZER))

    def test_installed_helper_routing_and_safe_fallback(self):
        args = ['/usr/bin/pkexec', '/usr/bin/snap', 'refresh', 'editor', '--revision=11']
        with patch.object(privileges, 'trusted_file', return_value=True):
            self.assertEqual(privileges.command_for(args), ['/usr/bin/pkexec', str(privileges.HELPER), 'snap-upgrade', 'editor', '11'])
            unknown = ['/usr/bin/pkexec', '/usr/bin/bash', '-c', 'true']
            self.assertEqual(privileges.command_for(unknown), unknown)
        with patch.object(privileges, 'trusted_file', return_value=False):
            self.assertEqual(privileges.command_for(args), args)

    def test_symlink_writable_or_user_owned_helper_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'helper'
            target.write_text('fake helper')
            target.chmod(0o777)
            self.assertFalse(privileges.trusted_file(target))
            link = Path(folder) / 'link'
            link.symlink_to(target)
            self.assertFalse(privileges.trusted_file(link))
