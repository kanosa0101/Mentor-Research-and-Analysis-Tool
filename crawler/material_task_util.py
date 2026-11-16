"""Version 4 material progress wrapper; existing workflow modules receive v3 projections."""
import copy
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from crawler import contact_util as contact
from crawler import project_util as projects
from crawler import project_review_util as reviews
from crawler import workflow_util as core

STATUSES = ('todo', 'prepared', 'submitted', 'needs_revision')
BODY_KEYS = {'project_id', 'expected_goal', 'policy_id', 'action_id', 'expected_action',
             'status', 'material_ids', 'notes', 'confirmed_conditions'}
RECORD_KEYS = {'id', 'project_id', 'policy_id', 'policy_title', 'action_id', 'action',
               'action_fingerprint', 'goal_snapshot', 'source_snapshot', 'events', 'status',
               'material_ids', 'attachments', 'notes', 'confirmed_conditions', 'created_at'}


class Conflict(ValueError):
    pass


def project(data):
    result = copy.deepcopy(data)
    if result.get('version') == 4:
        result.pop('material_tasks', None)
        result['version'] = 3
    return result


def merge(previous, result):
    result = copy.deepcopy(result)
    if previous.get('version') == 4:
        result.update(version=4, material_tasks=copy.deepcopy(previous['material_tasks']))
    return result


def upgrade(data, known_ids, context):
    if isinstance(data, dict) and data.get('version') == 4:
        if set(data) != {'version', *core.KINDS, *contact.DEFAULTS, 'material_tasks'}:
            raise ValueError('材料工作流结构错误')
        result = merge(data, projects.upgrade(project(data), known_ids, context))
        validate(result, known_ids, context)
        return result
    return projects.upgrade(data, known_ids, context)


def validate(data, known_ids, context):
    base = project(data)
    contact.validate(base, known_ids)
    projects.validate(base, context)
    if data.get('version') == 4:
        if set(data) != {'version', *core.KINDS, *contact.DEFAULTS, 'material_tasks'} or not isinstance(data['material_tasks'], dict):
            raise ValueError('材料工作流结构错误')
        for key, entry in data['material_tasks'].items():
            validate_record(key, entry)
    if len(json.dumps({'version': data['version'], 'workflow': data}, ensure_ascii=False, indent=2).encode('utf-8')) > core.MAX_BACKUP_BYTES:
        raise ValueError('完整工作流超过 16 MB')


def validate_record(key, entry):
    if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key) or not isinstance(entry, dict) or set(entry) != RECORD_KEYS or entry['id'] != key:
        raise ValueError('材料进度记录结构错误')
    if any(not isinstance(entry[k], str) for k in RECORD_KEYS - {'action', 'goal_snapshot', 'source_snapshot', 'events', 'material_ids', 'attachments', 'confirmed_conditions'}):
        raise ValueError('材料进度字段错误')
    if entry['status'] not in STATUSES or type(entry['confirmed_conditions']) is not bool or not re.fullmatch('[0-9a-f]{64}', entry['action_fingerprint']):
        raise ValueError('材料进度状态或指纹错误')
    if any(not re.fullmatch('[0-9a-f]{32}', entry[k]) for k in ('id', 'project_id')) or any(not re.fullmatch('[a-z0-9_-]+', entry[k]) for k in ('policy_id', 'action_id')):
        raise ValueError('材料进度关联 ID 错误')
    datetime.fromisoformat(entry['created_at'])
    reviews.validate_goal(entry['goal_snapshot'])
    if not isinstance(entry['action'], dict) or not isinstance(entry['source_snapshot'], dict) or not isinstance(entry['events'], list):
        raise ValueError('材料动作快照错误')
    validate_snapshot(entry)
    if not isinstance(entry['material_ids'], list) or any(not isinstance(mid, str) for mid in entry['material_ids']) or len(set(entry['material_ids'])) != len(entry['material_ids']):
        raise ValueError('材料关联错误')
    if not isinstance(entry['attachments'], list) or any(not isinstance(a, dict) for a in entry['attachments']) or [a.get('material_id') for a in entry['attachments'] if isinstance(a, dict)] != entry['material_ids']:
        raise ValueError('材料附件快照与关联不一致')
    # Historical paths may no longer belong to the live index. Validate shape only; never open them here.
    historical = {'materials': {mid: {} for mid in entry['material_ids']}}
    contact.validate_attachments(entry['attachments'], historical)
    if sum(item['size'] for item in entry['attachments']) > contact.ATTACHMENT_LIMIT:
        raise ValueError('本次材料附件总量最多 20 MB')


def valid_url(value):
    if not isinstance(value, str):
        raise ValueError('材料来源 URL 错误')
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ValueError('材料来源须为无凭证 HTTP(S) URL')
    try:
        if url.port == 0:
            raise ValueError('材料来源端口错误')
    except ValueError as error:
        raise ValueError('材料来源端口错误') from error


def evidence_shape(evidence, source_ids):
    if not isinstance(evidence, dict) or not {'text', 'quote', 'locator'} <= set(evidence) or set(evidence) - {'text', 'quote', 'locator', 'source_ids'} or any(not isinstance(evidence[k], str) or not evidence[k].strip() for k in ('text', 'quote', 'locator')):
        raise ValueError('材料动作原文证据错误')
    if 'source_ids' in evidence:
        refs = evidence['source_ids']
        if not isinstance(refs, list) or not refs or any(not isinstance(sid, str) or sid not in source_ids for sid in refs) or len(set(refs)) != len(refs):
            raise ValueError('材料动作证据来源错误')


def validate_snapshot(entry):
    snapshot = entry['source_snapshot']
    if set(snapshot) != {'sources', 'scope', 'conditions', 'source_id'} or not isinstance(snapshot['sources'], dict) or not snapshot['sources']:
        raise ValueError('材料来源快照错误')
    if not isinstance(snapshot['source_id'], str) or snapshot['source_id'] not in snapshot['sources']:
        raise ValueError('材料主来源快照错误')
    for sid, item in snapshot['sources'].items():
        if not isinstance(sid, str) or not re.fullmatch('[a-z0-9_-]+', sid) or not isinstance(item, dict) or set(item) != {'url', 'review_hash'} or not isinstance(item['review_hash'], str) or not re.fullmatch('[0-9a-f]{64}', item['review_hash']):
            raise ValueError('材料来源指纹错误')
        valid_url(item['url'])
    scope = snapshot['scope']
    if not isinstance(scope, dict) or set(scope) != {'school', 'dept', 'year', 'degree', 'route', 'track', 'level', 'program_code', 'program'} or type(scope['year']) is not int or not 2000 <= scope['year'] <= 2100 or any(not isinstance(scope[k], str) for k in scope if k != 'year'):
        raise ValueError('材料政策范围快照错误')
    if scope['degree'] not in ('master', 'phd') or scope['route'] not in ('recommend', 'exam', 'assessment') or scope['track'] not in ('general', 'ordinary', 'special') or scope['level'] not in ('school', 'dept', 'program'):
        raise ValueError('材料政策范围值错误')
    conditions = snapshot['conditions']
    if not isinstance(conditions, list) or len(conditions) > 2:
        raise ValueError('材料条件快照错误')
    seen = set()
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {'scope', 'evidence'} or condition['scope'] not in ('policy', 'action') or condition['scope'] in seen:
            raise ValueError('材料条件快照错误')
        seen.add(condition['scope'])
        evidence_shape(condition['evidence'], snapshot['sources'])
    action = entry['action']
    if not {'id', 'label', 'stage', 'instruction'} <= set(action) or set(action) - {'id', 'label', 'stage', 'instruction', 'applies_if', 'event_indexes'} or action['id'] != entry['action_id'] or not isinstance(action['label'], str) or not action['label'].strip() or action['stage'] not in ('application', 'screening', 'interview', 'admission', 'enrollment', 'other'):
        raise ValueError('材料动作快照错误')
    evidence_shape(action['instruction'], snapshot['sources'])
    if 'applies_if' in action:
        evidence_shape(action['applies_if'], snapshot['sources'])
    indexes = action.get('event_indexes', [])
    if not isinstance(indexes, list) or any(type(i) is not int or i < 0 for i in indexes) or len(set(indexes)) != len(indexes):
        raise ValueError('材料事项索引错误')
    if len(entry['events']) != len(indexes):
        raise ValueError('材料事项快照错误')
    for index, resolved in zip(indexes, entry['events']):
        if not isinstance(resolved, dict) or set(resolved) != {'event_index', 'event', 'source_url'} or type(resolved['event_index']) is not int or resolved['event_index'] != index:
            raise ValueError('材料事项快照错误')
        valid_url(resolved['source_url'])
        if resolved['source_url'] not in [source['url'] for source in snapshot['sources'].values()]:
            raise ValueError('材料事项来源不在已核对来源中')
        event = resolved['event']
        if not isinstance(event, dict) or not {'label', 'kind', 'at', 'quote', 'locator'} <= set(event) or set(event) - {'label', 'kind', 'at', 'quote', 'locator', 'source_ids'} or any(not isinstance(event[k], str) or not event[k].strip() for k in ('label', 'kind', 'at', 'quote', 'locator')) or event['kind'] not in ('deadline', 'exam', 'qualification'):
            raise ValueError('材料事项原文错误')
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', event['at']):
            date.fromisoformat(event['at'])
        elif datetime.fromisoformat(event['at']).tzinfo is None:
            raise ValueError('材料事项时间须明确时区')
        if 'source_ids' in event:
            evidence_shape(dict(text=event['label'], quote=event['quote'], locator=event['locator'], source_ids=event['source_ids']), snapshot['sources'])
    bound = dict(policy_id=entry['policy_id'], source_id=snapshot['source_id'], goal_snapshot=entry['goal_snapshot'], scope=scope, conditions=conditions, action=action, sources=snapshot['sources'], events=entry['events'])
    if reviews.fingerprint(bound) != entry['action_fingerprint']:
        raise ValueError('材料动作快照指纹不一致')


def quality(policy, context, today=None):
    from crawler.policy_revalidation import confirmation_date, valid_revalidation
    checks = context.get('checks', {})
    sources = [(value, checks.get(sid, {})) for sid, value in policy.get('review_hashes', {}).items()]
    state, label = 'checked', '近期检查与核对版本一致；申请前仍需查看官网'
    def age(value):
        try:
            current = date.fromisoformat(today) if today else datetime.now(timezone(timedelta(hours=8))).date()
            return (current - date.fromisoformat(value)).days
        except (TypeError, ValueError):
            return -1
    if any(c.get('status') == 'error' for _, c in sources):
        state, label = 'error', '来源检查失败，需人工复核'
    elif any(c.get('hash') and c['hash'] != value for value, c in sources):
        state, label = 'changed', '原文或附件已变化，摘要待复核'
    elif not sources or any(c.get('status') != 'ok' or not c.get('hash') or not c.get('last_success') for _, c in sources):
        state, label = 'unknown', '尚无有效来源检查记录'
    elif any(not 0 <= age(c['last_success']) <= 7 for _, c in sources):
        state, label = 'stale', '来源超过7天未成功检查，需复核'
    elif policy.get('revalidation_invalid') or policy.get('revalidation') and not valid_revalidation(policy, context.get('sources')):
        state, label = 'review', '政策内容或来源配置已变化，原系统复检不再适用'
    elif (confirmed := confirmation_date(policy, context.get('sources'))) and 0 <= age(confirmed) <= 30:
        return {'state': 'checked', 'label': '系统复检：原核验版本与逐项证据一致；未改写摘要或适用年度',
                'method': 'unchanged_source', 'confirmed_at': confirmed}
    elif not 0 <= age(policy.get('reviewed_at')) <= 30:
        state, label = 'review', '摘要超过30天且无有效系统复检，需复核'
    return {'state': state, 'label': label}


def candidate(goal, policy):
    if not all(goal[k] for k in reviews.GOAL_KEYS[:6]):
        return False
    if any(goal[a] != policy[b] for a, b in [('school_id', 'school'), ('year', 'year'), ('degree', 'degree'), ('route', 'route')]):
        return False
    if policy.get('dept') and goal['dept_id'] != policy['dept']:
        return False
    track = policy.get('track', 'general' if policy['level'] == 'school' else 'ordinary')
    if track != goal['track'] and not (track == 'general' and goal['track'] == 'ordinary'):
        return False
    specific = policy['level'] == 'program' or bool(policy.get('program'))
    return not specific or not goal['program_name'] or (goal['program_code'], goal['program_name']) == (policy.get('program_code', ''), policy.get('program', ''))


def action_view(pid, goal, policy, action, context, records):
    refs = policy.get('review_hashes', {})
    sources = {sid: {'url': context['sources'].get(sid, {}).get('url', ''), 'review_hash': value} for sid, value in refs.items()}
    events = []
    for index in action.get('event_indexes', []):
        if type(index) is not int or not 0 <= index < len(policy.get('events', [])):
            raise ValueError('材料动作时间索引错误')
        event = policy['events'][index]
        source_ids = event.get('source_ids', [policy['source_id']])
        events.append({'event_index': index, 'event': copy.deepcopy(event), 'source_url': context['sources'].get(source_ids[0], {}).get('url', '')})
    conditions = [{'scope': scope, 'evidence': copy.deepcopy(item['applies_if'])} for scope, item in [('policy', policy), ('action', action)] if item.get('applies_if')]
    pending = not reviews.complete(goal) or bool((policy['level'] == 'program' or policy.get('program')) and not goal['program_name'])
    scope = {k: policy.get(k, 'general' if policy['level'] == 'school' else 'ordinary') if k == 'track' else policy.get(k, '') for k in ('school', 'dept', 'year', 'degree', 'route', 'track', 'level', 'program_code', 'program')}
    bound = dict(policy_id=policy['id'], source_id=policy['source_id'], goal_snapshot=goal, scope=scope, conditions=conditions, action=action, sources=sources, events=events)
    fingerprint = reviews.fingerprint(bound)
    q = quality(policy, context)
    valid_sources = bool(sources) and all(s['url'] for s in sources.values())
    reasons = (['goal_incomplete'] if not reviews.complete(goal) else []) + (['program_pending'] if pending else []) + ([] if valid_sources else ['source_missing'])
    applicable = not reasons
    matches = [r for r in records.values() if r['project_id'] == pid and r['policy_id'] == policy['id'] and r['action_id'] == action['id'] and r['goal_snapshot'] == goal and r['action_fingerprint'] == fingerprint]
    latest = max(matches, key=lambda r: (r['created_at'], r['id']))['id'] if matches else None
    return dict(policy_id=policy['id'], policy_title=policy['title'], action_id=action['id'], action=copy.deepcopy(action),
                action_fingerprint=fingerprint, goal_snapshot=copy.deepcopy(goal), conditions=conditions, program_pending=pending,
                quality=q, events=events, latest_record_id=latest, applicable=applicable, applicability_reasons=reasons,
                can_record=applicable and q['state'] in ('checked', 'stale', 'review')), dict(source_id=policy['source_id'], sources=sources, scope=scope, conditions=conditions)


def actions(data, context):
    result = {}
    records = data.get('material_tasks', {})
    for pid, entry in data['projects'].items():
        goal = reviews.goal_snapshot(entry)
        result[pid] = []
        if goal['dept_id'] not in context.get('units', {}).get(goal['school_id'], set()):
            continue
        for policy in context['policies']:
            if candidate(goal, policy):
                for action in policy.get('material_actions', []):
                    row, _ = action_view(pid, goal, policy, action, context, records)
                    result[pid].append(row)
    return result


def files_view(entry, data):
    result = []
    remaining = contact.ATTACHMENT_LIMIT
    for attachment in entry['attachments']:
        material = data['materials'].get(attachment['material_id'])
        state = 'unchanged'
        if material is None:
            state = 'unknown_material'
        elif core.path_key(material['path']) != core.path_key(attachment['path']):
            state = 'path_changed'
        else:
            try:
                # Read only the current registered path, never an arbitrary historical snapshot path.
                meta = core.material_metadata(material['path'])
                raw = contact.file_bytes(meta['path'], remaining)
                remaining -= len(raw)
                if (len(raw), meta['mtime'], hashlib.sha256(raw).hexdigest()) != (attachment['size'], attachment['mtime'], attachment['sha256']):
                    state = 'changed'
            except FileNotFoundError:
                state = 'missing'
            except (OSError, ValueError):
                state = 'unreadable'
        result.append(dict(copy.deepcopy(attachment), state=state))
    return result


def record_view(entry, data, action_rows):
    reasons = []
    current_project = data['projects'].get(entry['project_id'])
    if current_project is None:
        reasons.append('project_missing')
    elif reviews.goal_snapshot(current_project) != entry['goal_snapshot']:
        reasons.append('goal_changed')
    current = next((row for row in action_rows.get(entry['project_id'], []) if row['policy_id'] == entry['policy_id'] and row['action_id'] == entry['action_id']), None)
    if current is None:
        reasons.append('action_unavailable')
    else:
        if current['action_fingerprint'] != entry['action_fingerprint']:
            reasons.append('action_changed')
        if not current['applicable']:
            reasons.append('scope_pending')
        if current['quality']['state'] != 'checked':
            reasons.append('source_' + current['quality']['state'])
        if current['conditions'] and not entry['confirmed_conditions']:
            reasons.append('conditions_unconfirmed')
    applicable = not reasons
    files = files_view(entry, data)
    if any(item['state'] != 'unchanged' for item in files):
        reasons.append('files_changed')
    return dict(copy.deepcopy(entry), applicable=applicable, review_required=bool(reasons), review_reasons=reasons, files=files)


def view(data, context):
    rows = actions(data, context)
    return {'version': 1, 'actions': rows, 'records': {key: record_view(entry, data, rows) for key, entry in data.get('material_tasks', {}).items()}}


def checked_action(data, context, pid, expected_goal, policy_id, action_id, expected_action, *, require_current=False):
    reviews.validate_goal(expected_goal)
    if pid not in data['projects']:
        raise KeyError('未知申请项目')
    if reviews.goal_snapshot(data['projects'][pid]) != expected_goal:
        raise Conflict('申请目标已改变，请刷新后重新核对')
    row = next((r for r in actions(data, context)[pid] if r['policy_id'] == policy_id and r['action_id'] == action_id), None)
    if row is None or row['action_fingerprint'] != expected_action or not row['can_record']:
        raise Conflict('材料动作、适用范围或来源已改变或待核对，请刷新后重新核对')
    if require_current and row['quality']['state'] != 'checked':
        raise Conflict('官方事项来源需重新核对，暂不能据此创建提醒；个人准备记录仍可保存')
    policy = next(p for p in context['policies'] if p['id'] == policy_id)
    _, sources = action_view(pid, expected_goal, policy, row['action'], context, data.get('material_tasks', {}))
    return row, sources


def save(data, body, known_ids, context):
    if not isinstance(body, dict) or set(body) != BODY_KEYS:
        raise ValueError('材料进度请求须包含完整指定字段')
    if any(not isinstance(body[k], str) for k in ('project_id', 'policy_id', 'action_id', 'expected_action', 'status', 'notes')) or body['status'] not in STATUSES or type(body['confirmed_conditions']) is not bool:
        raise ValueError('材料进度字段或状态错误')
    row, sources = checked_action(data, context, body['project_id'], body['expected_goal'], body['policy_id'], body['action_id'], body['expected_action'])
    if row['conditions'] and not body['confirmed_conditions']:
        raise ValueError('请明确确认政策及动作的适用条件；确认不代表资格认证')
    try:
        attachments = contact.snapshots(project(data), body['material_ids'])
    except FileNotFoundError as error:
        raise ValueError('所选材料文件不存在，请重新核对已登记路径') from error
    except ValueError as error:
        raise ValueError(str(error).replace('单封附件总量最多 20 MB', '本次材料附件总量最多 20 MB')) from error
    result = copy.deepcopy(data)
    result.setdefault('material_tasks', {})
    result['version'] = 4
    key = uuid4().hex
    entry = dict(id=key, project_id=body['project_id'], policy_id=row['policy_id'], policy_title=row['policy_title'],
                 action_id=row['action_id'], action=row['action'], action_fingerprint=row['action_fingerprint'], goal_snapshot=row['goal_snapshot'],
                 source_snapshot=sources, events=row['events'], status=body['status'], material_ids=copy.deepcopy(body['material_ids']),
                 attachments=attachments, notes=body['notes'], confirmed_conditions=body['confirmed_conditions'], created_at=datetime.now().isoformat(timespec='microseconds'))
    result['material_tasks'][key] = entry
    validate(result, known_ids, context)
    return result, record_view(entry, result, actions(result, context))


def reminder(data, key, body, known_ids, context):
    if not isinstance(body, dict) or set(body) != {'expected_goal', 'expected_action', 'event_index'} or type(body['event_index']) is not int:
        raise ValueError('材料提醒请求字段错误')
    if key not in data.get('material_tasks', {}):
        raise KeyError('未知材料进度记录')
    entry = data['material_tasks'][key]
    row, _ = checked_action(data, context, entry['project_id'], body['expected_goal'], entry['policy_id'], entry['action_id'], body['expected_action'], require_current=True)
    if entry['goal_snapshot'] != row['goal_snapshot'] or entry['action_fingerprint'] != row['action_fingerprint']:
        raise Conflict('材料进度快照已失效，请重新登记')
    if row['conditions'] and not entry['confirmed_conditions']:
        raise ValueError('尚未明确确认适用条件')
    resolved = next((event for event in row['events'] if event['event_index'] == body['event_index']), None)
    if resolved is None:
        raise ValueError('该事项未明确关联当前材料动作')
    event = resolved['event']
    at = event['at']
    due = at if re.fullmatch(r'\d{4}-\d{2}-\d{2}', at) else datetime.fromisoformat(at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
    signature = reviews.fingerprint([entry['project_id'], entry['policy_id'], entry['action_id'], resolved])
    marker = '[material-action:' + signature + ']'
    for existing in data['reminders'].values():
        if existing['project_id'] == entry['project_id'] and marker in existing['notes']:
            return data, dict(existing, duplicate=True)
    file_warning = '关联文件版本需复核；本提醒不表示文件已准备完成。' if any(item['state'] != 'unchanged' for item in files_view(entry, data)) else '材料进度为人工登记，提醒不判断文件准备状态。'
    notes = '\n'.join([marker, file_warning, '人工选择的材料动作提醒；不代表已提交或院方收到。', row['policy_title'], row['action']['label'],
                       '材料说明：' + row['action']['instruction']['text'], '材料原文：' + row['action']['instruction']['quote'],
                       '材料定位：' + row['action']['instruction']['locator'], '事项类型：' + event['kind'], '原始时间：' + at, '原文：' + event['quote'], '定位：' + event['locator'],
                       '来源：' + '；'.join(context['sources'][sid]['url'] for sid in event.get('source_ids', [entry['source_snapshot']['source_id']]))])
    base, result = core.update_entry(contact.core_view(project(data)), 'reminders',
                                    dict(title=row['action']['label'] + ' · ' + event['label'], project_id=entry['project_id'], due_date=due, notes=notes), known_ids)
    updated = merge(data, contact.merge_core(project(data), base, known_ids))
    validate(updated, known_ids, context)
    return updated, dict(result, duplicate=False)
