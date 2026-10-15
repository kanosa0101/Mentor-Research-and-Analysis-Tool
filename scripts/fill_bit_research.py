"""Recover bounded verbatim research sections from historical BIT CS biographies.

Default: read-only JSON plan. --apply writes only missing research fields, retaining
the biography's original provenance and all existing record values and formatting.
No requests, cache reads, source refresh, or timestamps are created by this script.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sites.bit.bit_cs import extract_research_direction


def planned_record(record):
    if record.get('school') != 'bit' or record.get('dept') != 'cs':
        return None, 'outside BIT CS scope'
    provenance = record.get('provenance') or {}
    if record.get('research_direction_raw') or 'research_direction_raw' in provenance:
        return None, 'existing research value or provenance'
    origin = provenance.get('bio_raw') or {}
    if (origin.get('origin') != 'crawled' or
            urlsplit(origin.get('source', '')).hostname != 'cs.bit.edu.cn' or
            not origin.get('fetched_at')):
        return None, 'missing historical official biography provenance'
    direction = extract_research_direction(record.get('bio_raw'))
    if not direction:
        return None, 'no unambiguous nonempty bounded research section'
    updated = copy.deepcopy(record)
    updated['research_direction_raw'] = direction
    updated['provenance']['research_direction_raw'] = copy.deepcopy(origin)
    return updated, None


def updated_yaml(text, updated):
    """Insert two YAML entries without serializing or rewriting existing content."""
    node = yaml.compose(text)
    provenance = next(value for key, value in node.value if key.value == 'provenance')
    entry = yaml.safe_dump({'research_direction_raw': updated['provenance']['research_direction_raw']},
                           allow_unicode=True, sort_keys=False)
    newline = '\r\n' if '\r\n' in text else '\n'
    indented = ''.join('  '+line+newline for line in entry.splitlines())
    index = provenance.end_mark.index
    result = text[:index] + ('' if not index or text[index-1] == '\n' else newline) + indented + text[index:]
    result = result.rstrip('\r\n') + newline + yaml.safe_dump(
        {'research_direction_raw': updated['research_direction_raw']}, allow_unicode=True, sort_keys=False).replace('\n', newline)
    if yaml.safe_load(result) != updated:
        raise ValueError('YAML insertion would change unrelated record values')
    return result


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    candidates, skipped, writes = [], [], []
    directory = (ROOT / 'data/professors/bit/cs').resolve()
    for path in sorted(directory.glob('*.yaml')):
        if path.resolve().parent != directory:
            raise ValueError('Record path escapes the BIT CS directory')
        before = path.read_bytes()
        text = before.decode('utf-8')
        record = yaml.safe_load(text)
        updated, reason = planned_record(record)
        if updated is None:
            skipped.append({'slug': record['slug'], 'reason': reason, 'sha256': sha(before)})
            continue
        replacement = updated_yaml(text, updated)
        candidates.append({'slug': record['slug'], 'name': record['name'],
                           'research_direction_raw': updated['research_direction_raw'],
                           'provenance': updated['provenance']['research_direction_raw'],
                           'changed_fields': ['research_direction_raw', 'provenance.research_direction_raw'],
                           'before_sha256': sha(before), 'after_sha256': sha(replacement.encode('utf-8')),
                           'preserved_fields_sha256': sha(json.dumps(record, sort_keys=True, ensure_ascii=False).encode('utf-8')),
                           'bio_raw_sha256': sha((record.get('bio_raw') or '').encode('utf-8'))})
        writes.append((path, before, replacement))
    # Validate every insertion before applying any record.
    if args.apply:
        if any(path.read_bytes() != before for path, before, replacement in writes):
            raise ValueError('Record changed after planning; rerun the dry-run')
        for path, before, replacement in writes:
            path.write_bytes(replacement.encode('utf-8'))
    print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'candidate_count': len(candidates),
                      'skipped_count': len(skipped), 'candidates': candidates, 'skipped': skipped},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
