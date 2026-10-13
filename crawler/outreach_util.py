"""私人跟进记录校验，供写回、备份恢复和 preflight 共用。"""
from datetime import date

STATUSES = ('interested', 'emailed', 'replied', 'meeting', 'archived')
TEXT_FIELDS = ('notes', 'note', 'next_action', 'due_date')


def validate_patch(body):
    if not isinstance(body, dict):
        raise ValueError('请求须为 JSON 对象')
    if set(body) - set(TEXT_FIELDS) - {'status', 'tags', 'clear'}:
        raise ValueError('包含未知字段')
    if 'status' in body and body['status'] not in STATUSES:
        raise ValueError('无效跟进状态')
    for key in TEXT_FIELDS:
        if key in body and not isinstance(body[key], str):
            raise ValueError(f'{key} 须为字符串')
    if body.get('due_date'):
        if date.fromisoformat(body['due_date']).isoformat() != body['due_date']:
            raise ValueError('日期须为 YYYY-MM-DD')
    if 'tags' in body and (not isinstance(body['tags'], list) or
                          any(not isinstance(t, str) or not t.strip() for t in body['tags'])):
        raise ValueError('tags 须为非空字符串列表')
    if 'clear' in body and not isinstance(body['clear'], bool):
        raise ValueError('clear 须为布尔值')


def validate_outreach(data, known_ids):
    if not isinstance(data, dict):
        raise ValueError('跟进记录须为对象')
    for pid, entry in data.items():
        if pid not in known_ids:
            raise ValueError(f'未知导师: {pid}')
        if not isinstance(entry, dict) or entry.get('status') not in STATUSES:
            raise ValueError(f'无效跟进记录: {pid}')
        validate_patch({k: v for k, v in entry.items() if k not in ('updated_at', 'history')})
        if not isinstance(entry.get('history', []), list):
            raise ValueError(f'无效历史: {pid}')
        for h in entry.get('history', []):
            if not isinstance(h, dict) or not h.get('date') or not h.get('action'):
                raise ValueError(f'无效历史: {pid}')
            if 'note' in h and not isinstance(h['note'], str):
                raise ValueError(f'无效历史备注: {pid}')
