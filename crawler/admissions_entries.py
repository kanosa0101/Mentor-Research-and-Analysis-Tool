"""官方招生入口及配置目录；入口登记不等于已经整理对应政策。"""
from datetime import date
from pathlib import Path

import yaml

from crawler.admissions_util import valid_date


def load_catalog(root):
    root = Path(root)
    configs = [yaml.safe_load(p.read_text(encoding='utf-8')) for p in sorted((root / 'sites').glob('*/*.yaml'))]
    school_file = root / 'data/schools.yaml'
    schools = ([{'id': s['id'], 'name': s['name']} for s in yaml.safe_load(school_file.read_text(encoding='utf-8'))['schools']]
               if school_file.exists() else [{'id': sid, 'name': sid} for sid in sorted({c['school'] for c in configs})])
    units = {s['id']: set() for s in schools}
    for cfg in configs:
        if cfg['school'] not in units:
            raise ValueError('院系所属学校未在学校配置登记')
        units[cfg['school']].add(cfg['dept'])
    return schools, units


def validate_entries(data, units, sources):
    if not isinstance(data, dict) or set(data) != {'version', 'entries'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['entries'], list):
        raise ValueError('招生入口结构错误')
    seen = set()
    for entry in data['entries']:
        required = {'school', 'dept', 'source_id', 'reviewed_at'}
        if not isinstance(entry, dict) or not required <= set(entry) or set(entry) - required - {'note', 'year', 'degree', 'route'}:
            raise ValueError('招生入口字段错误')
        if any(not isinstance(entry[k], str) for k in required):
            raise ValueError('招生入口字段须为字符串')
        if entry['school'] not in units or entry['dept'] and entry['dept'] not in units[entry['school']]:
            raise ValueError('招生入口学校或院系未登记')
        if entry['source_id'] not in sources:
            raise ValueError('招生入口来源未登记')
        if 'note' in entry and (not isinstance(entry['note'], str) or not entry['note'].strip()):
            raise ValueError('招生入口范围说明须为非空字符串')
        if 'year' in entry and (type(entry['year']) is not int or not 2000 <= entry['year'] <= 2100):
            raise ValueError('招生入口年度须为2000至2100的整数')
        if 'degree' in entry and entry['degree'] not in ('master', 'phd'):
            raise ValueError('招生入口学位范围错误')
        if 'route' in entry and entry['route'] not in ('recommend', 'exam', 'assessment'):
            raise ValueError('招生入口渠道范围错误')
        valid_date(entry['reviewed_at'])
        key = (entry['school'], entry['dept'], entry['source_id'])
        if key in seen:
            raise ValueError('招生入口重复')
        seen.add(key)


def load_entries(root, units, sources):
    path = Path(root) / 'data/admissions_entries.yaml'
    data = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'entries': []}
    validate_entries(data, units, sources)
    return data['entries']


def source_status(entry, check, today=None):
    today = date.fromisoformat(today) if today else date.today()
    result = {'state': 'unknown', 'label': '尚未检查来源', 'last_success': None,
              'last_attempt': check.get('last_attempt'), 'reviewed_at': entry['reviewed_at']}
    try:
        previous = date.fromisoformat(check.get('last_success', ''))
        if previous <= today:
            result['last_success'] = previous.isoformat()
    except (TypeError, ValueError):
        pass
    if check.get('status') == 'error':
        return dict(result, state='error', label='最近回源失败，需查官网')
    try:
        day = date.fromisoformat(check.get('last_success', ''))
        reviewed = date.fromisoformat(entry['reviewed_at'])
    except (TypeError, ValueError):
        return result
    if check.get('status') != 'ok' or not check.get('hash') or day > today:
        return dict(result, last_success=None)
    result['last_success'] = day.isoformat()
    if (today - day).days > 7:
        return dict(result, state='stale', label='来源超过7天未成功检查')
    if reviewed > today or (today - reviewed).days > 30:
        return dict(result, state='review', label='入口超过30天未核对')
    return dict(result, state='checked', label='近期回源及入口核对有效；申请前仍需查看')
