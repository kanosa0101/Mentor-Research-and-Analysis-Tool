"""Bounded official source discovery; proposals never publish opportunities."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import source_discovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--max-seeds', type=int, default=6)
    parser.add_argument('--max-candidates', type=int, default=12)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    result = source_discovery.run(args.root, max_seeds=args.max_seeds, max_candidates=args.max_candidates, refresh=args.refresh)
    print(json.dumps(result['summary'], ensure_ascii=False))


if __name__ == '__main__':
    main()
