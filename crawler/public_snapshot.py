"""Versioned public data only; never include private workflows or credentials."""
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from crawler.opportunity_monitor import atomic_json, output_lock

FIXED = {'data/schools.yaml', 'data/admissions.yaml', 'data/admissions_entries.yaml',
         'data/admissions_checks.json', 'data/notices.json', 'data/opportunities.json',
         'sites/notices.yaml', 'sites/opportunities.yaml'}
OPTIONAL = {'data/coverage.json'}


def allowed(name):
    return name in FIXED | OPTIONAL or bool(re.fullmatch(
        r'(?:data/professors/[a-z0-9_-]+/[a-z0-9_-]+/[^/\\:.\x00]+\.yaml|sites/[a-z0-9_-]+/[a-z0-9_-]+\.yaml)', name))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(root):
    root = Path(root)
    folder = root / 'cache/public_snapshots'
    folder.mkdir(parents=True, exist_ok=True)
    with output_lock(folder / 'build'):
        paths = [root / name for name in FIXED]
        paths += [root / name for name in OPTIONAL if (root / name).exists()]
        paths += list((root / 'data/professors').glob('*/*/*.yaml')) + list((root / 'sites').glob('*/*.yaml'))
        files = {}
        for path in sorted(paths):
            name = path.relative_to(root).as_posix()
            if not allowed(name) or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('公开资料路径错误')
            raw = path.read_bytes()
            files[name] = {'size': len(raw), 'sha256': digest(raw)}
        version = (root / 'VERSION').read_text().strip()
        identity = digest(json.dumps({'client_version': version, 'files': files}, sort_keys=True).encode())
        target = folder / (identity + '.zip')
        manifest = dict(schema=1, id=identity, client_version=version,
                        generated_at=datetime.now(timezone.utc).isoformat(), files=files)
        if not target.exists():
            temporary = folder / (identity + '.tmp')
            with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, info in files.items():
                    raw = (root / name).read_bytes()
                    if digest(raw) != info['sha256']:
                        raise ValueError('资料生成期间发生变化，请重试')
                    archive.writestr(name, raw)
                archive.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False))
            temporary.replace(target)
        else:
            with zipfile.ZipFile(target) as archive:
                manifest = json.loads(archive.read('MANIFEST.json'))
        descriptor = {k: manifest[k] for k in ('schema', 'id', 'client_version', 'generated_at')}
        descriptor.update(size=target.stat().st_size, sha256=digest(target.read_bytes()),
                          file_count=len(files), archive='/api/public-data/archive/' + identity)
        atomic_json(folder / 'latest.json', descriptor)
        previous = sorted(folder.glob('*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in previous[2:]:
            if old != target and re.fullmatch(r'[a-f0-9]{64}\.zip', old.name) and not old.is_symlink():
                old.unlink()
        return descriptor


def latest(root):
    path = Path(root) / 'cache/public_snapshots/latest.json'
    return json.loads(path.read_text()) if path.exists() else None


def unpack(archive_path, destination, descriptor, client_version):
    """Reject path traversal, private files, incomplete or incompatible snapshots."""
    destination = Path(destination)
    if descriptor.get('schema') != 1 or descriptor.get('client_version') != client_version:
        raise ValueError('公共资料需要对应版本客户端，请先升级运行包')
    if digest(Path(archive_path).read_bytes()) != descriptor.get('sha256'):
        raise ValueError('公共资料下载校验失败')
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > 15000 or sum(i.file_size for i in infos) > 200_000_000 or any(i.file_size > 20_000_000 for i in infos):
            raise ValueError('公共资料超出大小限制')
        if len({i.filename for i in infos}) != len(infos):
            raise ValueError('公共资料存在重复文件')
        manifest = json.loads(archive.read('MANIFEST.json'))
        files = manifest['files']
        if not FIXED <= set(files) or not any(n.startswith('data/professors/') for n in files):
            raise ValueError('公共资料缺少必要文件')
        if set(archive.namelist()) != set(files) | {'MANIFEST.json'} or any(not allowed(n) for n in files):
            raise ValueError('公共资料包含未经允许的路径')
        identity = digest(json.dumps({'client_version': client_version, 'files': files}, sort_keys=True).encode())
        if manifest.get('id') != identity or descriptor.get('id') != identity or manifest.get('client_version') != client_version:
            raise ValueError('公共资料版本清单不一致')
        for name, info in files.items():
            raw = archive.read(name)
            if len(raw) != info['size'] or digest(raw) != info['sha256']:
                raise ValueError('公共资料文件校验失败')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return manifest
