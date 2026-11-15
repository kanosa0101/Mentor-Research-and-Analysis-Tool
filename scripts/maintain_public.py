"""Rotate public sources, renew unchanged audited opportunities, atomically rebuild pages."""
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.legacy_refresh import run
from crawler.opportunity_monitor import atomic_json, output_lock
from crawler.opportunity_review import renew
from scripts import build_site
from scripts.monitor_notices import collect as collect_notices
from crawler.public_snapshot import build as build_snapshot
from crawler.notice_util import classify_notice
import yaml


def refresh_notices():
    path = ROOT / 'data/notices.json'
    previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    checked = previous.get('checked_at')
    if checked and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(checked)).total_seconds() < 21600:
        return dict(skipped=True, **previous.get('summary', {}))
    configs = yaml.safe_load((ROOT / 'sites/notices.yaml').read_text(encoding='utf-8'))['targets']
    return collect_notices(configs, path, refresh=True)['summary']


def priority_units():
    units = set()
    path = ROOT / 'data/opportunities.json'
    if path.exists():
        for item in json.loads(path.read_text(encoding='utf-8'))['opportunities']:
            if item['cycle'] == 'current':
                units.add(item['school_id'] + '/' + item['dept_id'])
    path = ROOT / 'data/notices.json'
    if path.exists():
        for item in json.loads(path.read_text(encoding='utf-8'))['notices']:
            if classify_notice(item)['cycle'] in ('current', 'preparation'):
                units.add(item['school'] + '/' + item['dept'])
    return sorted(units)


def rebuild():
    # systemd ReadWritePaths uses separate bind mounts for cache and site.
    # Keep staging inside the destination mount so rename remains atomic.
    with tempfile.TemporaryDirectory(prefix='.build-', dir=ROOT / 'site') as directory:
        stage = Path(directory)
        build_site.SITE = stage
        build_site.main()
        changed = 0
        for path in stage.rglob('*'):
            if not path.is_file():
                continue
            target = ROOT / 'site' / path.relative_to(stage)
            if target.exists() and target.read_bytes() == path.read_bytes():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
            changed += 1
    return changed


def main():
    with output_lock(ROOT / 'cache/public-maintenance'):
        result = {'started_at': datetime.now(timezone.utc).isoformat(), 'failures': {}}
        def task(name, action):
            try:
                result[name] = action()
            except Exception as error:
                result['failures'][name] = str(error)[:1000]
                result[name] = {'error': 1, 'message': '本阶段失败，其他独立维护继续'}
        task('policies', lambda: run(ROOT, kind='policies', limit=20, workers=4, timeout=12))
        task('professors', lambda: run(ROOT, kind='professors', limit=40, timeout=12, priority_units=priority_units()))
        task('notices', refresh_notices)
        task('renewed', lambda: renew(ROOT / 'cache/opportunity_review.json', ROOT))
        task('pages_updated', rebuild)
        if 'pages_updated' not in result['failures']:
            task('public_snapshot', lambda: build_snapshot(ROOT))
        result['completed_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(ROOT / 'cache/public-maintenance.json', result)
        atomic_json(ROOT / 'cache/maintenance-alerts.json', {'checked_at': result['completed_at'], 'failures': result['failures']})
        print(json.dumps(result, ensure_ascii=False))
        return int(bool(result['failures']) or result['policies'].get('error', 0) > 0 or
                   result['professors'].get('error', 0) > 0 or result['notices'].get('sources_error', 0) > 0)


if __name__ == '__main__':
    try:
        if '--build-only' in sys.argv:
            print('Public pages updated:', rebuild())
        else:
            sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
