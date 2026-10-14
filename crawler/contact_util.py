"""导师联系闭环；公开数据不变，旧工作流仅在写入时升级。"""
import copy
import hashlib
import json
import mimetypes
import re
from datetime import datetime
from email.message import EmailMessage
from email import policy
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from crawler import workflow_util as core

STAGES = ('research', 'preparing', 'waiting', 'replied', 'materials', 'meeting', 'closed')
PRIORITIES = ('high', 'normal', 'low')
EXTRA = dict(target_id='', draft_id='', recipient='', attachments=[])
DEFAULTS = {
    'targets': dict(project_id='', mentor_id='', priority='normal', reason='', stage='research'),
    'drafts': dict(target_id='', recipient='', subject='', body='', basis='', material_ids=[], attachments=[]),
}
ATTACHMENT_LIMIT = 20_000_000


def core_view(data):
    result = {'version': 1, **{k: copy.deepcopy(data[k]) for k in core.KINDS}}
    for entry in result['communications'].values():
        if not isinstance(entry, dict):
            raise ValueError('沟通记录须为对象')
        for key in EXTRA:
            entry.pop(key, None)
    return result


def sync_targets(data):
    pairs = {(t['project_id'], t['mentor_id']): t for t in data['targets'].values()}
    for project in data['projects'].values():
        for mentor in project['mentor_ids']:
            pair = (project['id'], mentor)
            if pair not in pairs:
                key = uuid5(NAMESPACE_URL, 'mentor-application:' + ':'.join(pair)).hex
                entry = {**DEFAULTS['targets'], 'id': key, 'project_id': pair[0], 'mentor_id': mentor,
                         'created_at': project['created_at'], 'updated_at': project['updated_at']}
                data['targets'][key] = entry
                pairs[pair] = entry
    for event in sorted(data['communications'].values(), key=lambda e: (e['date'], e['created_at'])):
        if not event['target_id'] and (event['project_id'], event['mentor_id']) in pairs:
            target = pairs[(event['project_id'], event['mentor_id'])]
            event['target_id'] = target['id']
            if event['kind'] in ('sent', 'replied'):
                target['stage'] = 'waiting' if event['kind'] == 'sent' else 'replied'
                target['updated_at'] = event['created_at']
    return data


def upgrade(data, known_ids):
    if not isinstance(data, dict):
        raise ValueError('工作流须为对象')
    data = copy.deepcopy(data)
    if data.get('version') == 1:
        core.validate_workflow(data, known_ids)
        data.update(version=2, targets={}, drafts={})
        for event in data['communications'].values():
            event.update(copy.deepcopy(EXTRA))
    validate(data, known_ids)
    sync_targets(data)
    validate(data, known_ids)
    return data


def validate(data, known_ids):
    if not isinstance(data, dict) or set(data) != {'version', *core.KINDS, *DEFAULTS} or type(data['version']) is not int or data['version'] != 2:
        raise ValueError('联系工作流版本或结构错误')
    if any(not isinstance(data[k], dict) for k in (*core.KINDS, *DEFAULTS)):
        raise ValueError('工作流集合须为对象')
    core.validate_workflow(core_view(data), known_ids)
    pairs = set()
    for kind in DEFAULTS:
        for key, entry in data[kind].items():
            if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
                raise ValueError('无效联系记录 ID')
            if not isinstance(entry, dict) or set(entry) != {*DEFAULTS[kind], 'id', 'created_at', 'updated_at'} or entry['id'] != key:
                raise ValueError('联系记录结构错误')
            for field, default in DEFAULTS[kind].items():
                if isinstance(default, str) and not isinstance(entry[field], str):
                    raise ValueError(f'{field} 须为字符串')
            for field in ('created_at', 'updated_at'):
                if not isinstance(entry[field], str):
                    raise ValueError('时间须为字符串')
                datetime.fromisoformat(entry[field])
            if kind == 'targets':
                if entry['project_id'] not in data['projects'] or entry['mentor_id'] not in known_ids:
                    raise ValueError('目标导师须关联已知项目和导师')
                if entry['stage'] not in STAGES or entry['priority'] not in PRIORITIES:
                    raise ValueError('目标阶段或优先级错误')
                pair = (entry['project_id'], entry['mentor_id'])
                if pair in pairs:
                    raise ValueError('同一项目导师目标不可重复')
                pairs.add(pair)
            else:
                if entry['target_id'] not in data['targets']:
                    raise ValueError('未知目标导师')
                core.refs(entry['material_ids'], data['materials'], 'material_ids')
                validate_attachments(entry['attachments'], data)
                if [a['material_id'] for a in entry['attachments']] != entry['material_ids']:
                    raise ValueError('草稿附件与所选材料不一致')
                if any(core.path_key(a['path']) != core.path_key(data['materials'][a['material_id']]['path']) for a in entry['attachments']):
                    raise ValueError('草稿附件路径不对应所选登记材料')
    for event in data['communications'].values():
        if set(event) != {*core.DEFAULTS['communications'], *EXTRA, 'id', 'created_at', 'updated_at'}:
            raise ValueError('沟通记录结构错误')
        for key in ('target_id', 'draft_id', 'recipient'):
            if not isinstance(event[key], str):
                raise ValueError('沟通关联须为字符串')
        if event['target_id']:
            target = data['targets'].get(event['target_id'])
            if target is None or (event['mentor_id'], event['project_id']) != (target['mentor_id'], target['project_id']):
                raise ValueError('沟通目标上下文不一致')
        if event['draft_id']:
            draft = data['drafts'].get(event['draft_id'])
            if draft is None or event['target_id'] != draft['target_id'] or event['kind'] != 'sent':
                raise ValueError('已发草稿关联错误')
        validate_attachments(event['attachments'], data)
    if len(json.dumps({'version': 2, 'workflow': data}, ensure_ascii=False, indent=2).encode('utf-8')) > core.MAX_BACKUP_BYTES:
        raise ValueError('完整工作流超过 16 MB')


def validate_attachments(items, data):
    if not isinstance(items, list):
        raise ValueError('附件快照须为列表')
    for item in items:
        if not isinstance(item, dict) or set(item) != {'material_id', 'title', 'path', 'size', 'mtime', 'sha256'}:
            raise ValueError('附件快照结构错误')
        if any(not isinstance(item[k], str) for k in ('material_id', 'title', 'path', 'mtime', 'sha256')):
            raise ValueError('附件快照字段错误')
        if item['material_id'] not in data['materials'] or not Path(item['path']).is_absolute():
            raise ValueError('未知附件材料')
        if type(item['size']) is not int or item['size'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('附件指纹错误')
        datetime.fromisoformat(item['mtime'])


def merge_core(data, result, known_ids):
    data = copy.deepcopy(data)
    old_events = data['communications']
    for kind in core.KINDS:
        data[kind] = result[kind]
    for key, event in data['communications'].items():
        event.update(copy.deepcopy({field: old_events.get(key, EXTRA).get(field, default) for field, default in EXTRA.items()}))
    sync_targets(data)
    validate(data, known_ids)
    return data


def file_bytes(path, remaining):
    with Path(path).open('rb') as fh:
        raw = fh.read(remaining + 1)
    if len(raw) > remaining:
        raise ValueError('单封附件总量最多 20 MB')
    return raw


def snapshots(data, ids):
    core.refs(ids, data['materials'], 'material_ids')
    result, remaining = [], ATTACHMENT_LIMIT
    for key in ids:
        material = data['materials'][key]
        meta = core.material_metadata(material['path'])
        raw = file_bytes(meta['path'], remaining)
        remaining -= len(raw)
        result.append(dict(material_id=key, title=material['title'], path=meta['path'], size=len(raw),
                           mtime=meta['mtime'], sha256=hashlib.sha256(raw).hexdigest()))
    return result


def update(data, kind, body, known_ids, record_id=None):
    if kind not in DEFAULTS or not isinstance(body, dict):
        raise ValueError('请求须为对象')
    data = copy.deepcopy(data)
    if record_id is not None and record_id not in data[kind]:
        raise KeyError('未知记录')
    allowed = set(DEFAULTS[kind]) - {'attachments'}
    if record_id:
        allowed -= {'project_id', 'mentor_id'} if kind == 'targets' else {'target_id'}
    if set(body) - allowed:
        raise ValueError('包含未知或不可修改字段')
    if kind == 'targets' and record_id is None:
        record_id = next((key for key, t in data[kind].items() if
                          (t['project_id'], t['mentor_id']) == (body.get('project_id'), body.get('mentor_id'))), None)
    if kind == 'drafts' and record_id and any(e['draft_id'] == record_id for e in data['communications'].values()):
        raise ValueError('已确认发送的草稿不可修改，请新建草稿')
    key, now = record_id or uuid4().hex, datetime.now().isoformat(timespec='microseconds')
    previous_stage = data[kind].get(key, {}).get('stage')
    entry = data[kind].get(key) or {**copy.deepcopy(DEFAULTS[kind]), 'id': key, 'created_at': now}
    entry.update(body, updated_at=now)
    if kind == 'drafts' and 'material_ids' in body:
        entry['attachments'] = snapshots(data, body['material_ids'])
    data[kind][key] = entry
    validate(data, known_ids)
    if kind == 'targets':
        project = data['projects'][entry['project_id']]
        if entry['mentor_id'] not in project['mentor_ids']:
            project['mentor_ids'].append(entry['mentor_id'])
        if previous_stage and previous_stage != entry['stage']:
            data, _ = add_event(data, entry, {'kind': 'note', 'date': now[:10], 'subject': '联系阶段更新',
                                            'content': previous_stage + ' → ' + entry['stage']}, known_ids)
    elif data['targets'][entry['target_id']]['stage'] == 'research':
        data['targets'][entry['target_id']].update(stage='preparing', updated_at=now)
    validate(data, known_ids)
    return data, entry


def add_event(data, target, body, known_ids, extra=None):
    body = {**body, 'mentor_id': target['mentor_id'], 'project_id': target['project_id']}
    result, event = core.update_entry(core_view(data), 'communications', body, known_ids)
    data = merge_core(data, result, known_ids)
    event = data['communications'][event['id']]
    event.update(target_id=target['id'], **(extra or {}))
    return data, event


def ready(data, draft):
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", draft['recipient']):
        raise ValueError('请填写单个有效邮箱')
    if any(not draft[k].strip() for k in ('subject', 'body', 'basis')) or '\n' in draft['subject'] or '\r' in draft['subject']:
        raise ValueError('请补齐主题、正文和联系依据，主题不可换行')
    if re.search(r'【[^】]*】', draft['subject'] + draft['body']):
        raise ValueError('请替换正文和主题中的占位内容')
    if data['targets'][draft['target_id']]['stage'] == 'closed':
        raise ValueError('目标已结束，请先明确重新打开阶段')
    result, remaining = [], ATTACHMENT_LIMIT
    for attachment in draft['attachments']:
        raw = file_bytes(attachment['path'], remaining)
        remaining -= len(raw)
        if len(raw) != attachment['size'] or hashlib.sha256(raw).hexdigest() != attachment['sha256']:
            raise ValueError('附件已变化，请重新选择并保存草稿')
        result.append((attachment, raw))
    return result


def export_eml(data, draft_id):
    if draft_id not in data['drafts']:
        raise KeyError('未知草稿')
    draft = data['drafts'][draft_id]
    attachments = ready(data, draft)
    message = EmailMessage(policy=policy.SMTP)
    message['To'], message['Subject'] = draft['recipient'], draft['subject']
    message['X-Unsent'] = '1'
    message.set_content(draft['body'])
    for attachment, raw in attachments:
        mime = mimetypes.guess_type(attachment['path'])[0] or 'application/octet-stream'
        main, sub = mime.split('/', 1)
        message.add_attachment(raw, maintype=main, subtype=sub, filename=Path(attachment['path']).name)
    return message.as_bytes()


def confirm(data, draft_id, body, known_ids):
    if not isinstance(body, dict) or set(body) != {'sent', 'date'} or body['sent'] is not True:
        raise ValueError('须明确确认已经实际发送并填写日期')
    core.iso_date(body['date'])
    if draft_id not in data['drafts']:
        raise KeyError('未知草稿')
    existing = next((e for e in data['communications'].values() if e['draft_id'] == draft_id), None)
    if existing:
        return data, existing
    draft = data['drafts'][draft_id]
    ready(data, draft)
    target = data['targets'][draft['target_id']]
    data, event = add_event(data, target, {'kind': 'sent', 'date': body['date'], 'subject': draft['subject'],
                                        'content': draft['body'], 'material_ids': draft['material_ids']}, known_ids,
                            dict(draft_id=draft_id, recipient=draft['recipient'], attachments=copy.deepcopy(draft['attachments'])))
    data['targets'][target['id']].update(stage='waiting', updated_at=event['created_at'])
    validate(data, known_ids)
    return data, event


def reply(data, target_id, body, known_ids):
    if not isinstance(body, dict) or set(body) - {'content', 'date', 'stage', 'task'} or not isinstance(body.get('content'), str) or not body['content'].strip():
        raise ValueError('请填写回复内容')
    if target_id not in data['targets']:
        raise KeyError('未知目标导师')
    if body.get('stage') not in STAGES:
        raise ValueError('无效后续阶段')
    target = data['targets'][target_id]
    data, event = add_event(data, target, {'kind': 'replied', 'date': body.get('date', ''), 'subject': '收到导师回复',
                                        'content': body['content']}, known_ids)
    if body.get('task') is not None:
        task = body['task']
        if not isinstance(task, dict) or set(task) != {'title', 'due_date'}:
            raise ValueError('下一步须有标题和计划日期')
        result, _ = core.update_entry(core_view(data), 'reminders', {**task, 'mentor_id': target['mentor_id'],
                                                                   'project_id': target['project_id']}, known_ids)
        data = merge_core(data, result, known_ids)
    data['targets'][target_id].update(stage=body['stage'], updated_at=event['created_at'])
    validate(data, known_ids)
    return data, event
