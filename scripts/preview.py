#!/usr/bin/python3
"""Generate native GTK screenshots and check sorting using synthetic apps only."""
import json
from pathlib import Path
import sys
import time
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager.backend import Application, Manager, ManagerError, parse_packages
from app_manager.updates import UpdateInfo
from app_manager.progress import Progress
from app_manager import __version__
from app_manager.ui import App, Window, Gtk, GLib, Gdk, GdkPixbuf, ROOT, app_icon


class PreviewManager:
    warnings = []

    def __init__(self):
        self.apps = {}
        self.updates = {}

    def scan(self):
        mb = 1024 * 1024
        fixtures = [
            ("Calculator", "gnome-calculator", "APT", "46.1", 8, "2026-10-02 09:00:00", "accessories-calculator"),
            ("Files", "nautilus", "APT", "46.2", 22, "2026-09-20 10:00:00", "system-file-manager"),
            ("Image Viewer", "org.gnome.Loupe", "Flatpak", "46.3", 50, "", "image-x-generic"),
            ("Notes", "example-notes", "手动安装", "1.10", 18, "", "accessories-text-editor"),
            ("Text Editor", "gnome-text-editor", "APT", "46.2", 12, "2026-10-08 12:00:00", "text-x-generic"),
            ("Web Browser", "example-browser", "Snap", "130.0", 220, "", "web-browser"),
            ("星序", "miemie-app-manager", "手动安装", __version__, 1, "", "applications-other"),
        ]
        apps = [Application(f"example-{i}.desktop", name, package, source, version,
                            size * mb, date, icon=icon)
                for i, (name, package, source, version, size, date, icon) in enumerate(fixtures)]
        self.apps = {app.id: app for app in apps}
        self.updates = {}
        return apps

    def check_updates(self):
        self.updates = {app.id: UpdateInfo("unsupported" if app.source == "手动安装" else "current")
                        for app in self.apps.values()}
        for key, version in (("example-0.desktop", "46.2"), ("example-4.desktop", "47.0"), ("example-5.desktop", "131.0")):
            self.updates[key] = UpdateInfo("available", version, note="仅为界面示例，不是实际更新。")
        self.updates["example-1.desktop"] = UpdateInfo("failed", note="模拟软件源无法连接")
        return self.updates

    def plan(self, *_):
        raise ManagerError("截图示例仅使用模拟数据，不执行卸载。")


class PreviewApp(App):
    def do_activate(self):
        if not self.window:
            self.window = Window(self, PreviewManager())
        self.window.present()


def settle(milliseconds):
    loop = GLib.MainLoop()
    GLib.timeout_add(milliseconds, lambda: (loop.quit(), False)[1])
    loop.run()


def screenshot(widget, path):
    window = widget.get_window()
    geometry = window.get_geometry()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, geometry.width, geometry.height)
    if not pixbuf:
        raise RuntimeError("GTK screenshot failed")
    pixbuf.savev(str(path), "png", [], [])


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
    output.mkdir(parents=True, exist_ok=True)
    app = PreviewApp(smoke=True)
    started = time.monotonic()
    report = {"synthetic_data_only": True, "uninstall_executed": False, "real_update_executed": False}

    def finish():
        try:
            win = app.window
            if not win or win.scanning:
                if time.monotonic() - started > 20:
                    raise RuntimeError("preview timed out")
                return True
            assert len(win.apps) == 7
            for caption in (win.window_title, win.window_subtitle):
                width, height = caption.get_layout().get_pixel_size()
                allocation = caption.get_allocation()
                assert width <= allocation.width and height <= allocation.height
            for column, button in win.table_buttons.items():
                ascending, descending, default = win.sort_columns[column]
                win.sort.set_active(6)
                button.clicked()
                assert win.sort.get_active() == default
                button.clicked()
                assert win.sort.get_active() == (descending if default == ascending else ascending)
                assert button.get_style_context().has_class("active-sort")
                icon_name, _ = win.table_arrows[column].get_icon_name()
                assert icon_name == ("pan-up-symbolic" if win.sort.get_active() == ascending else "pan-down-symbolic")
            win.sort.set_active(2)
            dates = [a.installed_at for a in win.filtered() if a.installed_at]
            assert dates == sorted(dates, reverse=True)
            assert not win.filtered()[-1].installed_at
            settle(200)
            win.sort.popup_for_device(Gdk.Display.get_default().get_default_seat().get_pointer())
            settle(400)
            if not win.sort.get_property("popup-shown"):
                win.present()
                settle(300)
                win.sort.popup_for_device(Gdk.Display.get_default().get_default_seat().get_pointer())
                settle(400)
            assert win.sort.get_property("popup-shown"), 'sort menu did not open'
            popup = win.sort.get_popup_accessible().get_widget()
            screenshot(popup.get_toplevel(), output / "sort-menu.png")
            win.sort.popdown()
            win.sort.set_active(0)
            win.set_focus(None)
            settle(400)
            screenshot(win, output / "main.png")
            def row_buttons(widget):
                found = [widget] if isinstance(widget, Gtk.Button) else []
                if isinstance(widget, Gtk.Container):
                    for child in widget.get_children():
                        found.extend(row_buttons(child))
                return found
            assert not any(b.get_label() == '更新' for row in win.listbox.get_children() for b in row_buttons(row))
            # Check the asynchronous UI entry point, status text, filtering and busy controls.
            win.check_button.clicked()
            assert win.busy and not win.check_button.get_sensitive() and not win.refresh_button.get_sensitive()
            assert '正在刷新软件源并查询可用版本' in win.status.get_text()
            assert not any(term in win.status.get_text() for term in ('短时间', '首次', '需系统授权'))
            assert '需要系统授权' not in win.check_button.get_tooltip_text()
            report['update_check_status_does_not_claim_temporary_or_required_authentication'] = True
            deadline = time.monotonic() + 5
            while win.busy and time.monotonic() < deadline:
                settle(50)
            assert not win.busy and win.check_button.get_sensitive()
            assert "暂未完成检查" in win.status.get_text() and win.status_area.get_visible()
            assert win.status_details_button.get_visible()
            for row in win.listbox.get_children():
                buttons = [b for b in row_buttons(row) if b.get_label() == '更新']
                assert bool(buttons) == win.update_info(win.manager.apps[row.app_id]).available
            report['update_buttons_only_exist_for_available_updates'] = True
            win.set_mode("updates")
            assert len(win.filtered()) == 3 and all(win.update_info(a).available for a in win.filtered())
            win.search.set_text("calculator")
            settle(200)
            assert len(win.filtered()) == 1
            win.search.set_text("")
            settle(200)
            screenshot(win, output / "updates.png")
            win.set_mode("all")
            report['update_check_filter_search_and_busy_controls'] = True
            # One-time authorization settings: simulated only, no system policy changes.
            with patch('app_manager.ui.authorization_enabled', return_value=False), patch('app_manager.ui.set_authorization') as configure:
                dialog = win.make_authorization_dialog()
                assert dialog.authorization_target
                assert dialog.get_widget_for_response(Gtk.ResponseType.OK).get_label() == '授权一次，以后免密'
                settle(150)
                screenshot(dialog, output / 'authorization-enable.png')
                dialog.destroy()
                def auth_response(response):
                    def respond():
                        for dialog in Gtk.Window.list_toplevels():
                            if isinstance(dialog, Gtk.Dialog) and dialog.get_title() == '星序授权设置':
                                dialog.response(response)
                                return False
                        return True
                    GLib.timeout_add(30, respond)
                auth_response(Gtk.ResponseType.CANCEL)
                win.configure_authorization()
                configure.assert_not_called()
                auth_response(Gtk.ResponseType.OK)
                win.configure_authorization()
                assert win.busy and not win.authorize_button.get_sensitive()
                deadline = time.monotonic() + 3
                while win.busy and time.monotonic() < deadline:
                    settle(30)
                configure.assert_called_once()
                assert configure.call_args[0][0] is True
                assert not win.busy and win.authorize_button.get_sensitive()
                assert '一次授权已启用' in win.status.get_text()
            with patch('app_manager.ui.authorization_enabled', return_value=True), patch('app_manager.ui.set_authorization', side_effect=ManagerError('系统授权已取消')):
                dialog = win.make_authorization_dialog()
                assert not dialog.authorization_target
                assert dialog.get_widget_for_response(Gtk.ResponseType.OK).get_label() == '撤销授权'
                settle(150)
                screenshot(dialog, output / 'authorization-enabled.png')
                dialog.destroy()
                auth_response(Gtk.ResponseType.OK)
                win.configure_authorization()
                deadline = time.monotonic() + 3
                while win.busy and time.monotonic() < deadline:
                    settle(30)
                assert not win.busy and win.authorize_button.get_sensitive()
                assert win.status.get_style_context().has_class('error')
            report['one_time_authorization_dialog_cancel_success_failure_and_revoke'] = True

            # Regression for a failed APT certificate check: no raw log inline.
            raw = 'E: Failed to fetch https://example.org/debs/InRelease SSL connection failed: certificate verify failed [IP: 198.18.0.54 443]'
            win.show_status(raw, True)
            assert win.status_area.get_visible()
            assert '安全连接' in win.status.get_text()
            assert not any(term in win.status.get_text() for term in ('https://', 'SSL', 'certificate', '198.18.'))
            assert win.status_details_button.get_visible() and 'certificate verify failed' in win.status_details
            settle(200)
            screenshot(win, output / 'friendly-error.png')
            details = win.make_error_details_dialog(win.status_details)
            settle(150)
            screenshot(details, output / 'error-details.png')
            details.destroy()
            win.show_status('检查完成：3 个应用可更新。')
            assert not win.status_details_button.get_visible() and not win.status_details
            win.hide_status()
            assert not win.status_area.get_visible()
            report['raw_error_only_in_explicit_details_and_cleared_after_success'] = True

            # Exercise the real update preview/confirmation/worker/record/rescan paths.
            calls = []
            update_state = {"version": "1.0", "executed": False, "failure": False}
            update_target = Application('editor.desktop', 'Example Editor', 'example-editor', 'APT', '1.0')
            def update_runner(args, **kwargs):
                calls.append(args)
                if args[0] == '/usr/bin/apt-cache':
                    return f"example-editor:\n  Installed: {update_state['version']}\n  Candidate: 2.0\n"
                if args[0] == '/usr/bin/apt-mark':
                    return ''
                if args[0] == '/usr/bin/apt-get':
                    return f"Inst example-editor [{update_state['version']}] (2.0 Example [amd64])\nInst example-library (1.0 Example [amd64])\n"
                if args[0] == '/usr/bin/pkexec':
                    if update_state['failure']:
                        raise ManagerError('模拟系统授权取消')
                    progress = kwargs.get('progress')
                    if progress:
                        for event in (Progress('等待系统授权；已授权时将直接继续'),
                                      Progress('正在下载软件包', .42),
                                      Progress('正在安装和配置', .72)):
                            progress(event)
                            time.sleep(.65)
                    update_state.update(version='2.0', executed=True)
                    return 'Simulated upgrade'
                if args[0] == '/usr/bin/dpkg-query':
                    return 'installed\t' + update_state['version']
                raise AssertionError(args)
            update_manager = Manager(update_runner)
            update_manager.apps[update_target.id] = update_target
            def updated_scan():
                update_target.version = update_state['version']
                update_manager.updates = {}
                return [update_target]
            update_manager.scan = updated_scan
            update_manager.updates = update_manager.check_updates(refresh=False)
            win.manager = update_manager
            win.apps = [update_target]
            win.render()
            plan = update_manager.plan_update(update_target.id)
            dialog = win.make_update_dialog(plan)
            settle(200)
            screenshot(dialog, output / 'update-confirm.png')
            dialog.destroy()
            def respond_update(response):
                def respond():
                    for dialog in Gtk.Window.list_toplevels():
                        if isinstance(dialog, Gtk.Dialog) and dialog.get_transient_for() == win:
                            assert dialog.get_title() == '确认更新'
                            dialog.response(response)
                            return False
                    return True
                GLib.timeout_add(50, respond)
            with tempfile.TemporaryDirectory() as state:
                original_history = win.history_path
                win.history_path = Path(state) / 'history.json'
                respond_update(Gtk.ResponseType.CANCEL)
                win.confirm_update(plan)
                assert not update_state['executed'] and not win.history_path.exists()
                report['update_cancel_executes_nothing'] = True
                captured_progress = set()
                def capture_progress():
                    if win.progress_area.get_visible() and win._progress_timer is not None:
                        assert win.progress_elapsed.get_text().startswith('已用时 ')
                        assert not win.check_button.get_sensitive()
                        if win.progress_percent.get_text() == '进行中':
                            captured_progress.add('waiting')
                        if win.progress_stage.get_text() == '正在下载软件包':
                            assert abs(win.progress_bar.get_fraction() - .42) < .001
                            if 'download' not in captured_progress:
                                screenshot(win, output / 'update-progress.png')
                            captured_progress.add('download')
                        if win.progress_stage.get_text() == '正在安装和配置':
                            captured_progress.add('install')
                    return not update_state['executed']
                GLib.timeout_add(100, capture_progress)
                respond_update(Gtk.ResponseType.OK)
                win.prepare_update(update_target)
                deadline = time.monotonic() + 5
                while (win.busy or win.scanning or not update_state['executed']) and time.monotonic() < deadline:
                    settle(50)
                assert update_state['executed'] and not win.busy and not win.scanning
                assert win.apps[0].version == '2.0'
                assert captured_progress == {'waiting', 'download', 'install'}, captured_progress
                assert win.progress_percent.get_text() == '100%'
                assert win.progress_area.get_visible() and win._progress_timer is None
                old_generation = win._progress_generation - 1
                win.queue_progress(old_generation, Progress('过期消息', .1))
                win.progress_tick()
                assert win.progress_percent.get_text() == '100%'
                report['live_update_progress_phases_timer_and_stale_events'] = True
                assert not win.update_info(win.apps[0]).available
                record = json.loads(win.history_path.read_text())[0]
                assert record['status'] == '已更新' and record['operation'] == '更新'
                win.set_mode('history')
                settle(200)
                screenshot(win, output / 'update-history.png')
                win.set_mode('all')
                # A failed command must record failure and restore controls after rescanning.
                update_state.update(version='1.0', executed=False, failure=True)
                update_target.version = '1.0'
                plan = update_manager.plan_update(update_target.id)
                def close_update_error():
                    for dialog in Gtk.Window.list_toplevels():
                        if isinstance(dialog, Gtk.MessageDialog) and dialog.get_transient_for() == win:
                            dialog.response(Gtk.ResponseType.CLOSE)
                            return False
                    return True
                GLib.timeout_add(50, close_update_error)
                respond_update(Gtk.ResponseType.OK)
                win.confirm_update(plan)
                deadline = time.monotonic() + 5
                while (win.busy or win.scanning) and time.monotonic() < deadline:
                    settle(50)
                assert not win.busy and not win.scanning and win.check_button.get_sensitive()
                assert json.loads(win.history_path.read_text())[0]['status'] == '更新未完成'
                assert not win.progress_area.get_visible() and win._progress_timer is None
                report['failure_clears_progress_without_false_completion'] = True
                report['update_failure_records_failure_rescans_and_restores_controls'] = True
                win.history_path = original_history
            report['simulated_update_preview_confirm_execute_verify_record_rescan'] = True
            # A deleted user theme icon must not replace our bundled star with a missing icon.
            target = Application('io.miemie.AppManager.desktop', '星序应用管理', 'miemie-app-manager', 'APT',
                                 __version__, icon='/nonexistent/old-user-icon.png')
            actual = app_icon(target).get_pixbuf()
            expected = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ROOT / 'assets/icon.png'), 40, 40, True)
            assert actual.get_pixels() == expected.get_pixels()
            report['self_icon_survives_missing_theme_file'] = True
            # Drive the real confirmation/worker/exit flow; package commands are simulated.
            calls = []
            def runner(args, **kwargs):
                calls.append(args)
                if args[0] == '/usr/bin/apt-get':
                    return f'Remv miemie-app-manager [{__version__}]\n'
                if args[0] == '/usr/bin/dpkg-query':
                    return 'config-files'
                return 'Simulated self removal'
            manager = Manager(runner)
            manager.packages = parse_packages(f'miemie-app-manager\tinstalled\t{__version__}\t100\tno\toptional\n')
            manager.apps[target.id] = target
            win.manager = manager
            win.apps = [target]
            quit_calls = []
            original_quit = app.quit
            app.quit = lambda: quit_calls.append(True)
            with tempfile.TemporaryDirectory() as state:
                win.history_path = Path(state) / 'history.json'
                def accept_self_dialog():
                    for dialog in Gtk.Window.list_toplevels():
                        if isinstance(dialog, Gtk.Dialog) and dialog.get_transient_for() == win:
                            assert dialog.get_widget_for_response(Gtk.ResponseType.OK).get_sensitive()
                            dialog.response(Gtk.ResponseType.OK)
                            return False
                    return True
                GLib.timeout_add(100, accept_self_dialog)
                win.confirm_uninstall(manager.plan(target.id))
                deadline = time.monotonic() + 5
                while not quit_calls and time.monotonic() < deadline:
                    settle(100)
                assert quit_calls and not win.busy
                assert json.loads(win.history_path.read_text())[0]['status'] == '已卸载'
                assert next(args for args in calls if args[0] == '/usr/bin/pkexec')[-2:] == ['--', 'miemie-app-manager']
            app.quit = original_quit
            report['simulated_self_uninstall_confirmation_and_exit'] = True
            report.update(passed=True, header_text_fits=True, column_sort_buttons_toggle_and_sync=True,
                          sort_popup_visible=True, unknown_dates_last=True)
        except Exception as exc:
            report.update(passed=False, error=repr(exc))
        (output / "preview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        app.quit()
        return False

    GLib.timeout_add(300, finish)
    app.run([])
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
