"""Build the reviewed local release ZIP from an explicit public-file allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXED = {
    'VERSION', 'release.json', '启动应用.cmd', 'README.md', 'USER_GUIDE.md',
    'RELEASE_NOTES.md', 'RELEASE_ACCEPTANCE.md', 'REQUIREMENTS.md',
    'ARCHITECTURE.md', 'HANDOVER.md', 'requirements.txt', 'docs/INDEX.md',
    'docs/DATA_SNAPSHOT.json', 'scripts/serve.py', 'scripts/build_site.py',
    'scripts/package_release.py', 'sites/notices.yaml', 'data/schools.yaml',
    'data/admissions.yaml', 'data/admissions_entries.yaml',
    'data/admissions_checks.json', 'data/notices.json', 'data/opportunities.json',
    'scripts/monitor_opportunities.py', 'scripts/monitor_notices.py', '启动信息监测.cmd', 'sites/opportunities.yaml', 'data/opportunity_feed.json',
    'scripts/review_opportunities.py', 'scripts/refresh_legacy.py',
    'deploy/DELIVERY_V1.2_2026-11-15.md',
    'deploy/DELIVERY_V1.3_2026-11-15.md',
    'deploy/DELIVERY_V1.4_2026-11-15.md',
    'deploy/DELIVERY_V1.5_2026-11-15.md', 'data/coverage.json',
    'scripts/serve_review.py',
    'scripts/assist_opportunity.py', 'data/source_coverage.json',
    'deploy/DELIVERY_V1.6_2026-11-15.md',
    'deploy/DELIVERY_V1.7_2026-11-15.md',
}
PATTERNS = (
    'crawler/*.py', 'sites/*/*.yaml', 'sites/*.py', 'sites/*/*.py', 'site/*.html', 'site/*.js', 'site/*.css',
    'site/templates/*.j2', 'site/p/*.html', 'data/professors/*/*/*.yaml',
    'docs/history/pre-v1.5/*.md', 'docs/history/pre-v1.5/*.json',
    'docs/history/pre-v1/*.md',
    'docs/history/pre-v1.6/*.md', 'docs/history/pre-v1.6/*.json',
    'docs/history/pre-v1.7/*.md', 'docs/history/pre-v1.7/*.json',
)
REQUIRED_SITE = {
    'site/start.html', 'site/coverage.html', 'site/start.js',
    'site/browser-library-core.js', 'site/browser-library.js', 'site/public-data.js',
    'site/plan-transfer.js', 'site/school-catalog.js', 'site/discovery-data.js',
    'site/release.html', 'site/index.html', 'site/discovery.html', 'site/discovery-entry.js',
    'site/admissions.html', 'site/applications.html', 'site/desk.html',
    'site/board.html', 'site/compare.html', 'site/notices.html', 'site/data.js',
    'site/search.js', 'site/compare-data.js', 'site/admissions-data.js',
    'site/ui.css', 'site/templates/_nav.html.j2',
}


def allowed(name):
    """Match path components exactly; wildcards never cross a directory."""
    if not name or '\\' in name or ':' in name or name.startswith('/'):
        return False
    parts = name.split('/')
    if any(p in ('', '.', '..') for p in parts):
        return False
    if name in FIXED:
        return True
    return any(len(parts) == len(pattern.split('/')) and
               all(re.fullmatch(re.escape(pat).replace(r'\*', '[^/]*'), part)
                   for part, pat in zip(parts, pattern.split('/')))
               for pattern in PATTERNS)


def checked_path(root, path):
    if '..' in path.parts or not path.is_relative_to(root):
        raise ValueError(f'Path escapes release root: {path}')
    for parent in (path, *path.parents):
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError(f'Symlink or junction is not a release input: {path}')
        if parent == root:
            break
    if not path.resolve().is_relative_to(root):
        raise ValueError(f'Path escapes release root: {path}')
    if not path.is_file():
        raise ValueError(f'Missing release input: {path.relative_to(root)}')
    return path


def public_counts(root):
    def load(name):
        return yaml.load((root / name).read_text(encoding='utf-8-sig'),
                         Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))
    admissions = load('data/admissions.yaml')
    return {
        'professors': len(list((root / 'data/professors').glob('*/*/*.yaml'))),
        'schools': len(load('data/schools.yaml')['schools']),
        'units': len(list((root / 'sites').glob('*/*.yaml'))),
        'policies': len(admissions['policies']), 'sources': len(admissions['sources']),
        'checks': len(load('data/admissions_checks.json')),
        'entries': len(load('data/admissions_entries.yaml')['entries']),
        'notices': len(load('data/notices.json')['notices']),
    }


def collect(root):
    missing = sorted(name for name in FIXED | REQUIRED_SITE if not (root / name).is_file())
    if missing:
        raise ValueError('Missing required release files: ' + ', '.join(missing))
    paths = {root / name for name in FIXED}
    for pattern in PATTERNS:
        paths.update(root.glob(pattern))
    result = {}
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        if not allowed(name):
            raise ValueError(f'Not in release allowlist: {name}')
        checked_path(root, path)
        result[name] = path
    professor_pages = {
        f'{p.parent.parent.name}-{p.parent.name}-{p.stem}'
        for name, p in result.items() if name.startswith('data/professors/')
    }
    detail_pages = {p.stem for name, p in result.items() if name.startswith('site/p/')}
    if not professor_pages or professor_pages != detail_pages:
        raise ValueError('Public professor records and detail pages differ')
    return result


def build(root=ROOT):
    root = Path(root).resolve()
    paths = collect(root)
    version = (root / 'VERSION').read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('VERSION must be a numeric release version')
    release = json.loads((root / 'release.json').read_text(encoding='utf-8-sig'))
    if release.get('version') != version or release.get('edition') != 'local':
        raise ValueError('VERSION and release.json disagree')
    counts = public_counts(root)
    snapshot = json.loads((root / 'docs/DATA_SNAPSHOT.json').read_text(encoding='utf-8-sig'))
    expected = snapshot.get('counts', {})
    if not expected or any(key not in expected for key in counts):
        raise ValueError('DATA_SNAPSHOT.json must contain all public counts')
    if any(expected[key] != value for key, value in counts.items()):
        raise ValueError(f'Public counts differ from snapshot: actual={counts}, expected={expected}')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'],
                                        cwd=root, text=True).strip())
    manifest = {'version': version, 'edition': 'local', 'source_git_commit': commit,
                'source_worktree_dirty': dirty, 'counts': counts, 'files': {}}
    dist = root / 'dist'
    if dist.is_symlink() or (dist.exists() and dist.resolve() != root / 'dist'):
        raise ValueError('dist must be a real release directory')
    dist.mkdir(exist_ok=True)
    filename = f'mentor-assistant-v{version}-local.zip'
    output = dist / filename
    sidecar = dist / (filename + '.manifest.json')
    checksum = dist / (filename + '.sha256')
    for target in (output, sidecar, checksum):
        if target.is_symlink():
            raise ValueError(f'Release output cannot be a symlink: {target.name}')
    prefix = f'mentor-assistant-v{version}/'
    with tempfile.TemporaryDirectory(prefix='mentor-release-') as scratch:
        candidate = Path(scratch) / filename
        with zipfile.ZipFile(candidate, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in paths.items():
                content = checked_path(root, path).read_bytes()
                manifest['files'][name] = {'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
                archive.writestr(prefix + name, content)
            raw_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            archive.writestr(prefix + 'MANIFEST.json', raw_manifest)
        # Only the three explicitly named outputs from this script may be replaced.
        output.write_bytes(candidate.read_bytes())
        sidecar.write_bytes(raw_manifest)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        checksum.write_text(f'{digest}  {filename}\n', encoding='ascii')
    return {'zip': str(output), 'sha256': digest, 'size': output.stat().st_size,
            'manifest': str(sidecar), 'file_count': len(paths), 'version': version,
            'source_git_commit': commit, 'source_worktree_dirty': dirty, 'counts': counts}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        print(json.dumps(build(), ensure_ascii=True, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == '__main__':
    main()
