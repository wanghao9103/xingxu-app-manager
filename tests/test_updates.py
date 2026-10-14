import unittest
from unittest.mock import patch

from app_manager.backend import Application, Manager, ManagerError
from app_manager.updates import UpdateInfo


class AptRunner:
    def __init__(self, package="editor:arm64", installed="1.0", candidate="1.1"):
        self.package, self.installed, self.candidate = package, installed, candidate
        self.calls = []
        self.held = ""
        self.extra = "Inst dependency (2.0 Ubuntu:26.04 [arm64])\n"
        self.failure = None
        self.verify = True

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "/usr/bin/pkexec":
            if self.failure:
                raise ManagerError(self.failure)
            if "install" in args and self.verify:
                self.installed = self.candidate
            return "done"
        if args[0] == "/usr/bin/apt-mark":
            return self.held
        if args[0] == "/usr/bin/apt-cache":
            return f"{self.package}:\n  Installed: {self.installed}\n  Candidate: {self.candidate}\n  Version table:\n"
        if args[0] == "/usr/bin/apt-get":
            return f"Inst {self.package} [{self.installed}] ({self.candidate} Ubuntu:26.04 [arm64])\nConf {self.package} ({self.candidate} Ubuntu:26.04 [arm64])\n" + self.extra
        if args[0] == "/usr/bin/dpkg-query":
            return f"installed\t{self.installed}"
        raise AssertionError(args)


class UpdateTests(unittest.TestCase):
    def apt(self, runner=None):
        runner = runner or AptRunner()
        manager = Manager(runner)
        app = Application("editor", "Editor", runner.package, "APT", runner.installed)
        manager.apps[app.id] = app
        return manager, runner

    def test_refresh_indexes_never_upgrades_and_versions_are_debian_ordered(self):
        manager, runner = self.apt(AptRunner(installed="1:1.10~rc1-1", candidate="1:1.10-1"))
        self.assertTrue(manager.check_updates()["editor"].available)
        elevated = [a for a in runner.calls if a[0] == "/usr/bin/pkexec"]
        self.assertEqual(len(elevated), 1)
        self.assertEqual(elevated[0][-1], "update")
        self.assertIn("APT::Update::Error-Mode=any", elevated[0])
        self.assertIn("Acquire::Retries=2", elevated[0])

    @patch('app_manager.updates.time.sleep')
    def test_transient_certificate_failure_retries_verified_refresh(self, sleep):
        runner = AptRunner()
        attempts = []
        def flaky(args, **kwargs):
            if args[0] == '/usr/bin/pkexec':
                attempts.append(args)
                if len(attempts) == 1:
                    raise ManagerError('SSL connection failed: certificate verify failed')
            return runner(args, **kwargs)
        manager, _ = self.apt(runner)
        manager.run = flaky
        self.assertTrue(manager.check_updates()['editor'].available)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        sleep.assert_called_once_with(1)

    @patch('app_manager.updates.time.sleep')
    def test_persistent_certificate_failure_stays_failed_with_separate_diagnostics(self, _):
        manager, runner = self.apt()
        runner.failure = 'E: Failed to fetch https://example.org/InRelease SSL connection failed: certificate verify failed'
        info = manager.check_updates()['editor']
        self.assertEqual(info.state, 'failed')
        self.assertIn('安全连接', info.note)
        self.assertNotIn('https://', info.note)
        self.assertIn('certificate verify failed', info.details)
        self.assertEqual(sum(a[0] == '/usr/bin/pkexec' for a in runner.calls), 2)

    @patch('app_manager.updates.time.sleep')
    def test_authorization_failure_is_not_retried(self, sleep):
        manager, runner = self.apt()
        runner.failure = '系统授权已取消'
        self.assertEqual(manager.check_updates()['editor'].state, 'failed')
        self.assertEqual(sum(a[0] == '/usr/bin/pkexec' for a in runner.calls), 1)
        sleep.assert_not_called()

    def test_candidate_equal_older_or_none_is_not_upgrade(self):
        for candidate in ("1.0", "0.9", "(none)", "0:99.0"):
            with self.subTest(candidate=candidate):
                manager, _ = self.apt(AptRunner(installed="1:1.0", candidate=candidate))
                self.assertEqual(manager.check_updates(False)["editor"].state, "current")

    def test_hold_preserved_with_architecture_suffix(self):
        manager, runner = self.apt()
        runner.held = "editor\n"
        self.assertEqual(manager.check_updates(False)["editor"].state, "held")
        with self.assertRaisesRegex(ManagerError, "锁定"):
            manager.plan_update("editor")

    def test_refresh_failure_discards_stale_offer(self):
        manager, runner = self.apt()
        manager.updates["editor"] = UpdateInfo("available", "9.0")
        runner.failure = "软件源不可访问"
        self.assertEqual(manager.check_updates()["editor"].state, "failed")
        self.assertFalse(any("install" in a for a in runner.calls))

    def test_missing_policy_or_removed_app_is_failure(self):
        for installed in ("", "(none)"):
            manager, _ = self.apt(AptRunner(installed=installed))
            self.assertEqual(manager.check_updates(False)["editor"].state, "failed")

    def test_unqualified_policy_matches_one_architecture(self):
        manager, _ = self.apt()
        manager.apps["editor"].package = "editor"
        self.assertTrue(manager.check_updates(False)["editor"].available)

    def test_native_architecture_suffix_can_be_omitted_in_policy_heading(self):
        import apt_pkg
        apt_pkg.init()
        manager, _ = self.apt(AptRunner(package="editor"))
        manager.apps["editor"].package = "editor:" + apt_pkg.config.find("APT::Architecture")
        self.assertTrue(manager.check_updates(False)["editor"].available)

    def test_apt_upgrade_reviews_dependencies_and_verifies_installed_version(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                manager, runner = self.apt(AptRunner(package=f"editor:{arch}"))
                plan = manager.plan_update("editor")
                self.assertTrue(any("dependency" in line for line in plan.changes))
                self.assertEqual(manager.update(plan), "done")
                command = next(a for a in runner.calls if a[0] == "/usr/bin/pkexec")
                self.assertIn("--only-upgrade", command)
                self.assertIn("--no-remove", command)
                self.assertEqual(command[-2:], ["--", f"editor:{arch}=1.1"])
                self.assertNotIn("upgrade", command)
                self.assertNotIn("autoremove", command)
                self.assertEqual(manager.updates, {})

    def test_removal_blocks_upgrade_preview(self):
        manager, runner = self.apt()
        runner.extra = "Remv desktop [1.0]\n"
        with self.assertRaisesRegex(ManagerError, "删除"):
            manager.plan_update("editor")
        self.assertFalse(any(a[0] == "/usr/bin/pkexec" for a in runner.calls))

    def test_unparseable_plan_never_executes(self):
        manager, runner = self.apt()
        runner.extra = "Inst -malicious (2.0 Ubuntu:26.04 [arm64])\n"
        with self.assertRaisesRegex(ManagerError, "标识无效"):
            manager.plan_update("editor")

    def test_candidate_or_dependency_drift_prevents_execution(self):
        for drift in ("candidate", "dependencies", "installed"):
            manager, runner = self.apt()
            plan = manager.plan_update("editor")
            if drift == "candidate":
                runner.candidate = "1.2"
            elif drift == "installed":
                runner.installed = "0.9"
            else:
                runner.extra = "Inst dependency (3.0 Ubuntu:26.04 [arm64])\n"
            with self.assertRaisesRegex(ManagerError, "已变化"):
                manager.update(plan)
            self.assertFalse(any(a[0] == "/usr/bin/pkexec" for a in runner.calls))

    def test_exit_zero_with_unchanged_version_is_failure(self):
        manager, runner = self.apt()
        runner.verify = False
        with self.assertRaisesRegex(ManagerError, "未确认目标版本"):
            manager.update(manager.plan_update("editor"))
        self.assertFalse(manager._lock.locked())

    def test_progress_completion_requires_verified_target(self):
        for verify in (True, False):
            manager, runner = self.apt()
            runner.verify = verify
            events = []
            if verify:
                manager.update(manager.plan_update("editor"), progress=events.append)
                self.assertEqual(events[-1].fraction, 1)
                self.assertIn("目标版本已确认", events[-1].stage)
            else:
                with self.assertRaises(ManagerError):
                    manager.update(manager.plan_update("editor"), progress=events.append)
                self.assertFalse(any(event.fraction == 1 for event in events))
            self.assertTrue(any("验证更新结果" in event.stage for event in events))
            self.assertFalse(manager._lock.locked())

    def test_authorization_cancel_and_timeout_release_operation_lock(self):
        for failure in ("系统授权已取消", "操作超时"):
            manager, runner = self.apt()
            runner.failure = failure
            with self.assertRaisesRegex(ManagerError, failure):
                manager.update(manager.plan_update("editor"))
            self.assertFalse(manager._lock.locked())

    def test_manual_and_invalid_identifiers_do_not_run_package_commands(self):
        manager = Manager(lambda *a, **kw: self.fail("must not execute"))
        for source, package, scope, state in (("手动安装", "", "", "unsupported"), ("APT", "editor;evil", "", "failed"),
                                               ("Snap", "-all", "", "failed"), ("Flatpak", "org.example.App", "all", "failed")):
            manager.apps = {"bad": Application("bad", "Bad", package, source, scope=scope)}
            self.assertEqual(manager.check_updates(False)["bad"].state, state)
            with self.assertRaises(ManagerError):
                manager.plan_update("bad")

    def test_operation_lock_covers_checks_updates_and_uninstalls(self):
        manager, _ = self.apt()
        plan = manager.plan_update("editor")
        manager._lock.acquire()
        try:
            for operation in (lambda: manager.check_updates(), lambda: manager.update(plan)):
                with self.assertRaisesRegex(ManagerError, "另一个"):
                    operation()
        finally:
            manager._lock.release()

    def snap(self, held=False, revision="10", target="11", unchanged=False):
        calls = []
        state = {"revision": revision}
        def runner(args, **kwargs):
            calls.append(args)
            if args[0] == "/usr/bin/pkexec":
                if not unchanged:
                    state["revision"] = target
                return "done"
            if "--list" in args:
                return f"Name Version Rev Publisher Notes\nbrowser 1.0 {target} publisher -\n" if target else ""
            return f"Name Version Rev Tracking Publisher Notes\nbrowser 1.0 {state['revision']} latest/stable publisher {'held' if held else '-'}\n"
        manager = Manager(runner)
        manager.apps["browser"] = Application("browser", "Browser", "browser", "Snap", "1.0")
        return manager, calls

    def test_snap_equal_version_different_revision_is_update(self):
        manager, calls = self.snap()
        self.assertTrue(manager.check_updates(False)["browser"].available)
        manager.update(manager.plan_update("browser"))
        command = next(a for a in calls if a[0] == "/usr/bin/pkexec")
        self.assertEqual(command[-2:], ["browser", "--revision=11"])
        self.assertNotIn("--channel", command)

    def test_snap_held_local_and_no_pending_update(self):
        for kwargs, state in (({"held": True}, "held"), ({"revision": "x1"}, "held"), ({"target": ""}, "current")):
            manager, _ = self.snap(**kwargs)
            self.assertEqual(manager.check_updates(False)["browser"].state, state)

    def test_snap_revision_postcheck_required(self):
        manager, _ = self.snap(unchanged=True)
        with self.assertRaisesRegex(ManagerError, "未确认目标版本"):
            manager.update(manager.plan_update("browser"))

    def flatpak(self, scope="user", unchanged=False, remote_failure=False, duplicate=False, masked=False, pending=True):
        calls = []
        old, new = "a" * 64, "b" * 64
        ref = "app/org.example.App/aarch64/stable"
        state = {"commit": old}
        def runner(args, **kwargs):
            calls.append(args)
            action = args[2] if args[0] == "/usr/bin/pkexec" else args[1]
            if action == "list":
                row = f"{ref}\t1.0\t{state['commit']}\tflathub\n"
                return row + (row.replace("stable", "beta") if duplicate else "")
            if action == "remote-ls":
                return f"{ref}\t1.0\tflathub\torg.gnome.Platform/aarch64/48\t{new}\n" if pending else ""
            if action == "mask":
                return "org.example.*\n" if masked else ""
            if action == "remote-info":
                if remote_failure:
                    raise ManagerError("源不可访问")
                return new
            if action == "update":
                if not unchanged:
                    state["commit"] = new
                return "done"
            if action == "info":
                return state["commit"]
            raise AssertionError(args)
        manager = Manager(runner)
        manager.apps["flatpak"] = Application("flatpak", "App", "org.example.App", "Flatpak", "1.0", scope=scope)
        return manager, calls, ref, new

    @patch("app_manager.updates.shutil.which", return_value="/usr/bin/flatpak")
    def test_flatpak_exact_ref_origin_commit_and_scope(self, _):
        for scope in ("user", "system"):
            manager, calls, ref, target = self.flatpak(scope=scope)
            self.assertTrue(manager.check_updates(False)["flatpak"].available)
            manager.update(manager.plan_update("flatpak"))
            command = next(a for a in calls if "update" in a)
            self.assertEqual(command[0] == "/usr/bin/pkexec", scope == "system")
            self.assertIn(f"--{scope}", command)
            self.assertIn(f"--commit={target}", command)
            self.assertEqual(command[-1], ref)
            self.assertTrue(all(f"--{scope}" in a for a in calls))

    @patch("app_manager.updates.shutil.which", return_value="/usr/bin/flatpak")
    def test_flatpak_commit_postcheck_and_ambiguous_branch(self, _):
        manager, _, _, _ = self.flatpak(unchanged=True)
        with self.assertRaisesRegex(ManagerError, "未确认目标版本"):
            manager.update(manager.plan_update("flatpak"))
        manager, _, _, _ = self.flatpak(duplicate=True)
        self.assertEqual(manager.check_updates(False)["flatpak"].state, "failed")

    @patch("app_manager.updates.shutil.which", return_value="/usr/bin/flatpak")
    def test_empty_flatpak_offer_cannot_hide_remote_failure(self, _):
        manager, _, _, _ = self.flatpak(pending=False, remote_failure=True)
        self.assertEqual(manager.check_updates(False)["flatpak"].state, "failed")

    @patch("app_manager.updates.shutil.which", return_value="/usr/bin/flatpak")
    def test_flatpak_masks_not_bypassed(self, _):
        manager, calls, _, _ = self.flatpak(masked=True)
        self.assertEqual(manager.check_updates(False)["flatpak"].state, "held")
        with self.assertRaisesRegex(ManagerError, "锁定"):
            manager.plan_update("flatpak")
        self.assertFalse(any("update" in a for a in calls))

    def test_one_source_failure_does_not_block_other_sources(self):
        apt_manager, apt_runner = self.apt()
        snap_manager, _ = self.snap()
        def runner(args, **kwargs):
            if "snap" in args[0]:
                return snap_manager.run(args, **kwargs)
            raise ManagerError("APT 源故障")
        manager = Manager(runner)
        manager.apps = {**apt_manager.apps, **snap_manager.apps}
        result = manager.check_updates(False)
        self.assertEqual(result["editor"].state, "failed")
        self.assertTrue(result["browser"].available)


if __name__ == "__main__":
    unittest.main()
