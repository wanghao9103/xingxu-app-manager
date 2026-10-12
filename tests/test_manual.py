import os
from pathlib import Path
import tempfile
import unittest
from app_manager.backend import Application, sort_apps
from app_manager.manual import plan_manual, uninstall_manual, ManualError


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.data = self.home / '.local/share'
        self.config = self.home / '.config'
        (self.data / 'applications').mkdir(parents=True)
        self.calls = []
        self.app = Application('test.desktop', 'Fixture', source='手动安装', icon='test-fixture')
        self.app.desktop_path = str(self.data / 'applications/test.desktop')

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, args, **kwargs):
        self.calls.append(args)
        return ''

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def plan(self):
        return plan_manual(self.app, self.runner, self.home, self.data, self.config)

    def desktop(self, command):
        return self.write(Path(self.app.desktop_path), f'[Desktop Entry]\nType=Application\nName=Fixture\nExec="{command}"\nIcon=test-fixture\n')

    def test_native_bundle_is_actually_removed(self):
        program = self.write(self.data / 'native-fixture/program', 'fixture')
        launcher = self.desktop(program)
        icon = self.write(self.data / 'icons/hicolor/256x256/apps/test-fixture.png', 'icon')
        unrelated = self.write(self.data / 'unrelated/document', 'keep')
        plan = self.plan()
        self.assertIn(program.parent, plan.targets)
        uninstall_manual(plan, self.runner)
        self.assertFalse(program.parent.exists())
        self.assertFalse(launcher.exists())
        self.assertFalse(icon.exists())
        self.assertTrue(unrelated.exists())
        self.assertFalse(any(a[0] == '/usr/bin/pkexec' for a in self.calls))

    def test_wrapper_and_appimage_bundle_and_autostart(self):
        bundle = self.home / '.local/opt/screenshot'
        program = self.write(bundle / 'squashfs-root/AppRun', 'fixture')
        self.write(bundle / 'Fixture.AppImage', 'image')
        wrapper = self.write(self.home / '.local/bin/screenshot', f'#!/bin/sh\nexec {program} "$@"\n')
        launcher = self.desktop(wrapper)
        autostart = self.write(self.config / 'autostart/test.desktop', launcher.read_text())
        profile = self.write(self.config / 'Screenshot/config.ini', 'keep')
        plan = self.plan()
        self.assertIn(bundle, plan.targets)
        self.assertIn(wrapper, plan.targets)
        self.assertIn(autostart, plan.targets)
        uninstall_manual(plan, self.runner)
        self.assertFalse(bundle.exists())
        self.assertFalse(wrapper.exists())
        self.assertFalse(autostart.exists())
        self.assertTrue(profile.exists())

    def test_profile_in_share_is_preserved(self):
        program = self.write(self.data / 'messenger/Messenger', 'fixture')
        profile = self.write(program.parent / 'tdata/profile', 'keep')
        self.desktop(program)
        plan = self.plan()
        self.assertIn(program, plan.targets)
        self.assertNotIn(program.parent, plan.targets)
        uninstall_manual(plan, self.runner)
        self.assertFalse(program.exists())
        self.assertTrue(profile.exists())

    def test_shared_icon_is_retained(self):
        program = self.write(self.data / 'native-fixture/program', 'fixture')
        self.desktop(program)
        icon = self.write(self.data / 'icons/hicolor/256x256/apps/test-fixture.png', 'icon')
        self.write(self.data / 'applications/other.desktop', '[Desktop Entry]\nName=Other\nExec=/usr/bin/true\nIcon=test-fixture\n')
        self.assertNotIn(icon, self.plan().targets)

    def test_replaced_executable_blocks_removal(self):
        program = self.write(self.home / '.local/bin/test-program', 'fixture')
        launcher = self.desktop(program)
        plan = self.plan()
        program.unlink()
        program.symlink_to('/usr/bin/true')
        with self.assertRaises(ManualError):
            uninstall_manual(plan, self.runner)
        self.assertTrue(launcher.exists())

    def test_system_binary_is_never_deleted_as_manual(self):
        self.desktop(Path('/usr/bin/python3'))
        with self.assertRaises(ManualError):
            self.plan()

    def test_directory_link_outside_user_tree_is_rejected(self):
        outside = tempfile.TemporaryDirectory()
        try:
            program = Path(outside.name) / 'program'
            program.write_text('keep')
            link = self.data / 'unsafe'
            link.symlink_to(Path(outside.name), target_is_directory=True)
            self.desktop(link / 'program')
            with self.assertRaises(ManualError):
                self.plan()
            self.assertTrue(program.exists())
        finally:
            outside.cleanup()

    def test_dates_sort_both_directions_unknown_last(self):
        old = Application('old','Old',installed_at='2026-01-01 00:00:00')
        new = Application('new','New',installed_at='2026-10-12 00:00:00')
        unknown = Application('unknown','Unknown')
        self.assertEqual([a.id for a in sort_apps([unknown,old,new],2)], ['new','old','unknown'])
        self.assertEqual([a.id for a in sort_apps([unknown,old,new],5)], ['old','new','unknown'])

    def test_sizes_sort_both_directions_unknown_last(self):
        small = Application('small','Small',size=10)
        large = Application('large','Large',size=100)
        unknown = Application('unknown','Unknown')
        self.assertEqual([a.id for a in sort_apps([unknown,small,large],1)], ['large','small','unknown'])
        self.assertEqual([a.id for a in sort_apps([unknown,small,large],4)], ['small','large','unknown'])

    def test_matching_user_service_is_stopped_and_removed(self):
        program = self.write(self.data / 'native-fixture/program', 'fixture')
        self.desktop(program)
        unit = self.write(self.config / 'systemd/user/fixture.service', '[Service]\n')
        def runner(args, **kwargs):
            self.calls.append(args)
            if 'show' in args:
                return f'Id=fixture.service\nExecStart={{ path={program} ; argv[]={program} ; }}\nFragmentPath={unit}\n'
            return ''
        plan = plan_manual(self.app, runner, self.home, self.data, self.config)
        self.assertEqual(plan.services, ('fixture.service',))
        uninstall_manual(plan, runner)
        self.assertIn(['/usr/bin/systemctl','--user','stop','fixture.service'], self.calls)
        self.assertFalse(unit.exists())

    def test_natural_versions_with_unknown_last(self):
        one = Application('one','One',version='1.2')
        ten = Application('ten','Ten',version='1.10')
        unknown = Application('unknown','Unknown')
        self.assertEqual([a.id for a in sort_apps([unknown,ten,one],8)], ['one','ten','unknown'])
        self.assertEqual([a.id for a in sort_apps([unknown,ten,one],7)], ['ten','one','unknown'])


if __name__ == '__main__':
    unittest.main()
