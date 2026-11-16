"""申请目标 v3：保留旧文本，结构范围与政策时间快照由用户明确登记。"""
import copy
import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from crawler import workflow_util as core

PUBLIC_YAML_LOADER = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)

DEFAULTS = dict(school_id='', dept_id='', degree='', route='', track='',
                program_code='', program_name='', deadlines=[])
OPTIONAL = {'opportunity'}
DATE_KEYS = {'label', 'kind', 'at', 'origin', 'policy_id', 'source_ids', 'source_url', 'quote', 'locator'}


def load_context(root):
    root = Path(root)
    paths = [*sorted((root / 'sites').glob('*/*.yaml')),
             root / 'data/schools.yaml', root / 'data/admissions.yaml']
    signature = tuple((str(path.resolve()), stat.st_mtime_ns, stat.st_size, stat.st_ino)
                      for path in paths for stat in [path.stat()])
    # Only public configuration is cached. Callers may attach checks or modify lists.
    return copy.deepcopy(_read_context(signature, PUBLIC_YAML_LOADER))


@lru_cache(maxsize=4)
def _read_context(signature, loader):
    units = {}
    paths = [Path(row[0]) for row in signature]
    for path in paths[:-2]:
        cfg = yaml.load(path.read_text(encoding='utf-8'), Loader=loader)
        if isinstance(cfg, dict) and cfg.get('school') and cfg.get('dept'):
            units.setdefault(cfg['school'], set()).add(cfg['dept'])
    schools = yaml.load(paths[-2].read_text(encoding='utf-8'), Loader=loader)
    for school in schools['schools']:
        units.setdefault(school['id'], set())
    admissions = yaml.load(paths[-1].read_text(encoding='utf-8'), Loader=loader)
    return dict(units=units, sources=admissions['sources'], policies=admissions['policies'])


def structure(entry):
    if 'opportunity' in entry:
        from crawler.opportunity_util import validate
        validate(entry['opportunity'])
    for key, default in DEFAULTS.items():
        if key not in entry or isinstance(default, str) and not isinstance(entry[key], str):
            raise ValueError('申请目标结构错误')
    for key, values in [('degree', ('master', 'phd')), ('route', ('recommend', 'exam', 'assessment')),
                        ('track', ('ordinary', 'special'))]:
        if entry[key] and entry[key] not in values:
            raise ValueError('申请目标学位、渠道或类别错误')
    if entry['dept_id'] and not entry['school_id']:
        raise ValueError('选择院系前须选择学校')
    if not isinstance(entry['deadlines'], list):
        raise ValueError('项目时间须为列表')
    seen = set()
    for event in entry['deadlines']:
        if not isinstance(event, dict) or set(event) != DATE_KEYS:
            raise ValueError('项目时间字段错误')
        if any(not isinstance(event[k], str) for k in DATE_KEYS - {'source_ids'}):
            raise ValueError('项目时间字段须为字符串')
        if not event['label'].strip() or event['kind'] not in ('deadline', 'exam', 'qualification', 'plan') or event['origin'] not in ('manual', 'policy'):
            raise ValueError('项目时间名称、类型或来源错误')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', event['at']):
            date.fromisoformat(event['at'])
        elif not re.match(r'^\d{4}-\d{2}-\d{2}T', event['at']) or datetime.fromisoformat(event['at']).tzinfo is None:
            raise ValueError('时间须为 YYYY-MM-DD 或含时区的 ISO 日期时间')
        if not isinstance(event['source_ids'], list) or any(not isinstance(s, str) or not s for s in event['source_ids']) or len(set(event['source_ids'])) != len(event['source_ids']):
            raise ValueError('项目时间来源 ID 错误')
        if event['source_url']:
            url = urlsplit(event['source_url'])
            if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
                raise ValueError('项目时间来源须为无凭证 HTTP(S) 地址')
        if event['origin'] == 'manual':
            if event['policy_id'] or event['source_ids']:
                raise ValueError('个人计划不可携带官方政策来源')
        elif not event['policy_id'] or not event['source_ids'] or not all(event[k].strip() for k in ('source_url', 'quote', 'locator')) or event['kind'] == 'plan':
            raise ValueError('政策时间须包含完整原文来源')
        signature = json.dumps(event, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            raise ValueError('项目时间不可重复')
        seen.add(signature)


def applicable(entry, policy):
    if policy.get('applies_if'):
        return False
    if not all(entry[k] for k in ('school_id', 'dept_id', 'year', 'degree', 'route', 'track')):
        return False
    if any(entry[a] != policy[b] for a, b in [('school_id', 'school'), ('year', 'year'), ('degree', 'degree'), ('route', 'route')]):
        return False
    if policy['dept'] and entry['dept_id'] != policy['dept']:
        return False
    track = policy.get('track', 'general' if policy['level'] == 'school' else 'ordinary')
    if track != entry['track'] and not (track == 'general' and entry['track'] == 'ordinary'):
        return False
    is_program = policy['level'] == 'program' or track == 'special' and bool(policy['program'])
    return not is_program or bool(entry['program_name']) and (entry['program_code'], entry['program_name']) == (policy['program_code'], policy['program'])


def validate(data, context):
    for entry in data['projects'].values():
        structure(entry)


def validate_imports(entry, previous, context):
    if 'opportunity' in entry and (previous is None or entry['opportunity'] != previous.get('opportunity')):
        if entry['opportunity'] not in context.get('opportunities', []):
            raise ValueError('活动快照须来自当前已核对目录')
    scope_changed = previous is None or any(entry[k] != previous[k] for k in (*DEFAULTS.keys() - {'deadlines'}, 'year'))
    if scope_changed:
        if entry['school_id'] and entry['school_id'] not in context['units']:
            raise ValueError('未知学校 ID')
        if entry['dept_id'] and entry['dept_id'] not in context['units'][entry['school_id']]:
            raise ValueError('学校与院系 ID 不匹配')
    old_events = previous['deadlines'] if previous else []
    for event in entry['deadlines']:
        if event['origin'] != 'policy':
            continue
        if event in old_events:
            if scope_changed:
                raise ValueError('目标已改变；请明确清理旧政策时间后重新选择适用事件')
            continue
        policy = next((p for p in context['policies'] if p['id'] == event['policy_id']), None)
        if policy is None or not applicable(entry, policy):
            raise ValueError('政策时间不适用于当前目标；请先明确清理该时间记录')
        if not any(
            all(event[k] == candidate[k] for k in ('label', 'kind', 'at', 'quote', 'locator')) and
            event['source_ids'] == candidate.get('source_ids', [policy['source_id']]) and
            event['source_url'] == context['sources'][candidate.get('source_ids', [policy['source_id']])[0]]['url']
            for candidate in policy.get('events', [])):
            raise ValueError('政策时间与已核对原文事件不一致')


def upgrade(data, known_ids, context):
    from crawler import contact_util as contact
    data = contact.upgrade(data, known_ids)
    if data['version'] == 2:
        data['version'] = 3
        for entry in data['projects'].values():
            entry.update(copy.deepcopy(DEFAULTS))
    contact.validate(data, known_ids)
    validate(data, context)
    return data


def update(data, body, known_ids, context, record_id=None):
    from crawler import contact_util as contact
    if not isinstance(body, dict) or set(body) - {*core.DEFAULTS['projects'], *DEFAULTS, *OPTIONAL}:
        raise ValueError('包含未知或不可修改字段')
    base, entry = core.update_entry(contact.core_view(data), 'projects', {k: v for k, v in body.items() if k not in DEFAULTS and k not in OPTIONAL}, known_ids, record_id)
    result = contact.merge_core(data, base, known_ids)
    entry = result['projects'][entry['id']]
    entry.update(copy.deepcopy({k: v for k, v in body.items() if k in DEFAULTS or k in OPTIONAL}))
    contact.validate(result, known_ids)
    validate(result, context)
    validate_imports(entry, data['projects'].get(record_id), context)
    return result, entry
