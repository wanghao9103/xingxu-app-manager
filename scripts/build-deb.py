#!/usr/bin/python3
from pathlib import Path
import shutil
import subprocess
import sys

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
from app_manager import __version__
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
desktop_dir = stage / "usr/share/applications"
desktop_dir.mkdir(parents=True)
shutil.copyfile(project / "assets/io.miemie.AppManager.desktop", desktop_dir / "io.miemie.AppManager.desktop")
icon_dir = stage / "usr/share/icons/hicolor/256x256/apps"
icon_dir.mkdir(parents=True)
shutil.copyfile(project / "assets/icon.png", icon_dir / "io.miemie.AppManager.png")
doc_dir = stage / "usr/share/doc/miemie-app-manager"
doc_dir.mkdir(parents=True)
shutil.copyfile(project / "LICENSE", doc_dir / "copyright")
control_dir = stage / "DEBIAN"
control_dir.mkdir()
size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) // 1024 + 1
(control_dir / "control").write_text(f'''Package: miemie-app-manager
Version: {__version__}
Section: admin
Priority: optional
Architecture: all
Maintainer: haotian <271516878+wanghao9103@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, librsvg2-common, apt, dpkg, pkexec
Recommends: adwaita-icon-theme
Installed-Size: {size}
Description: Native Ubuntu desktop application manager
 Lists installed desktop applications with icons, package versions and
 installation records. Supports name search and reviewed package removal
 through APT, Snap and Flatpak.
''')
artifact = project / f"deliverables/miemie-app-manager_{__version__}_all.deb"
subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(artifact)], check=True)
shutil.rmtree(stage)
print(artifact)
