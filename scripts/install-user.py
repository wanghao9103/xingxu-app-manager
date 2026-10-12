#!/usr/bin/python3
"""Install into the user's XDG directories, without changing system packages."""
from pathlib import Path
import os
import shutil
import subprocess

project = Path(__file__).resolve().parent.parent
data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
target = data / "miemie-app-manager"
target.mkdir(parents=True, exist_ok=True)
for name in ("app_manager", "assets"):
    shutil.copytree(project / name, target / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
launcher = target / "start.sh"
launcher.write_text('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec /usr/bin/python3 -m app_manager "$@"\n')
launcher.chmod(0o755)
desktop_dir = data / "applications"
desktop_dir.mkdir(parents=True, exist_ok=True)
icon_dir = data / "icons/hicolor/256x256/apps"
icon_dir.mkdir(parents=True, exist_ok=True)
shutil.copyfile(project / "assets/icon.png", icon_dir / "io.miemie.AppManager.png")
# Desktop Exec escaping follows the Desktop Entry spec, not shell quoting.
escaped = str(launcher).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
desktop = desktop_dir / "io.miemie.AppManager.desktop"
desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=星序应用管理
Comment=查看、搜索和卸载 Ubuntu 应用
Exec="{escaped}"
Icon=io.miemie.AppManager
Terminal=false
Categories=Settings;PackageManager;
Keywords=星序;应用;管理;卸载;Xingxu;uninstall;
StartupNotify=true
StartupWMClass=io.miemie.AppManager
''')
desktop.chmod(0o755)
for command in (("update-desktop-database", str(desktop_dir)), ("gtk-update-icon-cache", "-f", "-t", str(data / "icons/hicolor"))):
    if shutil.which(command[0]):
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
print(f"已安装到：{target}\n应用菜单入口：{desktop}")
