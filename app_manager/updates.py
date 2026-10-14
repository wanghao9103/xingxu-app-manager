"""Source-aware update checks and reviewed, single-application upgrades."""
from dataclasses import dataclass
from fnmatch import fnmatchcase
import re
import shutil
import time

from .backend import ManagerError, valid_package, bare_package
from .errors import connection_error, diagnostic_text, friendly_error


@dataclass(frozen=True)
class UpdateInfo:
    state: str = "unchecked"
    version: str = ""
    target: str = ""  # Debian version, Snap revision, or full OSTree commit.
    installed: str = ""
    ref: str = ""
    origin: str = ""
    note: str = ""
    details: str = ""

    @property
    def available(self):
        return self.state == "available"


@dataclass(frozen=True)
class UpdatePlan:
    app: object
    info: UpdateInfo
    changes: tuple[str, ...]
    fingerprint: tuple[str, ...]
    command: tuple[str, ...]
    note: str = ""


def update_status(info):
    return {"unchecked": "未检查", "available": "可更新", "current": "软件源暂无更新",
            "held": "已锁定更新", "unsupported": "需自行更新", "failed": "检查失败"}.get(info.state, "未检查")


def get_app(manager, app_id):
    app = manager.apps.get(app_id)
    if not app:
        raise ManagerError("应用列表已变化，请刷新后重试。")
    if app.source not in ("APT", "Snap", "Flatpak") or not app.package:
        raise ManagerError("独立安装应用需要使用自身更新器或官方下载渠道。")
    if app.source in ("APT", "Snap") and not valid_package(app.package):
        raise ManagerError("软件包标识无效，已阻止更新。")
    if app.source == "Flatpak" and (app.scope not in ("user", "system") or
            not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", app.package)):
        raise ManagerError("Flatpak 应用标识或安装范围无效。")
    return app


def apt_updates(manager, apps, refresh):
    import apt_pkg
    apt_pkg.init()
    if refresh:
        # Error-Mode prevents partially failed repositories from appearing up to date.
        command = ["/usr/bin/pkexec", "/usr/bin/apt-get", "-o",
                   "APT::Update::Error-Mode=any", "-o", "Acquire::Retries=2", "update"]
        try:
            manager.run(command, timeout=600)
        except ManagerError as exc:
            if not connection_error(str(exc)):
                raise
            # Some TLS/transport errors are fatal to an individual APT attempt.
            # Retry the verified refresh once; never relax TLS or source checks.
            time.sleep(1)
            manager.run(command, timeout=600)
    held = {bare_package(p) for p in manager.run(["/usr/bin/apt-mark", "showhold"]).splitlines()}
    output = manager.run(["/usr/bin/apt-cache", "policy", "--", *sorted({a.package for a in apps})], timeout=60)
    policies = {}
    key = None
    for line in output.splitlines():
        if line and not line[0].isspace() and line.endswith(":"):
            key = line[:-1]
            policies[key] = {}
        elif key and line.strip().startswith(("Installed:", "Candidate:")):
            field, value = line.strip().split(":", 1)
            policies[key][field] = value.strip()
    result = {}
    for app in apps:
        policy = policies.get(app.package)
        if policy is None and app.package.endswith(":" + apt_pkg.config.find("APT::Architecture")):
            # apt-cache omits the native architecture suffix in its headings.
            policy = policies.get(bare_package(app.package))
        if policy is None and ":" not in app.package:
            matches = [v for k, v in policies.items() if bare_package(k) == app.package]
            policy = matches[0] if len(matches) == 1 else None
        installed, candidate = (policy or {}).get("Installed", ""), (policy or {}).get("Candidate", "")
        if not installed or installed == "(none)" or not candidate:
            result[app.id] = UpdateInfo("failed", note="无法确认已安装版本或软件源候选版本，请刷新列表。")
            continue
        newer = candidate != "(none)" and apt_pkg.version_compare(candidate, installed) > 0
        state = "held" if newer and bare_package(app.package) in held else "available" if newer else "current"
        note = "软件包被 apt-mark hold 锁定，本工具不会绕过。" if state == "held" else "仅检查已配置的软件源；本地 deb 未配置更新源时无法发现官网新版本。"
        result[app.id] = UpdateInfo(state, candidate if newer else "", candidate if newer else "", installed, note=note)
    return result


def snap_rows(output):
    rows = {}
    for line in output.splitlines():
        cols = line.split()
        if len(cols) >= 3 and valid_package(cols[0]) and re.fullmatch(r"(?:x)?\d+", cols[2]):
            rows[cols[0]] = cols
    return rows


def snap_updates(manager, apps):
    installed = snap_rows(manager.run(["/usr/bin/snap", "list"], timeout=60))
    pending = snap_rows(manager.run(["/usr/bin/snap", "refresh", "--list"], timeout=120))
    result = {}
    for app in apps:
        row = installed.get(app.package)
        if not row:
            result[app.id] = UpdateInfo("failed", note="Snap 已安装列表中未找到目标，请刷新。")
            continue
        candidate = pending.get(app.package)
        # Do not explicitly refresh held/local snaps, which could override user intent.
        blocked = "held" in row[-1].split(",") or row[2].startswith("x")
        state = "held" if blocked else "available" if candidate and candidate[2] != row[2] else "current"
        result[app.id] = UpdateInfo(state, candidate[1] if candidate else "", candidate[2] if candidate else "",
                                    row[2], origin=row[3] if len(row) >= 4 else "",
                                    note="沿用当前跟踪频道；Snap 自动更新可能使检查结果变化。" if not blocked else "Snap 已暂停更新或是本地安装，本工具不会绕过。")
    return result


def flatpak_updates(manager, apps, scope):
    binary = shutil.which("flatpak") or "/usr/bin/flatpak"
    installed = manager.run([binary, "list", f"--{scope}", "--app",
                            "--columns=ref:f,version,active:f,origin"], timeout=60)
    pending = manager.run([binary, "remote-ls", f"--{scope}", "--updates", "--app",
                          "--columns=ref:f,version,origin,runtime:f,commit:f"], timeout=120)
    current_rows = [line.split("\t") for line in installed.splitlines() if line]
    remote_rows = [line.split("\t") for line in pending.splitlines() if line]
    masks = manager.run([binary, "mask", f"--{scope}"], timeout=60).splitlines()
    result = {}
    for app in apps:
        try:
            rows = [r for r in current_rows if len(r) == 4 and r[0].split("/")[0:2] == ["app", app.package]]
            if len(rows) != 1:
                raise ManagerError("未找到唯一安装分支，请使用 Flatpak 自身工具确认分支。")
            ref, version, commit, origin = rows[0]
            if not re.fullmatch(r"app/[A-Za-z0-9_.-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", ref) or not re.fullmatch(r"[0-9a-f]{64}", commit):
                raise ManagerError("Flatpak 安装引用或提交标识无法可靠解析。")
            if any(fnmatchcase(ref, pattern) or fnmatchcase(ref, pattern.rstrip("/") + "/*") or
                   fnmatchcase(ref[4:], pattern) or fnmatchcase(ref[4:], pattern.rstrip("/") + "/*")
                   for pattern in masks if pattern and not pattern.startswith("#")):
                result[app.id] = UpdateInfo("held", installed=commit, ref=ref, origin=origin, note="Flatpak 分支已被 mask 锁定，本工具不会绕过。")
                continue
            matches = [r for r in remote_rows if len(r) == 5 and r[0] == ref and r[2] == origin]
            if len(matches) > 1:
                raise ManagerError("Flatpak 更新源有歧义。")
            # Query the exact origin even when remote-ls offered nothing. A remote
            # failure must not become a false "current" result.
            target = manager.run([binary, "remote-info", f"--{scope}", "--show-commit", "--", origin, ref], timeout=120).strip()
            if not re.fullmatch(r"[0-9a-f]{64}", target):
                raise ManagerError("Flatpak 更新提交标识无法可靠解析。")
            result[app.id] = UpdateInfo("available" if target != commit else "current",
                                        (matches[0][1] if matches and matches[0][4] == target else "") or f"新构建 {target[:12]}", target, commit, ref, origin,
                                        "同时由 Flatpak 处理所需运行库和语言扩展。运行库：" + ((matches[0][3] if matches else "") or "由软件源解析"))
        except ManagerError as exc:
            result[app.id] = UpdateInfo("failed", note=friendly_error(str(exc)), details=diagnostic_text(str(exc)))
    return result


def collect(manager, apps, refresh=False):
    result = {}
    groups = {}
    for app in apps:
        try:
            get_app(manager, app.id)
        except ManagerError as exc:
            result[app.id] = UpdateInfo("unsupported" if app.source == "手动安装" else "failed", note=str(exc))
            continue
        groups.setdefault((app.source, app.scope if app.source == "Flatpak" else ""), []).append(app)
    for (source, scope), group in groups.items():
        try:
            if source == "APT":
                result.update(apt_updates(manager, group, refresh))
            elif source == "Snap":
                result.update(snap_updates(manager, group))
            else:
                result.update(flatpak_updates(manager, group, scope))
        except (ManagerError, ImportError, ValueError, SystemError, OSError) as exc:
            result.update({a.id: UpdateInfo("failed", note=f"{source}：{friendly_error(str(exc))}",
                                          details=diagnostic_text(str(exc))) for a in group})
    return result


def check_updates(manager, refresh=True):
    if not manager._lock.acquire(blocking=False):
        raise ManagerError("另一个软件管理操作正在进行。")
    try:
        # Commit all statuses together, so a source failure cannot preserve stale offers.
        manager.updates = collect(manager, list(manager.apps.values()), refresh)
        return manager.updates
    finally:
        manager._lock.release()


def describe_apt_changes(lines):
    installed = {line.split()[1] for line in lines if line.startswith("Inst ")}
    changes = []
    for line in lines:
        parts = line.split()
        if parts[0] == "Conf" and parts[1] in installed:
            continue
        target = re.search(r"\((\S+)", line)
        before = re.search(r"\[([^\]]+)\]", line.split("(", 1)[0])
        version = target.group(1) if target else "由 APT 配置"
        if parts[0] == "Conf":
            changes.append(f"配置 {parts[1]} · {version}")
        else:
            changes.append(f"{parts[1]}：{before.group(1)} → {version}" if before else f"新增依赖 {parts[1]} · {version}")
    return tuple(changes)


def plan_update(manager, app_id):
    app = get_app(manager, app_id)
    info = collect(manager, [app])[app_id]
    if not info.available:
        raise ManagerError(f"{update_status(info)}。{info.note}")
    identity = (app.source, app.package, app.scope, info.installed, info.target, info.ref, info.origin)
    if app.source == "APT":
        args = ["/usr/bin/apt-get", "--no-remove", "--only-upgrade", "-o", "APT::Get::AutomaticRemove=false",
                "install", "--", f"{app.package}={info.target}"]
        output = manager.run([args[0], "-s", *args[1:]], timeout=90)
        changes = []
        targets = []
        for line in output.splitlines():
            if line.startswith(("Remv ", "Purg ")):
                raise ManagerError("更新会删除软件包，已阻止操作。")
            if line.startswith(("Inst ", "Conf ")):
                name = line.split()[1]
                if not valid_package(name):
                    raise ManagerError("更新计划的软件包标识无效。")
                changes.append(line)
                if line.startswith("Inst ") and bare_package(name) == bare_package(app.package):
                    match = re.search(r"\((\S+)", line)
                    if match:
                        targets.append(match.group(1))
        if targets != [info.target]:
            raise ManagerError("模拟计划没有升级到目标版本，请重新检查更新。")
        return UpdatePlan(app, info, describe_apt_changes(changes), identity + tuple(sorted(changes)),
                          tuple(["/usr/bin/pkexec", args[0], "-y", *args[1:]]),
                          "仅升级选中的应用及必要依赖；不删除软件包、不执行全系统升级。请保存内容并关闭目标应用。")
    if app.source == "Snap":
        return UpdatePlan(app, info, (f"{app.package}：修订 {info.installed} → {info.target}",), identity,
                          ("/usr/bin/pkexec", "/usr/bin/snap", "refresh", app.package, f"--revision={info.target}"),
                          "更新选中的 Snap；snapd 可能同时处理其基础运行环境。请保存内容并关闭目标应用。")
    binary = shutil.which("flatpak") or "/usr/bin/flatpak"
    args = [binary, "update", f"--{app.scope}", "--app", "--noninteractive", f"--commit={info.target}", info.ref]
    if app.scope == "system":
        args.insert(0, "/usr/bin/pkexec")
    return UpdatePlan(app, info, (info.ref, f"构建 {info.installed[:12]} → {info.target[:12]}"), identity + (info.note,),
                      tuple(args), info.note + " 不切换应用分支。运行库和扩展的完整变更由 Flatpak 执行时解析。请保存内容并关闭目标应用。")


def execute_update(manager, plan, progress=None):
    from .progress import Progress
    if not manager._lock.acquire(blocking=False):
        raise ManagerError("另一个软件管理操作正在进行。")
    try:
        if progress:
            progress(Progress("正在复核更新版本与影响范围"))
        current = plan_update(manager, plan.app.id)
        if current.fingerprint != plan.fingerprint or current.command != plan.command:
            raise ManagerError("更新版本或影响范围已变化，请重新检查并确认。")
        if progress:
            progress(Progress("正在准备更新" if current.app.scope == "user" else "等待系统授权；已授权时将直接继续"))
        kwargs = {"progress": progress} if progress else {}
        output = manager.run(list(current.command), timeout=1800, **kwargs)
        if progress:
            progress(Progress("正在验证更新结果"))
        app, info = current.app, current.info
        if app.source == "APT":
            status = manager.run(["/usr/bin/dpkg-query", "-W", "-f=${db:Status-Status}\t${Version}", app.package]).strip()
            verified = status == f"installed\t{info.target}"
        elif app.source == "Snap":
            rows = snap_rows(manager.run(["/usr/bin/snap", "list", app.package], timeout=60))
            verified = app.package in rows and rows[app.package][2] == info.target
        else:
            binary = shutil.which("flatpak") or "/usr/bin/flatpak"
            commit = manager.run([binary, "info", f"--{app.scope}", "--show-commit", info.ref]).strip()
            verified = commit == info.target
        if not verified:
            raise ManagerError("命令已结束，但未确认目标版本已安装，请刷新并检查。")
        if progress:
            progress(Progress("更新完成，目标版本已确认", 1.0))
        manager.updates = {}  # Shared dependencies and duplicate desktops may have changed.
        return output
    finally:
        manager._lock.release()
