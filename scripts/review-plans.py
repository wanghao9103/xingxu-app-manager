"""Read-only audit of every currently visible application removal plan."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app_manager.backend import Manager

manager = Manager()
apps = manager.scan()
errors = []
counts = {}
previous = None
if '--retry-errors' in sys.argv and Path('docs/plans-review.json').is_file():
    previous = json.loads(Path('docs/plans-review.json').read_text())
    counts.update(previous['by_source'])
    retry = {item['name'] for item in previous['errors']}
for app in apps:
    if previous and app.name not in retry:
        continue
    try:
        manager.plan(app.id)
        counts[app.source] = counts.get(app.source, 0) + 1
    except Exception as e:
        errors.append({"name": app.name, "source": app.source, "error": str(e)})
report = {"applications": len(apps), "plans_ready": sum(counts.values()), "by_source": counts, "errors": errors, "uninstall_executed": False}
if previous:
    report['rechecked_previous_failures'] = sorted(retry)
Path("docs/plans-review.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps(report, ensure_ascii=False))
