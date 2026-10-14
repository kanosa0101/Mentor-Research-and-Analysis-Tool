"""私人申请工作流：稳定 ID 关联，材料仅索引元数据，不推断身份或联系状态。"""
import copy
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

KINDS = ('projects', 'materials', 'communications', 'reminders')
DEFAULTS = {
    'projects': dict(name='', school='', college='', application_type='', year=None,
                     status='planned', notes='', mentor_ids=[]),
    'materials': dict(path='', title='', kind='other', notes='', mentor_ids=[], project_ids=[],
                      size=0, mtime='', missing=False),
    'communications': dict(mentor_id='', project_id='', material_ids=[], kind='note',
                           date='', subject='', content=''),
    'reminders': dict(title='', mentor_id='', project_id='', due_date='', notes='', completed=False),
}
PROJECT_STATUSES = ('planned', 'submitted', 'interview', 'accepted', 'rejected', 'archived')
MATERIAL_KINDS = ('paper', 'letter', 'cv', 'application', 'other')
COMMUNICATION_KINDS = ('draft', 'sent', 'replied', 'note')
SKIP_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'cache'}
MAX_BACKUP_BYTES = 16_000_000


def empty_workflow():
    return {'version': 1, **{kind: {} for kind in KINDS}}


def iso_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('日期须为 YYYY-MM-DD')


def refs(value, known, field):
    if not isinstance(value, list) or any(not isinstance(x, str) or x not in known for x in value):
        raise ValueError(f'{field} 包含未知关联 ID')
    if len(set(value)) != len(value):
        raise ValueError(f'{field} 不可重复')


def validate_workflow(data, known_ids):
    if not isinstance(data, dict) or set(data) != {'version', *KINDS} or type(data['version']) is not int or data['version'] != 1:
        raise ValueError('申请工作流版本或结构错误')
    if any(not isinstance(data[k], dict) for k in KINDS):
        raise ValueError('工作流记录须为对象')
    material_paths = set()
    for kind in KINDS:
        for key, entry in data[kind].items():
            if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{32}', key):
                raise ValueError('无效记录 ID')
            if not isinstance(entry, dict) or set(entry) != {*DEFAULTS[kind], 'id', 'created_at', 'updated_at'} or entry['id'] != key:
                raise ValueError(f'{kind} 记录结构错误')
            for field, default in DEFAULTS[kind].items():
                if isinstance(default, str) and not isinstance(entry[field], str):
                    raise ValueError(f'{field} 须为字符串')
            for field in ('created_at', 'updated_at'):
                if not isinstance(entry[field], str):
                    raise ValueError('时间须为字符串')
                datetime.fromisoformat(entry[field])
            if kind in ('projects', 'materials'):
                refs(entry['mentor_ids'], known_ids, 'mentor_ids')
            if kind == 'projects':
                if not entry['name'].strip() or entry['status'] not in PROJECT_STATUSES:
                    raise ValueError('项目名称或状态错误')
                if entry['year'] is not None and (type(entry['year']) is not int or not 2000 <= entry['year'] <= 2100):
                    raise ValueError('申请年度须为 2000–2100 或未知')
            elif kind == 'materials':
                refs(entry['project_ids'], data['projects'], 'project_ids')
                if not Path(entry['path']).is_absolute() or not entry['title'].strip() or entry['kind'] not in MATERIAL_KINDS:
                    raise ValueError('材料路径、标题或类型错误')
                if type(entry['size']) is not int or entry['size'] < 0 or type(entry['missing']) is not bool:
                    raise ValueError('材料元数据错误')
                datetime.fromisoformat(entry['mtime'])
                normalized = path_key(entry['path'])
                if normalized in material_paths:
                    raise ValueError('材料索引包含重复路径')
                material_paths.add(normalized)
            else:
                if entry['mentor_id'] and entry['mentor_id'] not in known_ids:
                    raise ValueError('未知导师')
                if entry['project_id'] and entry['project_id'] not in data['projects']:
                    raise ValueError('未知申请项目')
                if kind == 'communications':
                    if not entry['mentor_id'] or not entry['subject'].strip() or entry['kind'] not in COMMUNICATION_KINDS:
                        raise ValueError('沟通须有导师、主题和有效类型')
                    refs(entry['material_ids'], data['materials'], 'material_ids')
                    iso_date(entry['date'])
                else:
                    if not entry['title'].strip() or not (entry['mentor_id'] or entry['project_id']):
                        raise ValueError('提醒须有标题并关联项目或导师')
                    if type(entry['completed']) is not bool:
                        raise ValueError('completed 须为布尔值')
                    iso_date(entry['due_date'])
    if len(json.dumps({'version': 1, 'workflow': data}, ensure_ascii=False, indent=2).encode('utf-8')) > MAX_BACKUP_BYTES:
        raise ValueError('工作台索引超过 16 MB，请缩短沟通正文；原材料仍保留在本地')


def material_metadata(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('请填写材料的绝对路径')
    path = Path(value).resolve(strict=True)
    if not path.is_file():
        raise ValueError('材料须为现有文件')
    stat = path.stat()
    return dict(path=str(path), size=stat.st_size,
                mtime=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='microseconds'), missing=False)


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def update_entry(data, kind, body, known_ids, record_id=None):
    if kind not in KINDS or not isinstance(body, dict):
        raise ValueError('请求须为对象')
    allowed = set(DEFAULTS[kind]) - ({'size', 'mtime', 'missing'} if kind == 'materials' else set())
    if record_id is not None:
        if kind == 'communications':
            raise ValueError('沟通历史只追加；纠正时请追加备注')
        if record_id not in data[kind]:
            raise KeyError('未知记录')
        if kind == 'materials':
            allowed.discard('path')
    if set(body) - allowed:
        raise ValueError('包含未知或不可修改字段')
    data = copy.deepcopy(data)
    metadata = None
    if kind == 'materials' and record_id is None:
        metadata = material_metadata(body.get('path'))
        record_id = next((key for key, entry in data[kind].items()
                          if path_key(entry['path']) == path_key(metadata['path'])), None)
    key = record_id or uuid4().hex
    now = datetime.now().isoformat(timespec='microseconds')
    entry = data[kind].get(key) or {**copy.deepcopy(DEFAULTS[kind]), 'id': key, 'created_at': now}
    entry.update(body)
    if metadata:
        entry.update(metadata)
        if not entry['title']:
            entry['title'] = Path(entry['path']).name
    entry['updated_at'] = now
    data[kind][key] = entry
    validate_workflow(data, known_ids)
    return data, entry


def scan_materials(data, root, known_ids):
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError('请填写材料目录的绝对路径')
    folder = Path(root).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('扫描目标须为目录')
    # 全部发现成功后才更新索引；异常或超过上限不落库。
    files = []
    def fail(error):
        raise error
    for current, dirs, names in os.walk(folder, onerror=fail, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(current) / d).is_symlink())
        for name in sorted(names):
            path = Path(current) / name
            if not path.is_symlink():
                files.append(material_metadata(str(path)))
            if len(files) > 1000:
                raise ValueError('单次最多扫描 1000 个文件，请选择较小的材料目录')
    data = copy.deepcopy(data)
    now = datetime.now().isoformat(timespec='microseconds')
    existing = {path_key(entry['path']): key for key, entry in data['materials'].items()}
    seen = set()
    added = 0
    for metadata in files:
        normalized = path_key(metadata['path'])
        key = existing.get(normalized) or uuid4().hex
        entry = data['materials'].get(key)
        if entry is None:
            added += 1
            entry = {**copy.deepcopy(DEFAULTS['materials']), 'id': key, 'created_at': now,
                     'title': Path(metadata['path']).name}
        entry.update(metadata, updated_at=now)
        data['materials'][key] = entry
        seen.add(normalized)
    missing = 0
    for entry in data['materials'].values():
        path = Path(entry['path']).resolve()
        if path.is_relative_to(folder) and path_key(path) not in seen:
            if path.is_file():
                # 跳过目录不发现新文件，但已人工登记的文件仍复查存在性。
                entry.update(material_metadata(str(path)), updated_at=now)
            else:
                entry.update(missing=True, updated_at=now)
                missing += 1
    validate_workflow(data, known_ids)
    return data, {'scanned': len(files), 'added': added, 'missing': missing}
