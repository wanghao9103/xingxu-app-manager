#!/usr/bin/python3
from pathlib import Path
import os
import shutil
import subprocess
import sys

# Packages must not inherit a developer's group-writable umask/source modes.
os.umask(0o022)

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
from app_manager import __version__
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
stage = project / "deliverables/staging"
if stage.exists():
    shutil.rmtree(stage)
app_dir = stage / "usr/share/miemie-app-manager"
app_dir.mkdir(parents=True)
for name in ("app_manager", "assets"):
    shutil.copytree(project / name, app_dir / name, ignore=shutil.ignore_patterns("__pycache__"))
binary_dir = stage / "usr/bin"
binary_dir.mkdir(parents=True)
launcher = binary_dir / "miemie-app-manager"
launcher.write_text('#!/bin/sh\ncd /usr/share/miemie-app-manager || exit 1\nexec /usr/bin/python3 -m app_manager "$@"\n')
launcher.chmod(0o755)
helper_dir = stage / "usr/libexec"
helper_dir.mkdir(parents=True)
helper = helper_dir / "miemie-app-manager-helper"
shutil.copyfile(project / "app_manager/privileged_helper.py", helper)
helper.chmod(0o755)
authorizer = helper_dir / "miemie-app-manager-authorize"
shutil.copyfile(project / "app_manager/authorization_helper.py", authorizer)
authorizer.chmod(0o755)
policy_dir = stage / "usr/share/polkit-1/actions"
policy_dir.mkdir(parents=True)
shutil.copyfile(project / "assets/polkit/io.miemie.AppManager.policy", policy_dir / "io.miemie.AppManager.policy")
desktop_dir = stage / "usr/share/applications"
desktop_dir.mkdir(parents=True)
shutil.copyfile(project / "assets/io.miemie.AppManager.desktop", desktop_dir / "io.miemie.AppManager.desktop")
for pixels in (16, 24, 32, 48, 64, 128, 256):
    icon_dir = stage / f"usr/share/icons/hicolor/{pixels}x{pixels}/apps"
    icon_dir.mkdir(parents=True)
    if pixels == 256:
        shutil.copyfile(project / "assets/icon.png", icon_dir / "io.miemie.AppManager.png")
    else:
        image = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(project / "assets/icon.svg"), pixels, pixels, True)
        image.savev(str(icon_dir / "io.miemie.AppManager.png"), "png", [], [])
scalable = stage / "usr/share/icons/hicolor/scalable/apps"
scalable.mkdir(parents=True)
shutil.copyfile(project / "assets/icon.svg", scalable / "io.miemie.AppManager.svg")
doc_dir = stage / "usr/share/doc/miemie-app-manager"
doc_dir.mkdir(parents=True)
shutil.copyfile(project / "LICENSE", doc_dir / "copyright")
control_dir = stage / "DEBIAN"
control_dir.mkdir()
cache_script = '''#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
exit 0
'''
for name in ("postinst", "postrm"):
    script = control_dir / name
    cleanup = '''
case "$1" in
  remove|purge)
    rm -f -- /etc/polkit-1/rules.d/49-xingxu-app-manager-*.rules
    rm -rf -- /var/lib/miemie-app-manager/authorizations
    rmdir /var/lib/miemie-app-manager 2>/dev/null || true
    ;;
esac
''' if name == "postrm" else ""
    script.write_text(cache_script.replace("exit 0\n", cleanup + "exit 0\n"))
    script.chmod(0o755)
for path in stage.rglob("*"):
    path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) // 1024 + 1
(control_dir / "control").write_text(f'''Package: miemie-app-manager
Version: {__version__}
Section: admin
Priority: optional
Architecture: all
Maintainer: haotian <271516878+wanghao9103@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-apt, python3-gi, gir1.2-gtk-3.0, librsvg2-common, apt, dpkg, pkexec, polkitd, hicolor-icon-theme, gtk-update-icon-cache, desktop-file-utils
Recommends: adwaita-icon-theme
Installed-Size: {size}
Description: Native Ubuntu desktop application manager
 Lists installed desktop applications with icons, package versions and
 installation records. Supports name search, update checks and reviewed upgrades/removal
 through APT, Snap and Flatpak.
''')
artifact = project / f"deliverables/miemie-app-manager_{__version__}_all.deb"
subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(artifact)], check=True)
shutil.rmtree(stage)
print(artifact)
