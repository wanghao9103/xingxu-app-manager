#!/usr/bin/python3
"""Generate native GTK screenshots and check sorting using synthetic apps only."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager.backend import Application, ManagerError
from app_manager.ui import App, Window, Gtk, GLib, Gdk


class PreviewManager:
    warnings = []

    def scan(self):
        mb = 1024 * 1024
        fixtures = [
            ("Calculator", "gnome-calculator", "APT", "46.1", 8, "2026-10-02 09:00:00", "accessories-calculator"),
            ("Files", "nautilus", "APT", "46.2", 22, "2026-09-20 10:00:00", "system-file-manager"),
            ("Image Viewer", "org.gnome.Loupe", "Flatpak", "46.3", 50, "", "image-x-generic"),
            ("Notes", "example-notes", "手动安装", "1.10", 18, "", "accessories-text-editor"),
            ("Text Editor", "gnome-text-editor", "APT", "46.2", 12, "2026-10-08 12:00:00", "text-x-generic"),
            ("Web Browser", "example-browser", "Snap", "130.0", 220, "", "web-browser"),
            ("星序", "miemie-app-manager", "手动安装", "1.1.2", 1, "", "applications-other"),
        ]
        return [Application(f"example-{i}.desktop", name, package, source, version,
                            size * mb, date, icon=icon)
                for i, (name, package, source, version, size, date, icon) in enumerate(fixtures)]

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
    report = {"synthetic_data_only": True, "uninstall_executed": False}

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
            win.sort.popup_for_device(Gdk.Display.get_default().get_default_seat().get_pointer())
            settle(400)
            assert win.sort.get_property("popup-shown")
            popup = win.sort.get_popup_accessible().get_widget()
            screenshot(popup.get_toplevel(), output / "sort-menu.png")
            win.sort.popdown()
            win.sort.set_active(0)
            win.set_focus(None)
            settle(400)
            screenshot(win, output / "main.png")
            report.update(passed=True, header_text_fits=True, column_sort_buttons_toggle_and_sync=True,
                          sort_popup_visible=True, unknown_dates_last=True)
        except Exception as exc:
            report.update(passed=False, error=str(exc))
        (output / "preview.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        app.quit()
        return False

    GLib.timeout_add(300, finish)
    app.run([])
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    sys.exit(main())
