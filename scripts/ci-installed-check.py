#!/usr/bin/python3
"""Real install/removal regression, restricted to a root GitHub Actions runner."""
from pathlib import Path
import json
import os
import sys

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.geteuid() != 0:
    raise SystemExit('This destructive regression is restricted to the disposable GitHub Actions runner.')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager import __version__
from app_manager.backend import Manager, run
from app_manager.ui import app_icon


def root_runner(args, **kwargs):
    # The CI harness already runs as root; interactive authentication is tested on the desktop.
    return run(args[1:] if args[0] == '/usr/bin/pkexec' else args, **kwargs)


manager = Manager(root_runner)
app = next(a for a in manager.scan() if a.package == 'miemie-app-manager')
assert app.version == __version__ and app.source == 'APT' and app.removable
assert app.name == '星序应用管理'
assert Path(app.icon).is_file() and app.icon.startswith('/usr/share/icons/')
assert app_icon(app).get_pixbuf() is not None
plan = manager.plan(app.id)
assert plan.removed == ['miemie-app-manager']
assert not plan.installed and not plan.risky
manager.uninstall(plan)
for filename in ('/usr/bin/miemie-app-manager', '/usr/share/applications/io.miemie.AppManager.desktop', app.icon):
    assert not Path(filename).exists(), filename
assert root_runner(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}', 'apt']).strip() == 'installed'
assert root_runner(['/usr/bin/dpkg-query', '-W', '-f=${db:Status-Status}', 'python3-gi']).strip() == 'installed'
report = {'version': __version__, 'system_icon_decodes': True, 'self_plan_only_removes_manager': True,
          'real_ci_package_removed': True, 'core_dependencies_retained': True,
          'production_user_software_removed': False}
output = Path('.local/ci-installed-report.json')
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
