import unittest
from app_manager.backend import Application, Manager, ManagerError, parse_packages, parse_owners, parse_install_log, format_size


PACKAGES = "editor\tinstalled\t1.2\t2048\tno\toptional\nlibgtk-3-0t64\tinstalled\t3.0\t100\tno\toptional\nold\tconfig-files\t1.0\t5\tno\toptional\n"


class BackendTests(unittest.TestCase):
    def manager(self, runner):
        manager = Manager(runner)
        manager.packages = parse_packages(PACKAGES)
        manager.apps["editor.desktop"] = Application("editor.desktop", "Editor", "editor", "APT")
        return manager

    def test_only_installed_packages(self):
        packages = parse_packages(PACKAGES)
        self.assertNotIn("old", packages)
        self.assertEqual(packages["editor"]["size"], 2097152)
        self.assertTrue(packages["libgtk-3-0t64"]["protected"])

    def test_multiarch_file_owner(self):
        owners = parse_owners("editor:amd64: /usr/share/applications/editor.desktop\nother: /path with spaces/file.desktop\n")
        self.assertEqual(owners["/usr/share/applications/editor.desktop"], "editor:amd64")
        self.assertEqual(owners["/path with spaces/file.desktop"], "other")

    def test_manager_package_can_remove_itself_and_check_final_status(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == '/usr/bin/apt-get':
                return 'Remv miemie-app-manager [1.1.3]\n'
            if args[0] == '/usr/bin/dpkg-query':
                return 'config-files'
            return 'Removed manager'
        manager = Manager(runner)
        manager.packages = parse_packages('miemie-app-manager\tinstalled\t1.1.3\t100\tno\toptional\n')
        self.assertFalse(manager.packages['miemie-app-manager']['protected'])
        app = Application('io.miemie.AppManager.desktop', '星序应用管理', 'miemie-app-manager', 'APT')
        app.protected = manager.packages[app.package]['protected']
        manager.apps[app.id] = app
        self.assertTrue(app.removable)
        plan = manager.plan(app.id)
        self.assertEqual(plan.removed, ['miemie-app-manager'])
        self.assertEqual(manager.uninstall(plan), 'Removed manager')
        self.assertEqual(next(args for args in calls if args[0] == '/usr/bin/pkexec')[-2:], ['--', 'miemie-app-manager'])

    def test_self_removal_still_blocks_core_dependency(self):
        manager = Manager(lambda *args, **kwargs: 'Remv miemie-app-manager [1.1.3]\nRemv apt [3.2]\n')
        app = Application('io.miemie.AppManager.desktop', '星序应用管理', 'miemie-app-manager', 'APT')
        manager.apps[app.id] = app
        with self.assertRaisesRegex(ManagerError, '系统保护组件 apt'):
            manager.plan(app.id)

    def test_install_date_is_not_upgrade_date(self):
        dates = parse_install_log(["2026-10-02 12:00:00 upgrade editor:amd64 1.0 2.0", "2026-10-01 10:00:00 install editor:amd64 <none> 1.0"])
        self.assertEqual(dates["editor"], "2026-10-01 10:00:00")

    def test_removed_then_reinstalled_date(self):
        dates = parse_install_log(["2026-10-01 10:00:00 install editor:amd64 <none> 1.0", "2026-10-02 10:00:00 remove editor:amd64 1.0 <none>", "2026-10-03 10:00:00 install editor:amd64 <none> 2.0"])
        self.assertEqual(dates["editor"], "2026-10-03 10:00:00")

    def test_desktop_dependency_requires_explicit_risk_confirmation(self):
        manager = self.manager(lambda *a, **kw: "Remv editor [1.2]\nRemv gnome-shell [1.0]\n")
        plan = manager.plan("editor.desktop")
        self.assertEqual(plan.risky, ["gnome-shell"])
        with self.assertRaisesRegex(ManagerError, "输入应用名称"):
            manager.uninstall(plan)

    def test_essential_dependency_blocks_plan(self):
        manager = self.manager(lambda *a, **kw: "Remv editor [1.2]\nRemv critical [1.0]\n")
        manager.packages["critical"] = {"protected": True}
        with self.assertRaises(ManagerError):
            manager.plan("editor.desktop")

    def test_plan_drift_never_executes(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return "Remv editor [1.2]\n" if len(calls) == 1 else "Remv editor [1.2]\nRemv dependent [1.0]\n"
        manager = self.manager(runner)
        plan = manager.plan("editor.desktop")
        with self.assertRaisesRegex(ManagerError, "范围已变化"):
            manager.uninstall(plan)
        self.assertFalse(any(a[0] == "/usr/bin/pkexec" for a in calls))

    def test_success_requires_post_uninstall_status(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == "/usr/bin/apt-get":
                return "Remv editor [1.2]\n"
            if args[0] == "/usr/bin/dpkg-query":
                return "config-files"
            return "Removed editor"
        manager = self.manager(runner)
        self.assertEqual(manager.uninstall(manager.plan("editor.desktop")), "Removed editor")
        command = next(a for a in calls if a[0] == "/usr/bin/pkexec")
        self.assertEqual(command[-2:], ["--", "editor"])
        self.assertNotIn("purge", command)
        self.assertIn("APT::Get::AutomaticRemove=false", command)

    def test_installed_status_after_command_is_failure(self):
        def runner(args, **kwargs):
            return "installed" if args[0] == "/usr/bin/dpkg-query" else "Remv editor [1.2]\n"
        manager = self.manager(runner)
        with self.assertRaisesRegex(ManagerError, "仍显示"):
            manager.uninstall(manager.plan("editor.desktop"))

    def test_authorization_failure_is_not_success(self):
        def runner(args, **kwargs):
            if args[0] == "/usr/bin/pkexec":
                raise ManagerError("系统授权已取消")
            return "Remv editor [1.2]\n"
        manager = self.manager(runner)
        with self.assertRaisesRegex(ManagerError, "授权已取消"):
            manager.uninstall(manager.plan("editor.desktop"))
        self.assertFalse(manager._lock.locked())

    def test_unknown_and_unmanaged_ids_blocked(self):
        manager = self.manager(lambda *a, **kw: "")
        manager.apps["manual"] = Application("manual", "Manual")
        for app_id in ("does-not-exist", "manual"):
            with self.assertRaises(ManagerError):
                manager.plan(app_id)

    def test_command_injection_name_blocked(self):
        manager = self.manager(lambda *a, **kw: self.fail("must not call subprocess"))
        manager.apps["editor.desktop"].package = "editor;echo bad"
        with self.assertRaisesRegex(ManagerError, "标识无效"):
            manager.plan("editor.desktop")

    def test_replacement_install_is_part_of_reviewed_plan(self):
        manager = self.manager(lambda *a, **kw: "Remv editor [1.2]\nInst replacement [1.0]\n")
        plan = manager.plan("editor.desktop")
        self.assertEqual(plan.installed, ["replacement"])
        self.assertTrue(any("replacement" in line for line in plan.fingerprint))

    def test_size_unknown(self):
        self.assertEqual(format_size(0), "未知")
        self.assertEqual(format_size(2097152), "2.0 MB")

    def test_snap_uses_exact_identifier_and_retains_snapshot(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return "Name Version Rev Tracking Publisher Notes\n" if args[:2] == ["/usr/bin/snap", "list"] else ""
        manager = Manager(runner)
        manager.apps["browser"] = Application("browser", "Browser", "test-browser", "Snap")
        manager.uninstall(manager.plan("browser"))
        self.assertEqual(calls[0], ["/usr/bin/pkexec", "/usr/bin/snap", "remove", "test-browser"])
        self.assertNotIn("--purge", calls[0])

    def test_user_flatpak_does_not_elevate_or_delete_data(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return ""
        manager = Manager(runner)
        manager.apps["flatpak"] = Application("flatpak", "Test", "org.example.Test", "Flatpak", scope="user")
        manager.uninstall(manager.plan("flatpak"))
        self.assertNotEqual(calls[0][0], "/usr/bin/pkexec")
        self.assertIn("--user", calls[0])
        self.assertEqual(calls[0][-1], "org.example.Test")
        self.assertNotIn("--delete-data", calls[0])

    def test_system_flatpak_elevates_and_checks_system_scope(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            return ""
        manager = Manager(runner)
        manager.apps["flatpak"] = Application("flatpak", "Test", "org.example.Test", "Flatpak", scope="system")
        manager.uninstall(manager.plan("flatpak"))
        self.assertEqual(calls[0][0], "/usr/bin/pkexec")
        self.assertIn("--system", calls[0])
        self.assertIn("--system", calls[1])

    def test_parallel_uninstall_is_blocked(self):
        manager = self.manager(lambda *a, **kw: "Remv editor [1.2]\n")
        plan = manager.plan("editor.desktop")
        manager._lock.acquire()
        try:
            with self.assertRaisesRegex(ManagerError, "另一个卸载"):
                manager.uninstall(plan)
        finally:
            manager._lock.release()

    def test_replacement_version_drift_blocks_execution(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args)
            version = '1.0' if len(calls) == 1 else '2.0'
            return f'Remv editor [1.2]\nInst replacement [{version}]\n'
        manager = self.manager(runner)
        plan = manager.plan('editor.desktop')
        with self.assertRaisesRegex(ManagerError, '范围已变化'):
            manager.uninstall(plan)
        self.assertFalse(any(a[0] == '/usr/bin/pkexec' for a in calls))


if __name__ == "__main__":
    unittest.main()
