"""Preview/apply the reviewed content manifest without replacing newer public records."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler.content_migration import migrate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data/migrations/opportunity-content-v20.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/v20/content')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    report = migrate(args.root, manifest, apply=args.apply, output=args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / ('migration-applied.json' if args.apply else 'migration-preview.json')).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'changed': len(report['changes']), 'unchanged': len(report['unchanged']),
                      'skipped': report['skipped'], 'applied': args.apply}, ensure_ascii=False))


if __name__ == '__main__':
    main()
