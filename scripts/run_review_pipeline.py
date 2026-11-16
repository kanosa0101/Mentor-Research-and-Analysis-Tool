"""Run bounded public-source discovery, evidence review and maintainer alerts."""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import automatic_review, review_queue, source_discovery, maintenance_push, quality_status
from crawler.opportunity_monitor import atomic_json, output_lock
from crawler.pipeline_metrics import summarize


def rebuild(root):
    with output_lock(root / 'cache/public-maintenance'):
        result = subprocess.run(
            [sys.executable, '-X', 'utf8', str(root / 'scripts/maintain_public.py'), '--build-only'],
            cwd=root, capture_output=True, text=True, encoding='utf8', timeout=600)
        if result.returncode:
            raise ValueError('公共页面重建失败；下轮重试')
        return {'published': True}


def run(root=ROOT, *, limit=2, publish=False, discover=False, max_seeds=4, max_candidates=8):
    root = Path(root)
    path = root / 'cache/review-pipeline.json'
    with output_lock(root / 'cache/review-pipeline-run'):
        previous = json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
        result = dict(started_at=datetime.now(timezone.utc).isoformat(), failures={},
                      mode='publish' if publish else 'assess',
                      built_catalog_sha256=previous.get('built_catalog_sha256'))

        def phase(name, action):
            try:
                result[name] = action()
            except Exception as error:
                # Only controlled errors are displayed; never serialize request headers or credentials.
                result['failures'][name] = type(error).__name__
                result[name] = {'error': True, 'message': '本阶段未完成，其他独立阶段继续；请检查维护日志'}

        if discover:
            phase('discovery', lambda: source_discovery.run(root, max_seeds=max_seeds, max_candidates=max_candidates,
                                                          auto_admit=publish))
        phase('automatic', lambda: automatic_review.run(root, limit=limit, publish=publish))
        phase('alerts', lambda: review_queue.refresh_alerts(root))
        phase('quality_alerts', lambda: quality_status.refresh(root))
        if publish and 'alerts' not in result['failures']:
            combined = dict(result['alerts'], active=result['alerts'].get('active', []) +
                            result.get('quality_alerts', {}).get('active', []))
            phase('maintainer_notifications', lambda: maintenance_push.dispatch(root, combined))
        catalog = root / 'data/opportunities.json'
        if publish and catalog.exists():
            def publish_pages():
                digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
                if digest == result['built_catalog_sha256']:
                    return {'skipped': True, 'reason': '公开目录未变化'}
                publication = rebuild(root)
                result['built_catalog_sha256'] = digest
                return publication
            phase('public_pages', publish_pages)
        phase('metrics', lambda: summarize(root))
        result['completed_at'] = datetime.now(timezone.utc).isoformat()
        delivery = result.get('maintainer_notifications', {})
        attention = bool(result.get('automatic', {}).get('errors') or
                         delivery.get('failed') or delivery.get('retry_exhausted') or
                         result.get('quality_alerts', {}).get('failures') or
                         result.get('quality_alerts', {}).get('incomplete') or
                         any(value is False for value in result.get('quality_alerts', {}).get('available', {}).values()) or
                         result.get('quality_alerts', {}).get('summary', {}).get('overdue'))
        result['status'] = 'partial' if result['failures'] else 'attention' if attention else 'ok'
        atomic_json(path, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--limit', type=int, default=2)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--max-seeds', type=int, default=4)
    parser.add_argument('--max-candidates', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.limit <= 5 or not 1 <= args.max_seeds <= 8 or not 1 <= args.max_candidates <= 24:
        parser.error('每轮最多5次AI评估、8个来源入口、24个候选来源')
    result = run(args.root, limit=args.limit, publish=args.publish, discover=args.discover,
                 max_seeds=args.max_seeds, max_candidates=args.max_candidates)
    print(json.dumps({'status': result['status'], 'failures': result['failures'],
                      'automatic': result.get('automatic', {}).get('counts'),
                      'alerts': result.get('alerts', {}).get('summary')}, ensure_ascii=False))
    return int(bool(result['failures']))


if __name__ == '__main__':
    sys.exit(main())
