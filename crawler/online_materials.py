"""Account-owned uploads used by the existing application workflow.

The HTTP caller authenticates the account, checks CSRF, and holds the workflow
write lock across upload and metadata persistence. No browser-supplied path is
accepted. Original private directories are never scanned or imported.
"""
import base64
import binascii
import copy
import os
import re
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from crawler import contact_util as contact
from crawler import material_task_util as tasks
from crawler import workflow_util as core

MAX_FILE_BYTES = 20_000_000
MAX_REQUEST_BYTES = 28_000_000
MAX_USER_BYTES = 200_000_000
UPLOAD_FIELDS = {'filename', 'content_base64', 'title', 'kind', 'notes', 'project_ids', 'mentor_ids'}
PENDING_DELETE = '.pending-delete'


class Conflict(ValueError):
    pass


def safe_filename(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 200
            or value in ('.', '..', PENDING_DELETE) or value != value.strip() or value.endswith('.')
            or re.search(r'[\x00-\x1f\x7f/\\:*?"<>|]', value)
            or re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', value)):
        raise ValueError('文件名无效，请使用不含路径或特殊字符的文件名')
    return value


def _no_links(path):
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise ValueError('材料存储路径无效')


def _folder(user_root):
    folder = Path(user_root).absolute() / 'materials'
    _no_links(folder)
    return folder


def _owned_file(user_root, value, require_exists=True):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('材料必须是本账号上传的文件')
    path, folder = Path(value), _folder(user_root)
    try:
        parts = path.relative_to(folder).parts
    except ValueError:
        raise ValueError('材料必须是本账号上传的文件') from None
    if len(parts) != 2 or not re.fullmatch(r'[a-f0-9]{32}', parts[0]):
        raise ValueError('材料必须是本账号上传的文件')
    safe_filename(parts[1])
    _no_links(path)
    if not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError('材料必须是本账号上传的文件')
    if require_exists and not path.is_file():
        raise ValueError('材料文件不存在，请重新上传')
    return path


def validate_storage_paths(data, user_root):
    """Check ownership before reads; absent files must not block unrelated records."""
    if not isinstance(data, dict):
        raise ValueError('工作流须为对象')

    def visit(value):
        if isinstance(value, dict):
            if 'path' in value:
                _owned_file(user_root, value['path'], require_exists=False)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for key in ('materials', 'drafts', 'communications', 'material_tasks'):
        visit(data.get(key, {}))


def missing_materials(data, user_root):
    return {key for key, material in data.get('materials', {}).items()
            if not _owned_file(user_root, material['path'], require_exists=False).is_file()}


def _used_bytes(folder):
    if not folder.exists():
        return 0
    size = 0
    for current, dirs, names in os.walk(folder, followlinks=False):
        for name in (*dirs, *names):
            path = Path(current) / name
            _no_links(path)
            if path.is_file():
                size += path.stat().st_size
    return size


def _cleanup_pending(folder, data):
    if not folder.exists():
        return
    used_folders = {Path(m['path']).parent for m in data.get('materials', {}).values()}
    for child in folder.iterdir():
        if re.fullmatch(r'[a-f0-9]{32}', child.name) and child not in used_folders:
            _no_links(child)
            pending = child / PENDING_DELETE
            _no_links(pending)
            if pending.is_file():
                pending.unlink()
                if not any(child.iterdir()):
                    child.rmdir()


def add_upload(user_root, data, body, known_ids):
    """Return (workflow, material); caller persists and rolls back on save failure."""
    if not isinstance(body, dict) or set(body) - UPLOAD_FIELDS:
        raise ValueError('上传参数无效，不接受服务器文件路径')
    filename = safe_filename(body.get('filename'))
    encoded = body.get('content_base64')
    if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES + 2) // 3 * 4:
        raise ValueError('单个材料最大 20 MB')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('材料内容编码无效') from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError('请选择非空文件，单个材料最大 20 MB')
    validate_storage_paths(data, user_root)
    folder = _folder(user_root)
    _cleanup_pending(folder, data)
    if _used_bytes(folder) + len(raw) > MAX_USER_BYTES:
        raise ValueError('账号材料存储上限为 200 MB')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    upload_folder = folder / uuid4().hex
    upload_folder.mkdir(mode=0o700)
    path = upload_folder / filename
    try:
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(0o600)
        base = tasks.project(data)
        metadata = {k: copy.deepcopy(v) for k, v in body.items()
                    if k not in ('filename', 'content_base64')}
        metadata.update(path=str(path), title=body.get('title') or filename)
        updated, material = core.update_entry(contact.core_view(base), 'materials', metadata, known_ids)
        if base.get('version') == 1:
            result = updated
        else:
            result = contact.merge_core(base, updated, known_ids)
        return tasks.merge(data, result), material
    except Exception:
        path.unlink(missing_ok=True)
        upload_folder.rmdir()
        raise


def rollback_upload(user_root, material):
    path = _owned_file(user_root, material['path'])
    path.unlink()
    path.parent.rmdir()


def download(user_root, data, material_id):
    if not isinstance(material_id, str) or not re.fullmatch(r'[a-f0-9]{32}', material_id):
        raise KeyError('材料不存在')
    entry = data.get('materials', {}).get(material_id)
    if not isinstance(entry, dict):
        raise KeyError('材料不存在')
    path = _owned_file(user_root, entry.get('path'))
    return path, path.name


def download_headers(filename):
    safe_filename(filename)
    return {'Content-Type': 'application/octet-stream',
            'Content-Disposition': "attachment; filename=\"material\"; filename*=UTF-8''" + quote(filename, safe=''),
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}


def delete_upload(user_root, data, material_id, persist):
    """Delete an unreferenced upload while retaining originals on a failed save."""
    validate_storage_paths(data, user_root)
    entry = data.get('materials', {}).get(material_id)
    if not isinstance(entry, dict):
        raise KeyError('材料不存在')
    path = _owned_file(user_root, entry.get('path'), require_exists=False)

    def referenced(value):
        if isinstance(value, dict):
            if material_id in value.get('material_ids', []) or value.get('path') == str(path):
                return True
            return any(referenced(item) for item in value.values())
        return isinstance(value, list) and any(referenced(item) for item in value)

    if any(referenced(data.get(kind, {})) for kind in ('drafts', 'communications', 'material_tasks')):
        raise Conflict('材料已用于邮件草稿、沟通历史或准备记录，保留原文件以便核对，不能删除')
    updated = copy.deepcopy(data)
    del updated['materials'][material_id]
    # Removing the index first means interruption cannot leave a valid record
    # pointing at a file we have moved. An interrupted quarantine is reclaimed
    # on the next upload, only when no current material references its folder.
    persist(updated)
    if not path.exists():
        if path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()
        return {'deleted': True, 'material_id': material_id}
    pending = path.with_name(PENDING_DELETE)
    try:
        if pending.exists():
            raise ValueError('材料删除尚未完成，请稍后重试')
        path.rename(pending)
        pending.unlink()
    except Exception:
        if pending.is_file() and not path.exists():
            pending.rename(path)
        persist(data)
        raise
    if not any(path.parent.iterdir()):
        path.parent.rmdir()
    return {'deleted': True, 'material_id': material_id}
