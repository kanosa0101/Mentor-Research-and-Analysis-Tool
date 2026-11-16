"""Recheck public mentor issues; rules never infer missing identity or contact details."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler.mentor_quality import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--limit', type=int, default=40)
    parser.add_argument('--retry', action='store_true')
    parser.add_argument('--unit', action='append', default=[])
    args = parser.parse_args()
    result = run(args.root, limit=args.limit, retry=args.retry, units=args.unit)
    print(json.dumps({key: value for key, value in result.items() if key != 'results'}, ensure_ascii=False))
    return int(result['error'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
