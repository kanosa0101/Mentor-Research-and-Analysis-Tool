"""限量、可续跑地回源旧导师与政策；不把抓取成功改写为人工审核成功。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.legacy_refresh import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--kind', choices=('all', 'policies', 'professors'), default='all')
    parser.add_argument('--limit', type=int, default=30, help='每类本轮最多检查条数；按最久未尝试轮转')
    parser.add_argument('--unit', action='append', default=[], help='限定 school/dept，可重复')
    parser.add_argument('--workers', type=int, default=4, help='政策并发数；导师顺序解析')
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--retry', action='store_true', help='优先重试失败记录，并允许再次检查24小时内已尝试记录')
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000 or not 1 <= args.workers <= 8 or not 1 <= args.timeout <= 60:
        parser.error('limit 1..1000, workers 1..8, timeout 1..60')
    report = run(args.root, kind=args.kind, limit=args.limit, units=args.unit,
                 workers=args.workers, timeout=args.timeout, retry=args.retry)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report['error'] > 0)


if __name__ == '__main__':
    sys.exit(main())
