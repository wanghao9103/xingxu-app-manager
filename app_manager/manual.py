"""Reviewed removal of user-installed executables, bundles and launchers."""
from dataclasses import dataclass
from pathlib import Path
import configparser
import os
import re
import shlex
import shutil
import signal
import subprocess
import time


class ManualError(Exception):
    pass


@dataclass
class ManualPlan:
    targets: tuple[Path, ...]
    roots: tuple[Path, ...]
    services: tuple[str, ...]
    fingerprint: tuple[str, ...]


def desktop_exec(path):
    try:
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read(path, encoding="utf-8")
        parts = shlex.split(config["Desktop Entry"].get("Exec", ""))
        if parts and Path(parts[0]).name == "env":
            parts = [p for p in parts[1:] if "=" not in p and not p.startswith("-")]
        return Path(parts[0]).expanduser() if parts and parts[0].startswith("/") else None
    except (OSError, ValueError, configparser.Error, KeyError):
        return None


def is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def wrapper_target(path):
    """Read simple wrappers; never execute a script to discover its target."""
    try:
        if path.stat().st_size > 65536:
            return None
        for line in path.read_text(errors="replace").splitlines():
            if line.strip().startswith("exec "):
                parts = shlex.split(line.strip()[5:])
                if parts and parts[0].startswith("/"):
                    return Path(parts[0])
    except (OSError, ValueError):
        pass
    return None


def path_stamp(path):
    try:
        stat = path.lstat()
        return f"{path}|{stat.st_dev}|{stat.st_ino}|{stat.st_mode}|{stat.st_size}|{stat.st_mtime_ns}|{path.parent.resolve()}"
    except OSError as e:
        raise ManualError(f"安装文件已变化或无法访问：{path}") from e


def plan_manual(app, runner, home=None, data=None, config=None):
    home = Path(home or Path.home()).resolve()
    data = Path(data or os.environ.get("XDG_DATA_HOME", home / ".local/share")).absolute()
    config = Path(config or os.environ.get("XDG_CONFIG_HOME", home / ".config")).absolute()
    launcher = Path(app.desktop_path).absolute()
    executable = desktop_exec(launcher)
    if not executable or not executable.is_file():
        raise ManualError("无法确认程序文件位置。请检查桌面入口的 Exec，或使用原安装程序卸载。")
    # Only operate in dedicated installation locations owned by this user.
    allowed = [home / ".local/bin", home / ".local/opt", home / "Applications", data]
    executable = executable.absolute()
    if not any(is_within(executable, root) and executable != root for root in allowed):
        raise ManualError("这个独立安装的程序不在当前用户的应用目录内，需要原安装程序提供卸载方式。")
    if executable.lstat().st_uid != os.getuid():
        raise ManualError("程序文件不属于当前用户，不能按用户级应用删除。")
    # Follow at most four simple wrapper targets, collecting the wrappers too.
    chain = [executable]
    for _ in range(4):
        candidate = wrapper_target(chain[-1])
        if not candidate or candidate in chain or not candidate.exists():
            break
        if not any(is_within(candidate.absolute(), root) and candidate != root for root in allowed):
            break
        chain.append(candidate.absolute())
    program = chain[-1]
    roots = []
    # Dedicated opt/Applications bundles are removed as a unit. In share/,
    # remove the executable only so application profiles are retained.
    for base in (home / ".local/opt", home / "Applications"):
        if is_within(program, base):
            root = base / program.relative_to(base).parts[0]
            if root.is_dir():
                roots.append(root)
    if program.parent.parent == data and not program.parent.is_symlink():
        if set(program.parent.iterdir()) == {program}:
            roots.append(program.parent)
    self_root = data / "miemie-app-manager"
    if is_within(program, self_root) and (self_root / "app_manager/__main__.py").is_file():
        roots.append(self_root)
    targets = set(roots)
    for file in chain:
        if not any(is_within(file, root) for root in roots):
            targets.add(file)
    matches = {str(p) for p in chain}
    launchers = []
    for directory in (data / "applications", config / "autostart"):
        for path in directory.glob("*.desktop"):
            cmd = desktop_exec(path)
            if cmd and (str(cmd) in matches or any(is_within(cmd, root) for root in roots)):
                targets.add(path)
                launchers.append(path)
    if launcher.is_file() and is_within(launcher, data / "applications"):
        targets.add(launcher)
    # Icons are removed only if no remaining user launcher shares that name.
    icon = app.icon
    shared_icon = False
    for path in (data / "applications").glob("*.desktop"):
        if path in targets:
            continue
        try:
            entries = configparser.ConfigParser(interpolation=None, strict=False)
            entries.read(path)
            if entries.get("Desktop Entry", "Icon", fallback="") == icon:
                shared_icon = True
        except configparser.Error:
            continue
    if icon and not shared_icon:
        if not icon.startswith("/") and re.fullmatch(r"[A-Za-z0-9_.-]+", icon):
            for suffix in ("png", "svg", "xpm"):
                targets.update((data / "icons").glob(f"**/apps/{icon}.{suffix}"))
        elif icon.startswith("/"):
            path = Path(icon)
            if is_within(path, data / "icons") and path.is_file():
                targets.add(path)

    services = []
    try:
        output = runner(["/usr/bin/systemctl", "--user", "show", "--all", "--property=Id,ExecStart,FragmentPath", "*.service"], timeout=15, accept=(0, 1))
        for chunk in output.split("\n\n"):
            props = dict(line.split("=", 1) for line in chunk.splitlines() if "=" in line)
            command = props.get("ExecStart", "")
            if any(re.search(re.escape(str(path)) + r"(?=[ /;\"}]|$)", command) for path in chain + roots):
                name = props.get("Id", "")
                if name and re.fullmatch(r"[A-Za-z0-9_@.\\:-]+\.service", name):
                    services.append(name)
                    unit = config / "systemd/user" / name
                    if unit.is_file() or unit.is_symlink():
                        targets.add(unit)
                    for link in (config / "systemd/user").glob(f"*.wants/{name}"):
                        targets.add(link)
    except Exception:
        # Process checks still prevent removal of running executables.
        pass
    targets = sorted(targets, key=str)
    for path in targets:
        if path == home or path in allowed or not is_within(path.absolute(), home):
            raise ManualError(f"卸载范围不属于独立应用目录：{path}")
        if not is_within(path.parent.resolve(), home):
            raise ManualError(f"安装路径通过符号链接指向用户目录外：{path}")
        if path.lstat().st_uid != os.getuid():
            raise ManualError(f"安装文件不属于当前用户：{path}")
        if path.is_symlink():
            # Delete a launcher link itself, never the file it points to.
            continue
        if path in roots and path.resolve() != path:
            raise ManualError("应用目录是符号链接，无法确认完整卸载范围。")
    stamps = tuple(path_stamp(p) for p in targets) + tuple(sorted(services))
    return ManualPlan(tuple(targets), tuple(set(chain + roots)), tuple(sorted(services)), stamps)


def matching_processes(roots, proc=Path("/proc")):
    result = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            executable = (entry / "exe").resolve(strict=True)
            if any(executable == root or (root.is_dir() and is_within(executable, root)) for root in roots):
                result.append(int(entry.name))
        except (OSError, RuntimeError):
            pass
    return result


def uninstall_manual(plan, runner):
    if tuple(path_stamp(p) for p in plan.targets) + tuple(sorted(plan.services)) != plan.fingerprint:
        raise ManualError("安装文件已变化，请重新查看卸载计划。")
    for service in plan.services:
        runner(["/usr/bin/systemctl", "--user", "stop", service], timeout=30)
        # Generated autostart units are disabled by removing their desktop entry.
        if not service.startswith("app-"):
            runner(["/usr/bin/systemctl", "--user", "disable", service], timeout=30, accept=(0, 1))
    processes = matching_processes(plan.roots)
    for pid in processes:
        # Re-read ownership and executable immediately before signaling.
        if pid in matching_processes(plan.roots):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 5
    while matching_processes(plan.roots) and time.monotonic() < deadline:
        time.sleep(.1)
    if matching_processes(plan.roots):
        raise ManualError("应用仍在运行。请保存内容并手动退出后，再尝试卸载。")
    for path in plan.targets:
        # Revalidate parents to avoid traversing replacement symlinks.
        if not path.exists() and not path.is_symlink():
            continue  # systemctl disable may already have removed its wants link.
        if path_stamp(path) not in plan.fingerprint:
            raise ManualError("安装文件或路径已变化，已停止删除。")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    runner(["/usr/bin/systemctl", "--user", "daemon-reload"], timeout=15, accept=(0, 1))
    if shutil.which("update-desktop-database"):
        runner([shutil.which("update-desktop-database"), str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications")], accept=(0, 1))
    icons = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "icons/hicolor"
    if shutil.which("gtk-update-icon-cache") and icons.is_dir():
        runner([shutil.which("gtk-update-icon-cache"), "-f", "-t", str(icons)], accept=(0, 1))
    if any(p.exists() or p.is_symlink() for p in plan.targets):
        raise ManualError("部分应用文件仍然存在，请检查文件权限后重试。")
    return "独立应用、相关启动入口及匹配的用户服务已移除。"
