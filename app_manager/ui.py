from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timedelta
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk, GdkPixbuf
from .backend import Manager, ManagerError, format_size, bare_package, run as run_command
from .privileges import authorization_enabled, set_authorization
from .updates import UpdateInfo, update_status
from .errors import friendly_error, diagnostic_text
from .progress import Progress
from . import __version__

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "io.miemie.AppManager"

CSS = b"""
window { background: #0c1220; color: #e0eafa; font-family: 'Noto Sans CJK SC', 'Ubuntu', sans-serif; font-size: 13px; }
headerbar { background: #131d2f; border-bottom: 1px solid #27364b; box-shadow: none; }
.sidebar { background: #131d2f; border-right: 1px solid #253349; }
.brand { font-size: 20px; font-weight: 700; color: #eff7ff; }
.muted { color: #95a7bf; font-size: 12px; }
.title { font-size: 26px; font-weight: 700; }
.section { color: #7a90ab; font-size: 11px; font-weight: 600; }
.nav { background: transparent; border: none; border-radius: 9px; padding: 12px 14px; box-shadow: none; color: #a0afc4; }
.nav:hover { background: #17253a; }
.nav.active { background: #12313e; color: #59d9e8; font-weight: 600; }
.card { background: #131d2f; border: 1px solid #2a3e57; border-radius: 12px; padding: 19px; }
.metric { font-size: 28px; font-weight: 700; }
.metric-icon { color: #60dfed; background: #153c49; border-radius: 10px; padding: 12px; }
entry { background: #131d2f; border: 1px solid #2b3d55; border-radius: 8px; padding: 8px 10px; box-shadow: none; }
entry:focus { border-color: #51b6c8; }
button { background: #131d2f; border: 1px solid #31435e; border-radius: 7px; padding: 7px 13px; box-shadow: none; color: #b2c4dd; }
button:hover { background: #213850; border-color: #468a9e; }
button:disabled { color: #64758c; background: #152031; }
.primary { background: #177f92; color: #131d2f; border-color: #177f92; font-weight: 600; }
.primary:hover { background: #209aab; color: #131d2f; }
.danger { color: #efb0be; background: #131d2f; border-color: #523348; }
.danger:hover { background: #442438; border-color: #b45b7c; }
.table { background: #131d2f; border: 1px solid #2a3b52; border-radius: 12px; }
.table-header { background: #172337; padding: 12px 18px; border-bottom: 1px solid #2a3e57; color: #8fa6c3; font-size: 12px; }
list { background: #131d2f; }
row { padding: 12px 18px; border-bottom: 1px solid #203047; }
row:hover { background: #17283d; }
row:selected { background: #18354a; color: #e0eafa; }
.app-name { font-weight: 600; font-size: 14px; }
.app-meta { font-size: 11px; color: #889cb8; }
.badge { background: #302747; color: #c3acf4; border-radius: 4px; padding: 2px 6px; font-size: 10px; }
.badge.snap { background: #19362e; color: #8fd6b4; }
.badge.manual { background: #18364a; color: #80c7e3; }
.status { background: #173544; color: #9edce8; border-radius: 8px; padding: 10px 14px; }
.error { background: #392131; color: #f0b1be; }
.empty-title { font-size: 18px; font-weight: 600; }
.detail-title { font-size: 21px; font-weight: 700; }
.note { background: #17253a; border-radius: 8px; padding: 12px; color: #b7cce4; }
combobox button { padding: 7px 12px; }
scrolledwindow { background: transparent; }
dialog { background: #131d2f; }
tooltip { background: #213650; color: #131d2f; }
label { color: #d3e0f2; }
button label { color: inherit; }
headerbar .subtitle { color: #91a6c0; }
headerbar { min-height: 44px; padding: 6px 12px; }
headerbar .window-title { font-size: 14px; font-weight: 600; color: #eaf5ff; }
headerbar .window-subtitle { font-size: 11px; font-weight: 400; color: #a4b6ce; }
headerbar button { padding: 5px 10px; min-height: 24px; }
menu, popover, .menu { background: #172337; color: #d3e0f2; border: 1px solid #3d5674; }
menuitem { background: #172337; color: #d3e0f2; padding: 9px 13px; }
menuitem label { color: #d3e0f2; }
menuitem:hover, menuitem:selected { background: #245065; color: #8eeaf2; }
menuitem:hover label, menuitem:selected label { color: #8eeaf2; }
.column-sort { background: transparent; border: none; border-radius: 4px; padding: 0; color: #a3b9d3; box-shadow: none; }
.column-sort:hover { background: #203a4b; color: #e4f5ff; }
.column-sort.active-sort { color: #6fdfeb; }
.column-sort label { color: #a3b9d3; }
.column-sort.active-sort label { color: #6fdfeb; }
.column-sort:hover label { color: #e4f5ff; }
.sort-arrow { font-size: 12px; color: #708fae; }
.active-sort .sort-arrow { color: #6fdfeb; }
.app-name, .title, .metric, .brand, .detail-title { color: #eaf5ff; }
.card { background-image: linear-gradient(135deg, #192639, #131d2e); }
.metric-icon { border: 1px solid #226172; }
.nav.active { border: 1px solid #20586a; }
.danger { background: #251e31; }
.primary, .primary:hover, tooltip { color: #fff; }
entry { color: #e3efff; caret-color: #69deec; }
headerbar { color: #eaf5ff; background: #101828; }
.sidebar { background: #101828; }
.update-progress { background: #142a37; border: 1px solid #246074; border-radius: 10px; padding: 14px 16px; }
progressbar trough { background: #24384b; border: none; border-radius: 5px; min-height: 9px; }
progressbar progress { background: #53cddd; border: none; border-radius: 5px; min-height: 9px; }
"""


def style(widget, *names):
    for name in names:
        widget.get_style_context().add_class(name)
    return widget


def label(text, cls=None, xalign=0):
    obj = Gtk.Label(label=text, xalign=xalign)
    if cls:
        style(obj, cls)
    return obj


def box(vertical=False, spacing=0):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)


def margins(widget, value):
    widget.set_margin_top(value)
    widget.set_margin_bottom(value)
    widget.set_margin_start(value)
    widget.set_margin_end(value)
    return widget


def icon(name, size=20):
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    return image


def app_icon(app, size=40):
    if app.id == APP_ID + ".desktop" or app.package.split(":", 1)[0] == "miemie-app-manager":
        return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ROOT / "assets/icon.png"), size, size, True))
    if app.icon.startswith("/") and Path(app.icon).is_file():
        try:
            return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(app.icon, size, size, True))
        except GLib.Error:
            pass
    theme = Gtk.IconTheme.get_default()
    info = theme.lookup_icon(app.icon, size, Gtk.IconLookupFlags.FORCE_SIZE)
    if info:
        try:
            return Gtk.Image.new_from_pixbuf(info.load_icon())
        except GLib.Error:
            pass  # A stale theme cache may refer to a removed user icon.
    return icon("application-x-executable", size)


def removes_running_manager(plan):
    return bool((plan.manual and ROOT in plan.manual.targets) or
                (plan.app.source == "APT" and plan.app.package.split(":", 1)[0] == "miemie-app-manager"))


class Window(Gtk.ApplicationWindow):
    def __init__(self, application, manager=None):
        super().__init__(application=application, title="星序 · 应用管理")
        self.set_default_size(1320, 790)
        self.set_size_request(1180, 620)
        self.set_icon_from_file(str(ROOT / "assets/icon.svg"))
        self.manager = manager or Manager()
        self.apps = []
        self.mode = "all"
        self.busy = False
        self.scanning = False
        self._progress_timer = None
        self._progress_generation = 0
        self._pending_progress = None
        self.nav_buttons = {}
        self.history_path = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "miemie-app-manager/history.json"
        self.connect("delete-event", self.on_close)
        self.connect("key-press-event", self.on_key)
        header = Gtk.HeaderBar()
        header_title = box(True, 2)
        header_title.set_valign(Gtk.Align.CENTER)
        self.window_title = label("星序 · 应用管理", "window-title", .5)
        self.window_subtitle = label("掌控应用，保持有序", "window-subtitle", .5)
        header_title.pack_start(self.window_title, False, False, 0)
        header_title.pack_start(self.window_subtitle, False, False, 0)
        header.set_custom_title(header_title)
        header.set_show_close_button(True)
        self.set_titlebar(header)
        layout = box()
        self.add(layout)
        sidebar = style(box(True), "sidebar")
        sidebar.set_size_request(210, -1)
        layout.pack_start(sidebar, False, False, 0)
        brand = margins(box(spacing=10), 24)
        brand.pack_start(Gtk.Image.new_from_file(str(ROOT / "assets/brand.svg")), False, False, 0)
        brand.pack_start(label("星序", "brand"), False, False, 0)
        sidebar.pack_start(brand, False, False, 0)
        caption = label("应用管理", "section")
        caption.set_margin_start(27)
        caption.set_margin_top(10)
        caption.set_margin_bottom(12)
        sidebar.pack_start(caption, False, False, 0)
        self.add_nav(sidebar, "all", "全部应用", "view-grid-symbolic")
        self.add_nav(sidebar, "updates", "可更新应用", "software-update-available-symbolic")
        self.add_nav(sidebar, "recent", "最近安装", "document-open-recent-symbolic")
        self.add_nav(sidebar, "large", "大型应用", "drive-harddisk-symbolic")
        caption = label("按安装来源", "section")
        caption.set_margin_start(27)
        caption.set_margin_top(30)
        caption.set_margin_bottom(12)
        sidebar.pack_start(caption, False, False, 0)
        for mode, title, image in (("APT", "APT / Debian", "package-x-generic-symbolic"), ("Snap", "Snap 应用", "application-x-addon-symbolic"), ("Flatpak", "Flatpak 应用", "folder-symbolic"), ("手动安装", "手动安装", "folder-download-symbolic")):
            self.add_nav(sidebar, mode, title, image)
        sidebar.pack_start(box(), True, True, 0)
        self.authorize_button = style(Gtk.Button(label="授权设置"), "nav")
        self.authorize_button.set_margin_start(13)
        self.authorize_button.set_margin_end(13)
        self.authorize_button.connect("clicked", self.configure_authorization)
        sidebar.pack_start(self.authorize_button, False, False, 0)
        self.add_nav(sidebar, "history", "操作记录", "document-text-symbolic")
        about = Gtk.Button(label=f"关于 · 版本 {__version__}")
        style(about, "nav")
        about.connect("clicked", self.about)
        sidebar.pack_start(margins(about, 15), False, False, 0)

        main = margins(box(True, 22), 30)
        layout.pack_start(main, True, True, 0)
        heading = box(spacing=12)
        titles = box(True, 6)
        self.heading = label("全部应用", "title")
        self.subtitle = label("查看安装信息，快速搜索，一处管理所有应用。", "muted")
        self.subtitle.set_ellipsize(3)
        titles.pack_start(self.heading, False, False, 0)
        titles.pack_start(self.subtitle, False, False, 0)
        heading.pack_start(titles, True, True, 0)
        self.refresh_button = Gtk.Button()
        refresh = box(spacing=7)
        refresh.pack_start(icon("view-refresh-symbolic", 16), False, False, 0)
        refresh.pack_start(label("刷新列表"), False, False, 0)
        self.refresh_button.add(refresh)
        self.refresh_button.set_valign(Gtk.Align.CENTER)
        self.refresh_button.connect("clicked", lambda _: self.scan())
        heading.pack_start(self.refresh_button, False, False, 0)
        self.check_button = style(Gtk.Button(label="检查更新"), "primary")
        self.check_button.set_valign(Gtk.Align.CENTER)
        self.check_button.set_tooltip_text("刷新 APT 软件源索引（需要系统授权），并检查 Snap / Flatpak 更新；不会升级应用。")
        self.check_button.connect("clicked", lambda _: self.check_updates())
        heading.pack_start(self.check_button, False, False, 0)
        main.pack_start(heading, False, False, 0)

        metrics = box(spacing=14)
        self.metric_labels = []
        for title, desc, image in (("已安装应用", "桌面应用，不含后台依赖", "view-grid-symbolic"), ("应用占用空间", "已知大小，按软件包去重", "drive-harddisk-symbolic"), ("最近 30 天安装", "仅统计有准确安装记录的应用", "document-open-recent-symbolic")):
            card = style(box(spacing=15), "card")
            text = box(True, 6)
            text.pack_start(label(title, "muted"), False, False, 0)
            value = label("—", "metric")
            self.metric_labels.append(value)
            text.pack_start(value, False, False, 0)
            text.pack_start(label(desc, "app-meta"), False, False, 0)
            card.pack_start(text, True, True, 0)
            badge = style(icon(image, 25), "metric-icon")
            badge.set_valign(Gtk.Align.START)
            card.pack_start(badge, False, False, 0)
            metrics.pack_start(card, True, True, 0)
        main.pack_start(metrics, False, False, 0)

        toolbar = box(spacing=12)
        self.search = Gtk.SearchEntry(placeholder_text="搜索应用名称或软件包…")
        self.search.set_tooltip_text("Ctrl+F 搜索")
        self.search.connect("search-changed", lambda _: self.render())
        toolbar.pack_start(self.search, True, True, 0)
        self.sort = Gtk.ComboBoxText()
        for item in ("名称 A → Z", "占用空间：大 → 小", "安装时间：新 → 旧", "名称 Z → A", "占用空间：小 → 大", "安装时间：旧 → 新", "安装来源", "版本：高 → 低", "版本：低 → 高"):
            self.sort.append_text(item)
        self.sort.set_active(0)
        self.sort.connect("changed", lambda _: self.render())
        toolbar.pack_start(self.sort, False, False, 0)
        main.pack_start(toolbar, False, False, 0)
        self.status = style(label("正在读取本机已安装应用…"), "status")
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(100)
        self.status.set_no_show_all(True)
        self.status_area = box(spacing=10)
        self.status_area.set_no_show_all(True)
        self.status_area.pack_start(self.status, True, True, 0)
        self.status_details = ""
        self.status_details_button = Gtk.Button(label="查看详情")
        self.status_details_button.set_halign(Gtk.Align.START)
        self.status_details_button.set_no_show_all(True)
        self.status_details_button.connect("clicked", lambda _: self.show_error_details())
        self.status_details_button.set_valign(Gtk.Align.CENTER)
        self.status_area.pack_start(self.status_details_button, False, False, 0)
        main.pack_start(self.status_area, False, False, 0)

        self.progress_area = style(box(True, 9), "update-progress")
        self.progress_area.set_no_show_all(True)
        progress_heading = box(spacing=14)
        self.progress_title = label("", "app-name")
        self.progress_title.set_ellipsize(3)
        progress_heading.pack_start(self.progress_title, True, True, 0)
        self.progress_elapsed = label("", "muted")
        progress_heading.pack_start(self.progress_elapsed, False, False, 0)
        self.progress_area.pack_start(progress_heading, False, False, 0)
        progress_caption = box(spacing=14)
        self.progress_stage = label("")
        self.progress_stage.set_ellipsize(3)
        progress_caption.pack_start(self.progress_stage, True, True, 0)
        self.progress_percent = label("", "muted")
        progress_caption.pack_start(self.progress_percent, False, False, 0)
        self.progress_area.pack_start(progress_caption, False, False, 0)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_pulse_step(.06)
        self.progress_bar.get_accessible().set_name("当前更新阶段的进度")
        self.progress_area.pack_start(self.progress_bar, False, False, 0)
        main.pack_start(self.progress_area, False, False, 0)

        table = style(box(True), "table")
        self.table_header = style(box(spacing=12), "table-header")
        self.table_buttons = {}
        self.table_arrows = {}
        self.sort_columns = {"应用名称": (0, 3, 0), "版本": (8, 7, 7), "占用空间": (4, 1, 1), "安装时间": (5, 2, 2)}
        for title, width, expand in (("应用名称", 180, True), ("版本", 150, False), ("占用空间", 95, False), ("安装时间", 115, False), ("操作", 190, False)):
            if title in self.sort_columns:
                cell = style(Gtk.Button(), "column-sort")
                caption = box(spacing=6)
                caption.pack_start(label(title), False, False, 0)
                arrow = style(icon("pan-down-symbolic", 12), "sort-arrow")
                caption.pack_start(arrow, False, False, 0)
                cell.add(caption)
                cell.set_tooltip_text("点击切换升序 / 降序")
                cell.connect("clicked", lambda _, key=title: self.column_sort(key))
                self.table_buttons[title] = cell
                self.table_arrows[title] = arrow
            else:
                cell = label(title)
            cell.set_size_request(width, -1)
            self.table_header.pack_start(cell, expand, expand, 0)
        table.pack_start(self.table_header, False, False, 0)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.connect("row-activated", self.on_row)
        self.scroller.add(self.listbox)
        table.pack_start(self.scroller, True, True, 0)
        main.pack_start(table, True, True, 0)
        self.footer = label("安装时间来自系统日志；没有可靠记录时显示「未知」。", "muted")
        main.pack_start(self.footer, False, False, 0)
        self.show_all()
        self.status.show()
        self.status_area.show()
        self.scan()

    def add_nav(self, sidebar, mode, title, image):
        button = style(Gtk.Button(), "nav")
        row = box(spacing=12)
        row.pack_start(icon(image, 18), False, False, 0)
        row.pack_start(label(title), False, False, 0)
        button.add(row)
        button.set_margin_start(13)
        button.set_margin_end(13)
        button.set_margin_bottom(4)
        button.connect("clicked", lambda _: self.set_mode(mode))
        sidebar.pack_start(button, False, False, 0)
        self.nav_buttons[mode] = button

    def set_mode(self, mode):
        self.mode = mode
        if mode == "recent":
            self.sort.set_active(2)
        elif mode == "large":
            self.sort.set_active(1)
        self.render()

    def column_sort(self, column):
        ascending, descending, default = self.sort_columns[column]
        active = self.sort.get_active()
        self.sort.set_active(descending if active == ascending else ascending if active == descending else default)

    def update_sort_arrows(self):
        current = self.sort.get_active()
        for column, button in self.table_buttons.items():
            ascending, descending, _ = self.sort_columns[column]
            selected = current in (ascending, descending)
            context = button.get_style_context()
            (context.add_class if selected else context.remove_class)("active-sort")
            self.table_arrows[column].set_from_icon_name("pan-up-symbolic" if current == ascending else "pan-down-symbolic", Gtk.IconSize.BUTTON)
            self.table_arrows[column].set_pixel_size(12)

    def on_key(self, _, event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
                self.search.grab_focus()
                return True
            if event.keyval in (Gdk.KEY_r, Gdk.KEY_R):
                self.scan()
                return True
        return False

    def on_close(self, *_):
        if self.busy:
            self.show_status("正在处理软件管理操作，请等待完成后再关闭窗口。", True)
            return True
        return False

    def show_status(self, text, error=False, details=""):
        readable = friendly_error(text) if error else text
        self.status_details = diagnostic_text(details or (text if readable != text else ""))
        self.status_details_button.set_visible(bool(self.status_details))
        self.status.set_text(readable)
        context = self.status.get_style_context()
        (context.add_class if error else context.remove_class)("error")
        self.status.show()
        self.status_area.show()

    def hide_status(self):
        self.status.hide()
        self.status_area.hide()
        self.status_details_button.hide()
        self.status_details = ""

    def start_progress(self, name):
        self.end_progress(False)
        self._progress_started = time.monotonic()
        self._pending_progress = (self._progress_generation, Progress("正在复核更新版本与影响范围"))
        self.progress_title.set_text(f"正在更新 {name}")
        self.progress_bar.set_fraction(0)
        for child in self.progress_area.get_children():
            child.show_all()
        self.progress_area.show()
        self.progress_tick()
        self._progress_timer = GLib.timeout_add(200, self.progress_tick)
        return self._progress_generation

    def queue_progress(self, generation, event):
        # Worker threads only replace this tuple. GTK is updated by the UI timer,
        # so verbose package output cannot flood the GTK main loop.
        self._pending_progress = (generation, event)

    def progress_tick(self):
        pending = self._pending_progress
        if pending and pending[0] == self._progress_generation:
            event = pending[1]
            self.progress_stage.set_text(event.stage)
            if event.fraction is None:
                self.progress_percent.set_text("进行中")
                self.progress_bar.pulse()
            else:
                # APT can complete a phase before final version verification.
                fraction = max(0, min(1, event.fraction))
                self.progress_bar.set_fraction(fraction)
                self.progress_percent.set_text(f"{fraction:.0%}")
        elapsed = int(time.monotonic() - self._progress_started)
        self.progress_elapsed.set_text(f"已用时 {elapsed // 60:02d}:{elapsed % 60:02d}")
        return True

    def end_progress(self, success):
        if self._progress_timer is not None:
            GLib.source_remove(self._progress_timer)
            self._progress_timer = None
        self._progress_generation += 1
        self._pending_progress = None
        if success:
            self.progress_title.set_text("更新完成")
            self.progress_stage.set_text("目标版本已确认，可以继续更新其他应用")
            self.progress_percent.set_text("100%")
            self.progress_bar.set_fraction(1)
        else:
            self.progress_area.hide()

    def make_error_details_dialog(self, details):
        dialog = Gtk.Dialog(title="操作详情", transient_for=self, modal=True)
        dialog.set_default_size(660, 380)
        dialog.add_button("关闭", Gtk.ResponseType.CLOSE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(250)
        text = label(diagnostic_text(details), "muted")
        text.set_selectable(True)
        text.set_line_wrap(True)
        text.set_max_width_chars(80)
        scroll.add(margins(text, 20))
        dialog.get_content_area().add(scroll)
        dialog.show_all()
        return dialog

    def show_error_details(self):
        if not self.status_details:
            return
        dialog = self.make_error_details_dialog(self.status_details)
        dialog.run()
        dialog.destroy()

    def make_authorization_dialog(self):
        enabled = authorization_enabled()
        dialog = Gtk.Dialog(title="星序授权设置", transient_for=self, modal=True)
        dialog.set_default_size(530, 300)
        dialog.authorization_target = not enabled
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        action = dialog.add_button("撤销授权" if enabled else "授权一次，以后免密", Gtk.ResponseType.OK)
        style(action, "danger" if enabled else "primary")
        body = margins(box(True, 16), 24)
        body.pack_start(label("已启用长期授权" if enabled else "一次授权，后续无需重复输入密码", "detail-title"), False, False, 0)
        message = label("仅对这台电脑的当前账号生效。授权后，在星序中检查更新、更新和卸载应用无需再次输入系统密码；关闭重开星序后仍然生效。", "note")
        message.set_line_wrap(True)
        message.set_max_width_chars(48)
        body.pack_start(message, False, False, 0)
        note = label("更新和卸载前仍会显示确认窗口。你可以随时在这里撤销授权，卸载星序也会清理这项授权。", "muted")
        note.set_line_wrap(True)
        note.set_max_width_chars(48)
        body.pack_start(note, False, False, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        return dialog

    def configure_authorization(self, _=None):
        if self.busy or self.scanning:
            return
        dialog = self.make_authorization_dialog()
        response = dialog.run()
        enabled = dialog.authorization_target
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.busy = True
        self.render()
        self.show_status("请完成这一次系统身份验证，以保存星序授权设置…")
        def done(_):
            self.busy = False
            self.render()
            self.show_status("一次授权已启用，之后在星序内管理应用无需重复输入系统密码。" if enabled else "长期授权已撤销，后续操作将按系统策略验证身份。")
        def failed(message):
            self.busy = False
            self.render()
            self.show_status(message, True)
        self.background(lambda: set_authorization(enabled, getattr(self.manager, "run", run_command)), done, failed)

    def background(self, task, success, failure=None):
        def worker():
            try:
                result = task()
            except Exception as e:
                GLib.idle_add(failure or self.failure, str(e))
            else:
                GLib.idle_add(success, result)
        threading.Thread(target=worker, daemon=True).start()

    def failure(self, message):
        self.show_status(message, True)

    def scan(self):
        if self.scanning or self.busy:
            return
        self.scanning = True
        self.refresh_button.set_sensitive(False)
        self.check_button.set_sensitive(False)
        self.render()
        self.show_status("正在读取本机应用与安装信息…")
        def done(apps):
            self.scanning = False
            self.refresh_button.set_sensitive(True)
            self.apps = apps
            self.update_metrics()
            self.render()
            if self.manager.warnings:
                self.show_status("；".join(self.manager.warnings), True)
            else:
                self.hide_status()
        def failed(message):
            self.scanning = False
            self.refresh_button.set_sensitive(True)
            self.render()
            self.show_status("读取失败：" + message, True)
        self.background(self.manager.scan, done, failed)

    def recent(self, app):
        if not app.installed_at:
            return False
        try:
            return datetime.now() - timedelta(days=30) <= datetime.fromisoformat(app.installed_at) <= datetime.now()
        except ValueError:
            return False

    def update_metrics(self):
        self.metric_labels[0].set_text(str(len(self.apps)))
        sizes = {}
        for app in self.apps:
            sizes[(app.source, app.scope, app.package or app.id)] = app.size
        self.metric_labels[1].set_text(format_size(sum(sizes.values())))
        self.metric_labels[2].set_text(str(sum(self.recent(a) for a in self.apps)))

    def filtered(self):
        query = self.search.get_text().strip().casefold()
        apps = [a for a in self.apps if query in (a.name + " " + a.package).casefold()]
        if self.mode == "updates":
            apps = [a for a in apps if self.update_info(a).available]
        elif self.mode == "recent":
            apps = [a for a in apps if self.recent(a)]
        elif self.mode == "large":
            apps = [a for a in apps if a.size >= 100 * 1024 * 1024]
        elif self.mode in ("APT", "Snap", "Flatpak", "手动安装"):
            apps = [a for a in apps if a.source == self.mode]
        order = self.sort.get_active()
        from .backend import sort_apps
        return sort_apps(apps, order)

    def render(self):
        self.refresh_button.set_sensitive(not self.busy and not self.scanning)
        self.check_button.set_sensitive(not self.busy and not self.scanning)
        self.authorize_button.set_sensitive(not self.busy and not self.scanning)
        self.update_sort_arrows()
        for mode, button in self.nav_buttons.items():
            context = button.get_style_context()
            (context.add_class if mode == self.mode else context.remove_class)("active")
        title = {"all": "全部应用", "updates": "可更新应用", "recent": "最近安装", "large": "大型应用", "history": "操作记录"}.get(self.mode, f"{self.mode} 应用")
        self.heading.set_text(title)
        for row in self.listbox.get_children():
            row.destroy()
        self.table_header.set_visible(self.mode != "history")
        self.sort.set_sensitive(self.mode != "history")
        if self.mode == "history":
            self.render_history()
            return
        apps = self.filtered()
        for app in apps:
            self.listbox.add(self.app_row(app))
        if not apps:
            self.empty("暂无可更新应用" if self.mode == "updates" else "没有找到应用",
                       "点击「检查更新」获取结果；检查失败或未适配的应用请在全部应用中查看。" if self.mode == "updates" else "试试其他关键词，或切换安装来源。")
        self.listbox.show_all()
        available = sum(self.update_info(a).available for a in self.apps)
        self.footer.set_text(f"显示 {len(apps)} / {len(self.apps)} 个应用   ·   {available} 个可更新   ·   刷新列表后需重新检查更新")

    def update_info(self, app):
        return getattr(self.manager, "updates", {}).get(app.id, UpdateInfo(
            "unsupported" if app.source == "手动安装" else "unchecked",
            note="请使用应用自身更新器或官方下载渠道。" if app.source == "手动安装" else "点击检查更新获取软件源中的可用版本。"))

    def app_row(self, app):
        row = Gtk.ListBoxRow()
        row.app_id = app.id
        content = box(spacing=12)
        title = box(spacing=13)
        title.set_size_request(180, -1)
        title.pack_start(app_icon(app), False, False, 0)
        titles = box(True, 5)
        name = label(app.name, "app-name")
        name.set_ellipsize(3)
        name.set_max_width_chars(29)
        name.set_tooltip_text(app.name)
        titles.pack_start(name, False, False, 0)
        meta = box(spacing=7)
        badge = style(label(app.source), "badge")
        if app.source == "Snap":
            style(badge, "snap")
        elif app.source == "手动安装":
            style(badge, "manual")
        meta.pack_start(badge, False, False, 0)
        package = label(app.package or "独立安装", "app-meta")
        package.set_ellipsize(3)
        package.set_max_width_chars(25)
        meta.pack_start(package, True, True, 0)
        titles.pack_start(meta, False, False, 0)
        title.pack_start(titles, True, True, 0)
        content.pack_start(title, True, True, 0)
        info = self.update_info(app)
        versions = box(True, 5)
        versions.set_size_request(150, -1)
        version = label(app.version, "muted")
        version.set_ellipsize(3)
        version.set_max_width_chars(18)
        version.set_tooltip_text(app.version)
        versions.pack_start(version, False, False, 0)
        status = label("→ " + info.version if info.available else update_status(info), "app-meta")
        status.set_ellipsize(3)
        status.set_max_width_chars(18)
        status.set_tooltip_text(f"{update_status(info)} {info.version}\n{info.note}")
        versions.pack_start(status, False, False, 0)
        content.pack_start(versions, False, False, 0)
        for text, width, tip in ((format_size(app.size), 95, "APT 为软件包安装大小；Snap 为当前镜像大小；不包含个人数据与共享运行库。"), (app.installed_at[:10] or "未知", 115, app.date_note)):
            cell = label(text, "muted")
            cell.set_ellipsize(3)
            cell.set_max_width_chars(16)
            cell.set_size_request(width, -1)
            cell.set_tooltip_text(tip)
            content.pack_start(cell, False, False, 0)
        actions = box(spacing=6)
        actions.set_size_request(190, -1)
        detail = Gtk.Button()
        detail.add(icon("dialog-information-symbolic", 16))
        detail.set_tooltip_text("应用详情")
        detail.connect("clicked", lambda _: self.details(app))
        actions.pack_start(detail, False, False, 0)
        if info.available:
            update = style(Gtk.Button(label="更新"), "primary")
            update.set_sensitive(not self.busy and not self.scanning)
            update.set_tooltip_text("查看更新影响并确认")
            update.connect("clicked", lambda _: self.prepare_update(app))
            actions.pack_start(update, False, False, 0)
        remove = style(Gtk.Button(label="卸载"), "danger")
        remove.set_sensitive(app.removable and not self.busy and not self.scanning)
        remove.set_tooltip_text("查看卸载影响并确认" if app.removable else "系统保护组件" if app.protected else "先查看卸载范围")
        remove.connect("clicked", lambda _: self.prepare_uninstall(app))
        actions.pack_end(remove, False, False, 0)
        content.pack_start(actions, False, False, 0)
        row.add(content)
        return row

    def on_row(self, _, row):
        if getattr(row, "app_id", None) in self.manager.apps:
            self.details(self.manager.apps[row.app_id])

    def empty(self, title, subtitle):
        holder = margins(box(True, 12), 60)
        holder.pack_start(icon("edit-find-symbolic", 40), False, False, 0)
        holder.pack_start(label(title, "empty-title", .5), False, False, 0)
        holder.pack_start(label(subtitle, "muted", .5), False, False, 0)
        self.listbox.add(holder)

    def details(self, app):
        dialog = Gtk.Dialog(title="应用详情", transient_for=self, modal=True)
        dialog.set_default_size(500, 430)
        dialog.add_button("关闭", Gtk.ResponseType.CLOSE)
        body = margins(box(True, 18), 24)
        heading = box(spacing=16)
        heading.pack_start(app_icon(app, 56), False, False, 0)
        name = label(app.name, "detail-title")
        name.set_line_wrap(True)
        name.set_max_width_chars(35)
        heading.pack_start(name, True, True, 0)
        body.pack_start(heading, False, False, 0)
        grid = Gtk.Grid(column_spacing=24, row_spacing=14)
        fields = [("软件包", app.package or "独立应用"), ("安装来源", app.source + (f" · {app.scope}" if app.scope else "")), ("版本", app.version), ("占用空间", format_size(app.size)), ("安装时间", app.installed_at or "未知"), ("时间依据", app.date_note), ("桌面入口", app.desktop_path or "无"), ("卸载状态", "系统保护组件" if app.protected else "支持自动卸载" if app.removable else "支持独立应用卸载")]
        info = self.update_info(app)
        fields.extend([("更新状态", update_status(info)), ("可更新版本", info.version or "—"), ("更新说明", info.note or "使用当前已配置的软件源。")])
        for i, (key, value) in enumerate(fields):
            grid.attach(label(key, "muted"), 0, i, 1, 1)
            text = label(value)
            text.set_line_wrap(True)
            text.set_max_width_chars(47)
            text.set_selectable(True)
            grid.attach(text, 1, i, 1, 1)
        body.pack_start(grid, False, False, 0)
        if app.description:
            text = label(app.description, "note")
            text.set_line_wrap(True)
            text.set_max_width_chars(57)
            body.pack_start(text, False, False, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def check_updates(self):
        if self.busy or self.scanning:
            return
        self.busy = True
        self.end_progress(False)
        self.render()
        self.show_status("正在检查更新；首次刷新软件源需系统授权，短时间内可复用，不会升级应用…")
        def done(updates):
            self.busy = False
            self.render()
            count = sum(info.available for info in updates.values())
            failures = [info.note for info in updates.values() if info.state == "failed"]
            message = f"检查完成：{count} 个应用可更新。"
            if failures:
                message += f" 部分软件源暂未完成检查，影响 {len(failures)} 个应用；请稍后重试。"
            details = "\n\n".join(dict.fromkeys(info.details or info.note for info in updates.values() if info.state == "failed"))
            self.show_status(message, bool(failures), details=details)
        def failed(message):
            self.busy = False
            self.render()
            self.show_status("检查更新失败：" + message, True)
        self.background(self.manager.check_updates, done, failed)

    def prepare_update(self, app):
        if self.busy or self.scanning:
            return
        self.busy = True
        self.render()
        self.show_status(f"正在核对 {app.name} 的更新版本与影响…")
        def ready(plan):
            self.busy = False
            self.render()
            self.hide_status()
            self.confirm_update(plan)
        def failed(message):
            self.busy = False
            getattr(self.manager, "updates", {}).pop(app.id, None)
            self.render()
            self.show_status(message + " 请重新检查更新。", True)
        self.background(lambda: self.manager.plan_update(app.id), ready, failed)

    def make_update_dialog(self, plan):
        dialog = Gtk.Dialog(title="确认更新", transient_for=self, modal=True)
        dialog.set_default_size(580, 380)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        style(dialog.add_button("确认更新", Gtk.ResponseType.OK), "primary")
        body = margins(box(True, 16), 24)
        title = label(f"更新 {plan.app.name}？", "detail-title")
        title.set_line_wrap(True)
        title.set_max_width_chars(35)
        body.pack_start(title, False, False, 0)
        before = plan.info.installed if plan.app.source == "APT" else plan.app.version
        versions = label(f"{plan.app.source} · {plan.app.scope or '系统'}\n{before} → {plan.info.version}")
        versions.set_line_wrap(True)
        versions.set_max_width_chars(60)
        body.pack_start(versions, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(90)
        scroll.set_max_content_height(240)
        scroll.set_propagate_natural_height(True)
        changes = label("\n".join(plan.changes), "note")
        changes.set_line_wrap(True)
        changes.set_max_width_chars(65)
        changes.set_selectable(True)
        scroll.add(changes)
        body.pack_start(scroll, True, True, 0)
        note = label(plan.note, "muted")
        note.set_line_wrap(True)
        note.set_max_width_chars(60)
        body.pack_start(note, False, False, 0)
        if plan.app.source == "APT" and bare_package(plan.app.package) == "miemie-app-manager":
            body.pack_start(label("星序更新成功后会退出，请重新打开以加载新版本。", "muted"), False, False, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        return dialog

    def confirm_update(self, plan):
        if self.busy or self.scanning:
            return
        dialog = self.make_update_dialog(plan)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.busy = True
        self.render()
        self.hide_status()
        generation = self.start_progress(plan.app.name)
        def done(_):
            self.end_progress(True)
            self.record(plan.app, "已更新", "更新")
            self.busy = False
            if plan.app.source == "APT" and bare_package(plan.app.package) == "miemie-app-manager":
                self.get_application().quit()
                return
            self.scan()
        def failed(message):
            self.end_progress(False)
            self.record(plan.app, "更新未完成", "更新")
            self.busy = False
            self.scan()
            self.error_dialog("更新未完成", message)
        self.background(lambda: self.manager.update(plan, progress=lambda event: self.queue_progress(generation, event)), done, failed)

    def prepare_uninstall(self, app):
        if self.busy or self.scanning:
            return
        self.busy = True
        self.refresh_button.set_sensitive(False)
        self.render()
        self.show_status(f"正在检查 {app.name} 的卸载影响…")
        def ready(plan):
            self.busy = False
            self.refresh_button.set_sensitive(True)
            self.hide_status()
            self.render()
            self.confirm_uninstall(plan)
        def failed(message):
            self.busy = False
            self.refresh_button.set_sensitive(True)
            self.render()
            self.show_status(message, True)
        self.background(lambda: self.manager.plan(app.id), ready, failed)

    def make_confirm_dialog(self, plan):
        dialog = Gtk.Dialog(title="确认卸载", transient_for=self, modal=True)
        dialog.set_default_size(520, 350)
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        action = dialog.add_button("确认卸载", Gtk.ResponseType.OK)
        style(action, "danger")
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        body = margins(box(True, 16), 24)
        title = box(spacing=14)
        title.pack_start(app_icon(plan.app, 48), False, False, 0)
        name = label(f"卸载 {plan.app.name}？", "detail-title")
        name.set_line_wrap(True)
        name.set_max_width_chars(35)
        title.pack_start(name, True, True, 0)
        body.pack_start(title, False, False, 0)
        body.pack_start(label(f"来源：{plan.app.source}   ·   版本：{plan.app.version}", "muted"), False, False, 0)
        unit = "文件或目录" if plan.manual else "软件包"
        closing = "卸载完成后，星序会自动退出。" if removes_running_manager(plan) else "请先保存内容，卸载时会关闭该应用。" if plan.manual else "请先保存内容并关闭目标应用。"
        message = label(f"本次将移除以下 {len(plan.removed)} 个{unit}。{closing}")
        message.set_line_wrap(True)
        body.pack_start(message, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(75)
        scroll.set_max_content_height(220)
        scroll.set_propagate_natural_height(True)
        entries = plan.removed + (["\n停止用户服务：" + ", ".join(plan.manual.services)] if plan.manual and plan.manual.services else [])
        if plan.installed:
            entries += ["\n同时安装或配置的替代软件：", *plan.installed]
        packages = label("\n".join(entries), "note")
        packages.set_max_width_chars(65)
        packages.set_selectable(True)
        packages.set_line_wrap(True)
        scroll.add(packages)
        body.pack_start(scroll, True, True, 0)
        note = label("仅移除上面列出的内容。安装目录之外的个人配置会保留；请检查目录中是否有需要备份的文件。", "muted")
        note.set_line_wrap(True)
        note.set_max_width_chars(56)
        body.pack_start(note, False, False, 0)
        if plan.risky:
            warning = label("此操作会同时移除：" + ", ".join(plan.risky) + "。可能影响登录界面、桌面或网络连接。", "status")
            style(warning, "error")
            warning.set_line_wrap(True)
            warning.set_max_width_chars(56)
            body.pack_start(warning, False, False, 0)
            dialog.risk_entry = Gtk.Entry(placeholder_text=f"输入 {plan.app.name} 以确认")
            action.set_sensitive(False)
            dialog.risk_entry.connect("changed", lambda entry: action.set_sensitive(entry.get_text() == plan.app.name))
            body.pack_start(dialog.risk_entry, False, False, 0)
        dialog.get_content_area().add(body)
        dialog.show_all()
        return dialog

    def confirm_uninstall(self, plan):
        if self.busy:
            return
        dialog = self.make_confirm_dialog(plan)
        response = dialog.run()
        risk_accepted = bool(plan.risky) and dialog.risk_entry.get_text() == plan.app.name if plan.risky else False
        dialog.destroy()
        if response != Gtk.ResponseType.OK or (plan.risky and not risk_accepted):
            return
        self.busy = True
        self.refresh_button.set_sensitive(False)
        self.render()
        self.show_status(f"正在卸载 {plan.app.name}，请完成系统授权并等待…")
        def done(_):
            self.record(plan.app, "已卸载")
            self.busy = False
            if removes_running_manager(plan):
                self.get_application().quit()
                return
            self.refresh_button.set_sensitive(True)
            self.scan()
            self.show_status(f"{plan.app.name} 已卸载，正在刷新列表。")
        def failed(message):
            self.record(plan.app, "未完成")
            self.busy = False
            self.refresh_button.set_sensitive(True)
            # A command may partially change state before failing; always rescan.
            self.scan()
            self.error_dialog("卸载未完成", message)
        self.background(lambda: self.manager.uninstall(plan, accept_risk=risk_accepted), done, failed)

    def record(self, app, status, operation="卸载"):
        try:
            history = self.read_history()
            history.insert(0, {"name": app.name, "package": app.package, "source": app.source, "status": status, "operation": operation, "time": datetime.now().isoformat(timespec="seconds")})
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(history[:200], ensure_ascii=False, indent=2))
            tmp.replace(self.history_path)
        except OSError:
            self.show_status("操作已结束，但操作记录保存失败。", True)

    def read_history(self):
        try:
            data = json.loads(self.history_path.read_text())
            return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def render_history(self):
        query = self.search.get_text().strip().casefold()
        items = [h for h in self.read_history() if query in (h.get("name", "") + " " + h.get("package", "")).casefold()]
        for item in items:
            row = box(spacing=20)
            operation = item.get("operation", "卸载")
            row.pack_start(icon("software-update-available-symbolic" if operation == "更新" else "edit-delete-symbolic", 22), False, False, 0)
            text = box(True, 5)
            text.pack_start(label(item.get("name", ""), "app-name"), False, False, 0)
            text.pack_start(label(operation + " · " + item.get("package", "") + " · " + item.get("source", ""), "muted"), False, False, 0)
            row.pack_start(text, True, True, 0)
            row.pack_start(label(item.get("time", "").replace("T", " "), "muted"), False, False, 0)
            row.pack_start(label(item.get("status", ""), "badge"), False, False, 0)
            self.listbox.add(row)
        if not items:
            self.empty("还没有操作记录", "通过本软件发起的更新和卸载，会显示在这里。")
        self.listbox.show_all()
        self.footer.set_text("仅记录通过本软件发起的操作；最多保留最近 200 条。")

    def error_dialog(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title)
        readable = friendly_error(message)
        dialog.format_secondary_text(readable)
        if readable != message:
            dialog.add_button("查看详情", 1001)
        while dialog.run() == 1001:
            details = self.make_error_details_dialog(message)
            details.run()
            details.destroy()
        dialog.destroy()

    def about(self, _):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True, program_name="星序 · 应用管理", version=__version__, comments="Ubuntu 原生应用管理工具\n安装信息 · 检查更新 · 更新与卸载计划\nAPT、Snap 和 Flatpak 支持更新；用户目录独立安装支持卸载。", license_type=Gtk.License.MIT_X11)
        dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ROOT / "assets/icon.svg"), 80, 80, True))
        dialog.run()
        dialog.destroy()


class App(Gtk.Application):
    def __init__(self, smoke=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE if smoke else Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_startup(self):
        GLib.set_application_name("星序 · 应用管理")
        Gdk.set_program_class(APP_ID)
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if not self.window:
            self.window = Window(self)
        self.window.present()
