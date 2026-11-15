"""Evaluate official drafts with AI; --publish explicitly enables restricted automatic publication."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.automatic_review import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--queue', type=Path)
    parser.add_argument('--limit', type=int, default=2)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        result = run(args.root, args.queue, limit=args.limit, publish=args.publish)
        print(json.dumps({k: result[k] for k in ('counts', 'published_ids', 'renewed_ids', 'errors')}, ensure_ascii=False))
        return int(bool(result['errors']))
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
