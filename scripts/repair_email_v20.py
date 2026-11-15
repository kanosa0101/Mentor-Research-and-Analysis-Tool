"""Apply reviewed email corrections only if the stored erroneous value is unchanged."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler import store
from crawler.model import Professor


def repair(root, apply=False):
    import yaml
    source = json.loads((ROOT / 'data/migrations/email_repairs_v20.json').read_text(encoding='utf8'))
    report = {'changed': [], 'already_correct': [], 'skipped_newer_or_missing': []}
    for patch in source['repairs']:
        path = root / patch['path']
        if not path.exists():
            report['skipped_newer_or_missing'].append(patch['path'])
            continue
        p = store._yaml_load(path)
        if p.get('email') == patch['email']:
            report['already_correct'].append(patch['path'])
            continue
        if p.get('email') != patch['old_email']:
            report['skipped_newer_or_missing'].append(patch['path'])
            continue
        p['email'] = patch['email']
        p.setdefault('provenance', {})['email'] = dict(origin='crawled', source=patch['source_url'],
                                                      fetched_at=patch['fetched_at'], confidence='verified')
        Professor.model_validate(p)
        if apply:
            path.write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding='utf8')
        report['changed'].append(patch['path'])
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(repair(args.root.resolve(), args.apply), ensure_ascii=False, indent=2))
