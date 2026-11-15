"""Explicit local public-data updates, with staging and rollback; private data excluded."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import requests
from crawler import public_snapshot as snapshot
from crawler.opportunity_monitor import atomic_json, output_lock


def origin(root):
    settings = json.loads((Path(root) / 'data/opportunity_feed.json').read_text(encoding='utf-8'))
    value = settings.get('notification_origin', '')
    url = urlsplit(value)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise ValueError('请配置可信HTTPS公共资料站点')
    return value.rstrip('/')


def check(root):
    with requests.Session() as session:
        response = session.get(origin(root) + '/api/public-data', timeout=15)
        response.raise_for_status()
        data = response.json()
    if data.get('schema') != 1 or not re.fullmatch(r'[a-f0-9]{64}', str(data.get('id', ''))):
        raise ValueError('服务器尚未发布公共资料版本')
    return data


def _safe(root, name):
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
        raise ValueError('更新目标不能是链接或工作区外路径')
    return target


def apply_stage(root, stage, backup, names):
    root, stage, backup = map(Path, (root, stage, backup))
    applied = []
    for name in names:
        _safe(root, name)
    try:
        for name in names:
            target, new, old = root / name, stage / name, backup / name
            old.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            if existed:
                os.replace(target, old)
            applied.append((name, existed))
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(new, target)
    except Exception:
        for name, existed in reversed(applied):
            target, old = root / name, backup / name
            if target.exists():
                if target.is_dir():
                    # Only explicitly enumerated public directories are ever removed.
                    if name != 'data/professors' and name != 'site/p':
                        raise ValueError('非公开目录不能回滚删除')
                    shutil.rmtree(_safe(root, name))
                else:
                    target.unlink()
            if existed:
                os.replace(old, target)
        raise


def update(root, expected_id):
    root = Path(root).resolve()
    with output_lock(root / 'cache/public-data-update'):
        descriptor = check(root)
        if descriptor['id'] != expected_id:
            raise ValueError('服务器公共资料已变化，请重新检查更新')
        version = (root / 'VERSION').read_text().strip()
        if descriptor.get('client_version') != version:
            raise ValueError('请先升级至 ' + str(descriptor.get('client_version')) + ' 客户端')
        installed = root / 'cache/public-data-installed.json'
        if installed.exists() and json.loads(installed.read_text(encoding='utf-8')).get('id') == expected_id:
            return dict(id=expected_id, already_current=True, private_data_unchanged=True)
        folder = root / 'cache/public_updates'
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='stage-', dir=folder) as directory:
            scratch = Path(directory); archive = scratch / 'download.zip'; stage = scratch / 'project'
            with requests.get(origin(root) + '/api/public-data/archive/' + descriptor['id'], timeout=45, stream=True) as response:
                response.raise_for_status()
                size = 0
                with archive.open('wb') as stream:
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 80_000_000:
                            raise ValueError('公共资料下载超出大小限制')
                        stream.write(chunk)
            manifest = snapshot.unpack(archive, stage, descriptor, version)
            shutil.copytree(root / 'crawler', stage / 'crawler', ignore=shutil.ignore_patterns('__pycache__'))
            (stage / 'scripts').mkdir()
            for script in (root / 'scripts').glob('*.py'):
                shutil.copy2(script, stage / 'scripts' / script.name)
            shutil.copytree(root / 'site/templates', stage / 'site/templates')
            for name in ('VERSION', 'release.json'):
                shutil.copy2(root / name, stage / name)
            result = subprocess.run([sys.executable, '-X', 'utf8', str(stage / 'scripts/build_site.py')],
                                    cwd=stage, capture_output=True, text=True, encoding='utf-8', timeout=600)
            if result.returncode:
                raise ValueError('新版资料验证或页面构建失败，原资料未替换：' + result.stderr[-800:])
            names = sorted(n for n in manifest['files'] if not n.startswith('data/professors/'))
            names += ['data/professors', 'site/p']
            names += [p.relative_to(stage).as_posix() for p in (stage / 'site').iterdir() if p.is_file()]
            backup = folder / ('backup-' + descriptor['id'][:16])
            if backup.exists():
                raise ValueError('该版本已经尝试更新，请查看备份后处理')
            apply_stage(root, stage, backup, names)
            atomic_json(root / 'cache/public-data-installed.json', descriptor)
            return dict(id=descriptor['id'], file_count=len(manifest['files']),
                        generated_at=descriptor['generated_at'], backup=str(backup), private_data_unchanged=True)
