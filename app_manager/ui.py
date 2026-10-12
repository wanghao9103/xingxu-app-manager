from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from datetime import datetime, timedelta
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib, Gdk, GdkPixbuf
from .backend import Manager, ManagerError, format_size

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
    if app.icon.startswith("/") and Path(app.icon).is_file():
        try:
            return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(app.icon, size, size, True))
        except GLib.Error:
            pass
    theme = Gtk.IconTheme.get_default()
    name = app.icon
    if not theme.has_icon(name):
        name = "application-x-executable"
    return icon(name, size)


class Window(Gtk.ApplicationWindow):
    def __init__(self, application, manager=None):
        super().__init__(application=application, title="星序 · 应用管理")
        self.set_default_size(1220, 790)
        self.set_size_request(1040, 620)
        self.set_icon_from_file(str(ROOT / "assets/icon.svg"))
        self.manager = manager or Manager()
        self.apps = []
        self.mode = "all"
        self.busy = False
        self.scanning = False
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
        self.add_nav(sidebar, "history", "卸载记录", "document-text-symbolic")
        about = Gtk.Button(label="关于 · 版本 1.1.2")
        style(about, "nav")
        about.connect("clicked", self.about)
        sidebar.pack_start(margins(about, 15), False, False, 0)

        main = margins(box(True, 22), 30)
        layout.pack_start(main, True, True, 0)
        heading = box(spacing=12)
        titles = box(True, 6)
        self.heading = label("全部应用", "title")
        self.subtitle = label("查看安装信息，快速搜索，一处管理所有应用。", "muted")
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
        self.status.set_no_show_all(True)
        main.pack_start(self.status, False, False, 0)

        table = style(box(True), "table")
        self.table_header = style(box(spacing=12), "table-header")
        self.table_buttons = {}
        self.table_arrows = {}
        self.sort_columns = {"应用名称": (0, 3, 0), "版本": (8, 7, 7), "占用空间": (4, 1, 1), "安装时间": (5, 2, 2)}
        for title, width, expand in (("应用名称", 180, True), ("版本", 125, False), ("占用空间", 95, False), ("安装时间", 115, False), ("操作", 113, False)):
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
            self.show_status("正在卸载，请等待系统操作完成后再关闭窗口。", True)
            return True
        return False

    def show_status(self, text, error=False):
        self.status.set_text(text)
        context = self.status.get_style_context()
        (context.add_class if error else context.remove_class)("error")
        self.status.show()

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
                self.status.hide()
        def failed(message):
            self.scanning = False
            self.refresh_button.set_sensitive(True)
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
        if self.mode == "recent":
            apps = [a for a in apps if self.recent(a)]
        elif self.mode == "large":
            apps = [a for a in apps if a.size >= 100 * 1024 * 1024]
        elif self.mode in ("APT", "Snap", "Flatpak", "手动安装"):
            apps = [a for a in apps if a.source == self.mode]
        order = self.sort.get_active()
        from .backend import sort_apps
        return sort_apps(apps, order)

    def render(self):
        self.update_sort_arrows()
        for mode, button in self.nav_buttons.items():
            context = button.get_style_context()
            (context.add_class if mode == self.mode else context.remove_class)("active")
        title = {"all": "全部应用", "recent": "最近安装", "large": "大型应用", "history": "卸载记录"}.get(self.mode, f"{self.mode} 应用")
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
            self.empty("没有找到应用", "试试其他关键词，或切换安装来源。")
        self.listbox.show_all()
        self.footer.set_text(f"显示 {len(apps)} / {len(self.apps)} 个应用   ·   安装时间来自系统日志，缺失时显示未知")

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
        for text, width, tip in ((app.version, 125, app.version), (format_size(app.size), 95, "APT 为软件包安装大小；Snap 为当前镜像大小；不包含个人数据与共享运行库。"), (app.installed_at[:10] or "未知", 115, app.date_note)):
            cell = label(text, "muted")
            cell.set_ellipsize(3)
            cell.set_max_width_chars(16)
            cell.set_size_request(width, -1)
            cell.set_tooltip_text(tip)
            content.pack_start(cell, False, False, 0)
        actions = box(spacing=6)
        actions.set_size_request(113, -1)
        detail = Gtk.Button()
        detail.add(icon("dialog-information-symbolic", 16))
        detail.set_tooltip_text("应用详情")
        detail.connect("clicked", lambda _: self.details(app))
        actions.pack_start(detail, False, False, 0)
        remove = style(Gtk.Button(label="卸载"), "danger")
        remove.set_sensitive(app.removable and not self.busy and not self.scanning)
        remove.set_tooltip_text("查看卸载影响并确认" if app.removable else "系统保护组件" if app.protected else "先查看卸载范围")
        remove.connect("clicked", lambda _: self.prepare_uninstall(app))
        actions.pack_start(remove, False, False, 0)
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
            self.status.hide()
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
        closing = "请先保存内容，卸载时会关闭该应用。" if plan.manual else "请先保存内容并关闭目标应用。"
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
            if plan.manual and ROOT in plan.manual.targets:
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

    def record(self, app, status):
        try:
            history = self.read_history()
            history.insert(0, {"name": app.name, "package": app.package, "source": app.source, "status": status, "time": datetime.now().isoformat(timespec="seconds")})
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(history[:200], ensure_ascii=False, indent=2))
            tmp.replace(self.history_path)
        except OSError:
            self.show_status("操作已结束，但卸载记录保存失败。", True)

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
            row.pack_start(icon("edit-delete-symbolic", 22), False, False, 0)
            text = box(True, 5)
            text.pack_start(label(item.get("name", ""), "app-name"), False, False, 0)
            text.pack_start(label(item.get("package", "") + " · " + item.get("source", ""), "muted"), False, False, 0)
            row.pack_start(text, True, True, 0)
            row.pack_start(label(item.get("time", "").replace("T", " "), "muted"), False, False, 0)
            row.pack_start(label(item.get("status", ""), "badge"), False, False, 0)
            self.listbox.add(row)
        if not items:
            self.empty("还没有卸载记录", "通过本软件完成的卸载，会显示在这里。")
        self.listbox.show_all()
        self.footer.set_text("仅记录通过本软件发起的操作；最多保留最近 200 条。")

    def error_dialog(self, title, message):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(message[-1800:])
        dialog.run()
        dialog.destroy()

    def about(self, _):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True, program_name="星序 · 应用管理", version="1.1.2", comments="Ubuntu 原生应用管理工具\n应用图标 · 名称搜索 · 安装信息 · 卸载计划\n支持 APT、Snap 和 Flatpak；支持用户目录独立安装。", license_type=Gtk.License.MIT_X11)
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
