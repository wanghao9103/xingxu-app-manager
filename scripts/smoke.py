"""Real GTK/Gio/dpkg smoke, screenshot and cancellation. Never uninstalls."""
import json
from pathlib import Path
import sys
import time
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager.ui import App, GLib, Gdk, Gtk
import gi
gi.require_version("GdkX11", "3.0")
from gi.repository import GdkX11

output = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
output.mkdir(parents=True, exist_ok=True)
app = App(smoke=True)
report = {}
started = time.monotonic()


def screenshot(widget, filename):
    window = widget.get_window()
    geometry = window.get_geometry()
    pixbuf = Gdk.pixbuf_get_from_window(window, 0, 0, geometry.width, geometry.height)
    if not pixbuf:
        raise RuntimeError("window screenshot failed")
    pixbuf.savev(str(output / filename), "png", [], [])


def finish():
    try:
        win = app.window
        if not win or win.scanning:
            if time.monotonic() - started > 90:
                raise RuntimeError("scan did not complete")
            return True
        assert len(win.apps) > 0, f"no installed applications found: {win.status.get_text()}"
        report["application_count"] = len(win.apps)
        report["sources"] = sorted({a.source for a in win.apps})
        report["known_install_dates"] = sum(bool(a.installed_at) for a in win.apps)
        for caption in (win.window_title, win.window_subtitle):
            width, height = caption.get_layout().get_pixel_size()
            allocation = caption.get_allocation()
            assert allocation.height >= height, f"header text clipped: {caption.get_text()}"
            assert allocation.width >= width, f"header text width clipped: {caption.get_text()}"
        report["header_text_fits"] = True
        xid = GdkX11.X11Window.get_xid(win.get_window())
        identity = subprocess.check_output(["xprop", "-id", hex(xid), "WM_CLASS", "_GTK_APPLICATION_ID"], text=True)
        assert '"io.miemie.AppManager"' in identity
        report["window_identity"] = identity.strip()
        screenshot(win, "main.png")
        # Immediate filtering, sources, no results, then restoration.
        win.search.set_text("gnome-calculator")
        win.render()
        assert all("gnome-calculator" in (a.name + " " + a.package).casefold() for a in win.filtered())
        report["search_matches"] = len(win.filtered())
        assert report["search_matches"] > 0
        win.search.set_text("__no_application_matches_this__")
        win.render()
        assert not win.filtered()
        report["no_results"] = True
        win.search.set_text("")
        win.set_mode("Snap")
        assert all(a.source == "Snap" for a in win.filtered())
        report["snap_filtered"] = len(win.filtered())
        win.set_mode("all")
        win.sort.set_active(2)
        dates = [a.installed_at for a in win.filtered() if a.installed_at]
        assert dates == sorted(dates, reverse=True)
        win.sort.set_active(5)
        dates = [a.installed_at for a in win.filtered() if a.installed_at]
        assert dates == sorted(dates)
        report["installation_date_sort_both_directions"] = True
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
        report["column_sort_buttons_toggle_and_sync"] = True
        win.sort.set_active(2)
        win.sort.popup_for_device(Gdk.Display.get_default().get_default_seat().get_pointer())
        loop = GLib.MainLoop()
        GLib.timeout_add(400, lambda: (loop.quit(), False)[1])
        loop.run()
        popup = win.sort.get_popup_accessible().get_widget()
        assert win.sort.get_property("popup-shown"), "sort popup did not open"
        screenshot(popup.get_toplevel(), "sort-menu.png")
        report["sort_popup_visible"] = True
        win.sort.popdown()
        from app_manager.backend import Plan
        risk_plan = Plan(win.apps[0], ['gdm3'], ('fixture',), risky=['gdm3'])
        risk_dialog = win.make_confirm_dialog(risk_plan)
        confirm_button = risk_dialog.get_widget_for_response(Gtk.ResponseType.OK)
        assert not confirm_button.get_sensitive()
        risk_dialog.risk_entry.set_text(risk_plan.app.name)
        assert confirm_button.get_sensitive()
        risk_dialog.destroy()
        report['system_component_name_confirmation'] = True
        win.sort.set_active(0)
        loop = GLib.MainLoop()
        GLib.timeout_add(150, lambda: (loop.quit(), False)[1])
        loop.run()
        screenshot(win, "main.png")
        manual_apps = [a for a in win.apps if a.source == "手动安装"]
        report["manual_plans"] = {}
        for manual_app in manual_apps:
            manual_plan = win.manager.plan(manual_app.id)
            assert manual_plan.manual and manual_plan.removed
            report["manual_plans"][manual_app.name] = len(manual_plan.removed)
        cloud = next((a for a in manual_apps if a.name == "CloudTune"), None)
        if cloud:
            cloud_dialog = win.make_confirm_dialog(win.manager.plan(cloud.id))
            def cancel_cloud():
                screenshot(cloud_dialog, "manual-confirm.png")
                cloud_dialog.response(Gtk.ResponseType.CANCEL)
            GLib.timeout_add(400, cancel_cloud)
            assert cloud_dialog.run() == Gtk.ResponseType.CANCEL
            cloud_dialog.destroy()
        target = next(a for a in win.apps if a.package == "gnome-calculator")
        plan = win.manager.plan(target.id)
        report["simulation_target"] = plan.app.package
        report["simulation_removals"] = plan.removed
        dialog = win.make_confirm_dialog(plan)
        def cancel():
            screenshot(dialog, "confirm.png")
            dialog.response(Gtk.ResponseType.CANCEL)
        GLib.timeout_add(400, cancel)
        assert dialog.run() == Gtk.ResponseType.CANCEL
        dialog.destroy()
        report["confirmation_cancel"] = True
        report["uninstall_executed"] = False
        report["warnings"] = win.manager.warnings
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc)
    (output / "native-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    app.quit()
    return False


GLib.timeout_add(500, finish)
app.run([])
sys.exit(0 if report.get("passed") else 1)
