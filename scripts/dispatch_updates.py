"""Build public update events and deliver only to explicitly subscribed browsers."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util, push_util

if __name__ == '__main__':
    catalog = opportunity_util.observed(ROOT)
    added = push_util.record(ROOT, catalog, catalog.get('monitoring'))
    result = push_util.dispatch(ROOT) if push_util.config(ROOT) else {'disabled': True}
    report = dict(events_added=added, **result)
    (ROOT / 'var/push/last_delivery.json').write_text(json.dumps(report), encoding='utf-8')
    print(json.dumps(report))
    sys.exit(1 if result.get('failed') else 0)
