"""只检查已登记政策原文及附件落地页；不自动改写人工摘要。"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import admissions_util as admissions, fetch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=ROOT / 'data/admissions.yaml')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/admissions_checks.json')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    data = yaml.safe_load(args.input.read_text(encoding='utf-8'))
    units = {}
    for cfg in (ROOT / 'sites').glob('*/*.yaml'):
        unit = yaml.safe_load(cfg.read_text(encoding='utf-8'))
        units.setdefault(unit['school'], set()).add(unit['dept'])
    admissions.validate(data, units)
    old = json.loads(args.output.read_text(encoding='utf-8')) if args.output.exists() else {}
    admissions.validate_checks(old, data['sources'])
    observations = {}
    fetch.set_direct(True)
    for sid, source in data['sources'].items():
        observations[sid] = admissions.check_source(source, old.get(sid, {}), args.refresh, date.today().isoformat())
        print(sid, observations[sid]['status'], observations[sid].get('last_success', '未成功'), 'cached' if observations[sid].get('cached') else '')
    # 相同目录临时文件+replace，采用现有原子写入方式，但公开检查输出为JSON。
    admissions.validate_checks(observations, data['sources'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import os
    import tempfile
    fd, path = tempfile.mkstemp(dir=args.output.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(observations, handle, ensure_ascii=False, indent=2)
        os.replace(path, args.output)
    finally:
        Path(path).unlink(missing_ok=True)
    return int(any(r['status'] != 'ok' for r in observations.values()))


if __name__ == '__main__':
    sys.exit(main())
