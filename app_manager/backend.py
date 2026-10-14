"""Read installed desktop applications; package operations never use a shell."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import gzip
import os
import re
import shutil
import subprocess
import threading
from .manual import ManualError, ManualPlan, plan_manual, uninstall_manual


class ManagerError(Exception):
    pass


def run(args, timeout=30, accept=(0,), progress=None):
    from .privileges import command_for
    command = command_for(args, progress=progress is not None)
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    try:
        if progress is not None:
            from .progress import stream
            returncode, stdout = stream(command, env, progress, timeout)
            stderr = ""
        else:
            p = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
            returncode, stdout, stderr = p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        raise ManagerError(f"系统未安装 {args[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise ManagerError("操作超时，请检查系统软件管理服务后重试。") from e
    if returncode not in accept:
        detail = (stderr.strip() or stdout.strip())[-6000:]
        if returncode in (126, 127) and args[0] == "/usr/bin/pkexec":
            detail = "系统授权已取消或未能取得权限。"
        raise ManagerError(detail or f"操作失败（退出码 {returncode}）")
    return stdout


@dataclass
class Application:
    id: str
    name: str
    package: str = ""
    source: str = "手动安装"
    version: str = "未知"
    size: int = 0
    installed_at: str = ""
    date_note: str = "系统没有提供可确认的安装时间"
    description: str = ""
    desktop_path: str = ""
    icon: str = "application-x-executable"
    protected: bool = False
    scope: str = ""

    @property
    def removable(self):
        return bool((self.package or self.source == "手动安装") and self.source in ("APT", "Snap", "Flatpak", "手动安装") and not self.protected)


@dataclass
class Plan:
    app: Application
    removed: list[str]
    fingerprint: tuple[str, ...]
    output: str = ""
    manual: ManualPlan | None = None
    installed: list[str] = field(default_factory=list)
    risky: list[str] = field(default_factory=list)


# Removing these can destroy the desktop/session or the package manager itself.
PROTECTED = {
    "apt", "dpkg", "python3", "python3-minimal", "python3-gi", "python3-cairo",
    "gir1.2-gtk-3.0", "libgtk-3-0t64",
    "gnome-shell", "gnome-session", "gnome-session-bin", "gdm3", "network-manager",
    "systemd", "systemd-sysv", "sudo", "polkitd", "pkexec", "snapd",
}
HARD_PROTECTED = PROTECTED - {"gnome-shell", "gnome-session", "gnome-session-bin", "gdm3", "network-manager", "snapd"}


def bare_package(name):
    return name.split(":", 1)[0]


def valid_package(name):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", name))


def parse_packages(output):
    packages = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 6 or fields[1] != "installed":
            continue
        name, _, version, size, essential, priority = fields[:6]
        try:
            size_bytes = int(size) * 1024
        except ValueError:
            size_bytes = 0
        record = {"name": name, "version": version, "size": size_bytes,
                  "protected": essential == "yes" or priority == "required" or bare_package(name) in HARD_PROTECTED,
                  "essential": essential == "yes", "required": priority == "required"}
        packages[name] = record
        packages.setdefault(bare_package(name), record)
    return packages


def parse_owners(output):
    owners = {}
    for line in output.splitlines():
        # A package may have an architecture suffix. Split only at ': /'.
        if ": /" not in line:
            continue
        package, path = line.split(": /", 1)
        if ", " not in package and valid_package(package):
            owners["/" + path] = package
    return owners


def parse_install_log(lines):
    """Use install-from-not-installed records; upgrades are not install dates."""
    dates = {}
    for line in sorted(lines):
        fields = line.split()
        if len(fields) < 5:
            continue
        when, action, package = f"{fields[0]} {fields[1]}", fields[2], bare_package(fields[3])
        if action == "install" and fields[4] == "<none>":
            dates[package] = when
        elif action in ("remove", "purge"):
            dates.pop(package, None)
    return dates


def install_dates(logdir=Path("/var/log")):
    lines = []
    for path in logdir.glob("dpkg.log*"):
        if not path.is_file():
            continue
        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", errors="replace") as f:
                lines.extend(f.readlines())
        except OSError:
            pass
    return parse_install_log(lines)


def format_size(size):
    if size <= 0:
        return "未知"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} B"
        size /= 1024


def sort_apps(apps, order=0):
    """Unknown installation dates and sizes stay last in either direction."""
    if order in (2, 5):
        known = [a for a in apps if a.installed_at]
        unknown = [a for a in apps if not a.installed_at]
        return sorted(known, key=lambda a: a.installed_at, reverse=order == 2) + sorted(unknown, key=lambda a: a.name.casefold())
    if order in (1, 4):
        known = [a for a in apps if a.size > 0]
        unknown = [a for a in apps if a.size <= 0]
        return sorted(known, key=lambda a: a.size, reverse=order == 1) + sorted(unknown, key=lambda a: a.name.casefold())
    if order == 6:
        return sorted(apps, key=lambda a: (a.source, a.name.casefold()))
    if order in (7, 8):
        def version_key(app):
            return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.findall(r'\d+|\D+', app.version))
        known = [a for a in apps if a.version and a.version != '未知']
        unknown = [a for a in apps if not a.version or a.version == '未知']
        return sorted(known, key=version_key, reverse=order == 7) + sorted(unknown, key=lambda a: a.name.casefold())
    return sorted(apps, key=lambda a: a.name.casefold(), reverse=order == 3)


class Manager:
    def __init__(self, runner=run):
        self.run = runner
        self.apps = {}
        self.packages = {}
        self.warnings = []
        self.updates = {}
        self._lock = threading.Lock()

    def scan(self):
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        warnings = []
        packages = parse_packages(self.run([
            "/usr/bin/dpkg-query", "-W", "-f=${binary:Package}\t${db:Status-Status}\t${Version}\t${Installed-Size}\t${Essential}\t${Priority}\n"
        ]))
        owners = parse_owners(self.run(["/usr/bin/dpkg-query", "-S", "/usr/share/applications/*"], accept=(0, 1)))
        dates = install_dates()
        snaps = {}
        if shutil.which("snap"):
            try:
                for line in self.run(["/usr/bin/snap", "list"], timeout=20).splitlines()[1:]:
                    columns = line.split()
                    if len(columns) >= 3:
                        snaps[columns[0]] = (columns[1], columns[2])
            except ManagerError as e:
                warnings.append(f"Snap 列表读取失败：{e}")

        flatpaks = {}
        if shutil.which("flatpak"):
            for scope in ("user", "system"):
                try:
                    output = self.run([shutil.which("flatpak"), "list", f"--{scope}", "--app", "--columns=application,name,version"], timeout=20)
                    for line in output.splitlines():
                        cols = line.split("\t")
                        if cols:
                            flatpaks[(cols[0], scope)] = cols
                except ManagerError as e:
                    warnings.append(f"Flatpak {scope} 列表读取失败：{e}")

        apps = {}
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo) or not info.should_show():
                continue
            path = info.get_filename() or ""
            app = Application(id=info.get_id() or path, name=info.get_display_name(),
                              description=info.get_description() or "", desktop_path=path,
                              icon=info.get_string("Icon") or "application-x-executable")
            snap_name = info.get_string("X-SnapInstanceName") or ""
            flatpak_id = info.get_string("X-Flatpak") or ""
            if snap_name in snaps:
                version, revision = snaps[snap_name]
                app.source, app.package, app.version = "Snap", snap_name, version
                try:
                    app.size = Path(f"/var/lib/snapd/snaps/{snap_name}_{revision}.snap").stat().st_size
                except OSError:
                    pass
            elif flatpak_id:
                scope = "user" if "/.local/share/" in path else "system"
                data = flatpaks.get((flatpak_id, scope))
                if data:
                    app.source, app.package, app.scope = "Flatpak", flatpak_id, scope
                    app.version = data[2] if len(data) > 2 and data[2] else "未知"
            else:
                owner = owners.get(path)
                # User desktop entries often override system entries. Resolve by same ID,
                # then by real executable ownership, never by the display name.
                if not owner and info.get_id():
                    system_path = "/usr/share/applications/" + info.get_id()
                    try:
                        system_info = Gio.DesktopAppInfo.new_from_filename(system_path) if Path(system_path).is_file() else None
                    except (TypeError, GLib.Error):
                        system_info = None
                    if system_info and info.get_executable() == system_info.get_executable():
                        owner = owners.get(system_path)
                if not owner:
                    executable = info.get_executable() or ""
                    if not executable.startswith("/"):
                        executable = shutil.which(executable) or ""
                    if executable.startswith("/") and Path(executable).exists():
                        try:
                            owner_map = parse_owners(self.run(["/usr/bin/dpkg-query", "-S", executable], accept=(0, 1)))
                            owner = owner_map.get(executable)
                        except ManagerError:
                            pass
                record = packages.get(owner or "")
                if record:
                    app.source, app.package = "APT", record["name"]
                    app.version, app.size, app.protected = record["version"], record["size"], record["protected"]
                    date = dates.get(bare_package(app.package), "")
                    if date:
                        app.installed_at, app.date_note = date, "来自 dpkg 安装日志（不是升级时间）"
            if app.source == "手动安装":
                app.date_note = "独立安装没有统一安装日志，未使用文件修改时间冒充安装时间"
            apps[app.id] = app

        # Some exported desktops are hidden/unavailable. Keep installed Flatpak apps searchable.
        for (package, scope), data in flatpaks.items():
            if any(a.source == "Flatpak" and a.package == package and a.scope == scope for a in apps.values()):
                continue
            key = f"flatpak:{scope}:{package}"
            apps[key] = Application(id=key, name=data[1] if len(data) > 1 else package,
                                    package=package, source="Flatpak", scope=scope,
                                    version=data[2] if len(data) > 2 and data[2] else "未知", icon=package)
        self.apps, self.packages, self.warnings = apps, packages, warnings
        self.updates = {}
        return sorted(apps.values(), key=lambda a: a.name.casefold())

    def check_updates(self, refresh=True):
        from .updates import check_updates
        return check_updates(self, refresh)

    def plan_update(self, app_id):
        from .updates import plan_update
        return plan_update(self, app_id)

    def update(self, plan, progress=None):
        from .updates import execute_update
        return execute_update(self, plan, progress)

    def get(self, app_id):
        app = self.apps.get(app_id)
        if not app:
            raise ManagerError("应用列表已变化，请刷新后重试。")
        if not app.removable:
            raise ManagerError("此应用属于系统保护组件或没有受支持的卸载方式。")
        if app.source in ("APT", "Snap") and not valid_package(app.package):
            raise ManagerError("软件包标识无效，已阻止操作。")
        if app.source == "Flatpak" and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", app.package):
            raise ManagerError("Flatpak 应用标识无效。")
        return app

    def plan(self, app_id):
        app = self.get(app_id)
        if app.source == "手动安装":
            try:
                manual = plan_manual(app, self.run)
            except ManualError as e:
                raise ManagerError(str(e)) from e
            removed = [str(p) for p in manual.targets]
            return Plan(app, removed, manual.fingerprint, manual=manual)
        if app.source != "APT":
            return Plan(app, [app.package], (app.source, app.package, app.scope))
        output = self.run(["/usr/bin/apt-get", "-s", "-o", "APT::Get::AutomaticRemove=false", "remove", "--", app.package], timeout=60)
        removed = []
        installed = []
        risky = []
        changes = []
        for line in output.splitlines():
            if line.startswith(("Remv ", "Purg ")):
                name = line.split()[1]
                if not valid_package(name):
                    raise ManagerError("卸载计划含有无法识别的软件包。")
                record = self.packages.get(name, {})
                if bare_package(name) in HARD_PROTECTED or record.get("essential") or record.get("required") or record.get("protected"):
                    raise ManagerError(f"卸载会影响系统保护组件 {name}，已阻止操作。")
                if bare_package(name) in PROTECTED:
                    risky.append(name)
                removed.append(name)
                changes.append(line)
            elif line.startswith(("Inst ", "Conf ")):
                name = line.split()[1]
                if not valid_package(name):
                    raise ManagerError("安装计划含有无法识别的软件包。")
                if name not in installed:
                    installed.append(name)
                changes.append(line)
        if bare_package(app.package) not in {bare_package(p) for p in removed}:
            raise ManagerError("没有找到目标包的卸载计划；它可能已被移除，请刷新列表。")
        return Plan(app, removed, tuple(sorted(changes)), output, installed=installed, risky=risky)

    def uninstall(self, plan, progress=None, accept_risk=False):
        if not self._lock.acquire(blocking=False):
            raise ManagerError("另一个卸载正在进行，请等待完成。")
        try:
            current = self.plan(plan.app.id)
            if current.fingerprint != plan.fingerprint:
                raise ManagerError("卸载影响范围已变化，请重新查看计划并确认。")
            if current.risky and not accept_risk:
                raise ManagerError("此操作会影响桌面、登录或网络组件，需要在确认窗口输入应用名称。")
            app = current.app
            if current.manual:
                try:
                    return uninstall_manual(current.manual, self.run)
                except ManualError as e:
                    raise ManagerError(str(e)) from e
            if app.source == "APT":
                args = ["/usr/bin/pkexec", "/usr/bin/apt-get", "-y", "-o", "APT::Get::AutomaticRemove=false", "remove", "--", app.package]
            elif app.source == "Snap":
                args = ["/usr/bin/pkexec", "/usr/bin/snap", "remove", app.package]
            else:
                args = [shutil.which("flatpak") or "/usr/bin/flatpak", "uninstall", f"--{app.scope}", "--noninteractive", app.package]
                if app.scope == "system":
                    args = ["/usr/bin/pkexec", *args]
            if progress:
                progress("等待系统授权并卸载，请勿关闭窗口…")
            output = self.run(args, timeout=1800)
            # An exit code alone is not proof of removal. Check the package manager.
            if app.source == "APT":
                status = self.run(["/usr/bin/dpkg-query", "-W", "-f=${db:Status-Status}", app.package], accept=(0, 1))
                remaining = status.strip() == "installed"
            elif app.source == "Snap":
                remaining = any(line.split() and line.split()[0] == app.package for line in self.run(["/usr/bin/snap", "list"]).splitlines()[1:])
            else:
                ids = self.run([shutil.which("flatpak") or "/usr/bin/flatpak", "list", f"--{app.scope}", "--app", "--columns=application"])
                remaining = app.package in ids.splitlines()
            if remaining:
                raise ManagerError("命令已结束，但系统仍显示该应用已安装，请刷新并检查。")
            return output
        finally:
            self._lock.release()
