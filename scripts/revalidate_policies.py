"""Refresh official sources and reconfirm unchanged reviewed policy versions."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler.policy_revalidation import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--timeout', type=int, default=15)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--policy-id', action='append', default=[])
    args = parser.parse_args()
    result = run(args.root, limit=args.limit, workers=args.workers, timeout=args.timeout,
                 force=args.force, policy_ids=args.policy_id)
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}, ensure_ascii=False))
    return int(bool(result['retry'] or result['review_required']))


if __name__ == '__main__':
    raise SystemExit(main())
