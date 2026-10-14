import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_manager import authorization_helper as helper
from app_manager import privileges


class AuthorizationTests(unittest.TestCase):
    def test_only_real_pkexec_caller_can_configure_and_no_target_user_argument(self):
        with patch.object(helper.os, 'geteuid', return_value=1000), patch.dict(os.environ, {'PKEXEC_UID': '1000'}):
            with self.assertRaises(ValueError): helper.account()
        with patch.object(helper.os, 'geteuid', return_value=0):
            for value in ('', '0', '-1', '1000;evil', '../1000'):
                with patch.dict(os.environ, {'PKEXEC_UID': value}), self.assertRaises(ValueError): helper.account()
        with patch.object(helper, 'configure') as configure, patch('builtins.print'):
            for args in ([], ['grant', '1001'], ['shell']):
                self.assertEqual(helper.main(args), 1)
            configure.assert_not_called()

    def test_rule_is_scoped_to_account_action_program_and_active_local_session(self):
        rule = helper.rule_text('example";evil()//')
        self.assertIn('action.id === "io.miemie.AppManager.manage"', rule)
        self.assertIn('action.lookup("program") === "/usr/libexec/miemie-app-manager-helper"', rule)
        self.assertIn('subject.local && subject.active', rule)
        self.assertIn('subject.user === "example\\";evil()//"', rule)
        self.assertNotIn('org.freedesktop.policykit.exec', rule)
        self.assertNotIn('io.miemie.AppManager.authorize', rule)

    def test_grant_is_idempotent_revoke_removes_only_current_account(self):
        with tempfile.TemporaryDirectory() as temp:
            rules = Path(temp) / 'rules'; rules.mkdir()
            state = Path(temp) / 'app/authorizations'
            with patch.object(helper, 'RULES', rules), patch.object(helper, 'STATE', state), patch.object(helper, 'trusted_directory'):
                other = rules / '49-xingxu-app-manager-1001.rules'; other.write_text('other account')
                for _ in range(2): helper.configure('grant', 1000, 'example')
                marker = state / '1000.json'
                self.assertEqual(json.loads(marker.read_text()), {'uid': 1000, 'user': 'example', 'enabled': True})
                rule = rules / '49-xingxu-app-manager-1000.rules'
                self.assertEqual(rule.stat().st_mode & 0o777, 0o644)
                self.assertEqual(marker.stat().st_mode & 0o777, 0o644)
                helper.configure('revoke', 1000, 'example')
                self.assertFalse(rule.exists() or marker.exists())
                self.assertEqual(other.read_text(), 'other account')

    def test_state_write_failure_rolls_back_authorization_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            rules = Path(temp) / 'rules'; rules.mkdir()
            state = Path(temp) / 'app/authorizations'
            with patch.object(helper, 'RULES', rules), patch.object(helper, 'STATE', state), patch.object(helper, 'trusted_directory'):
                rule = rules / '49-xingxu-app-manager-1000.rules'
                original = helper.atomic_write
                def write(path, data):
                    if path.parent == state: raise OSError('simulated disk error')
                    original(path, data)
                with patch.object(helper, 'atomic_write', side_effect=write):
                    with self.assertRaises(OSError): helper.configure('grant', 1000, 'example')
                self.assertFalse(rule.exists())

    def test_unsafe_directory_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'rules'; directory.mkdir()
            link=Path(temp)/'link'; link.symlink_to(directory)
            for path in (directory, link):
                with self.assertRaises(ValueError): helper.trusted_directory(path)

    def test_marker_cannot_be_forged_by_user_and_authorizer_is_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)
            marker=state/f'{os.getuid()}.json'
            marker.write_text(json.dumps({'uid': os.getuid(), 'user': 'fake', 'enabled': True}))
            with patch.object(privileges, 'AUTHORIZATION_STATE', state):
                self.assertFalse(privileges.authorization_enabled())
        calls=[]
        with patch.object(privileges, 'trusted_file', return_value=True):
            privileges.set_authorization(True, lambda args, **kw: calls.append(args))
            privileges.set_authorization(False, lambda args, **kw: calls.append(args))
        self.assertEqual(calls, [['/usr/bin/pkexec', str(privileges.AUTHORIZER), 'grant'],
                                 ['/usr/bin/pkexec', str(privileges.AUTHORIZER), 'revoke']])
        self.assertNotIn(str(privileges.HELPER), calls[0])
