"""Explicit optional AI suggestions for one public official draft; no publication."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.ai_evidence import assist_draft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('id', help='已有公开原文草稿ID')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--queue', type=Path, default=ROOT/'cache/opportunity_review.json')
    args = parser.parse_args()
    try:
        result = assist_draft(args.root, args.queue, args.id)
        print(json.dumps({'suggestions':len(result['suggestions']), 'validated_extracts':True, 'published':False}, ensure_ascii=False))
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
