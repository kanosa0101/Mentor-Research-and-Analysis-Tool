"""Release privacy and manifest contracts using isolated public input fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('package_release', Path(__file__).resolve().parents[1] / 'scripts/package_release.py')
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


class PackagingTests(unittest.TestCase):
    def test_reject_private_paths_and_path_escape(self):
        for name in ['data/outreach.yaml', 'data/student.yaml', 'data/student_sop.md',
                     'data/workflow.yaml', 'data/discovery.yaml', 'data/letters/a.md',
                     'cache/ai/key.json', 'sources/a.json', '.git/config', '../README.md',
                     '/README.md', 'site/../data/outreach.yaml', 'site/backups/x.html',
                     'crawler/__pycache__/x.pyc', r'site\data.js', 'C:/README.md']:
            with self.subTest(name=name):
                self.assertFalse(package_release.allowed(name))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'release'
            root.mkdir()
            outside = Path(directory) / 'README.md'
            outside.write_text('private', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                package_release.checked_path(root, outside)

    def test_allow_only_reviewed_public_patterns(self):
        for name in ['VERSION', 'release.json', '启动应用.cmd', 'README.md', 'docs/INDEX.md',
                     'docs/DATA_SNAPSHOT.json', 'scripts/serve.py', 'scripts/package_release.py',
                     'crawler/model.py', 'sites/buaa/cs.yaml', 'sites/notices.yaml', 'sites/buaa/buaa_cs.py',
                     'site/release.html', 'site/data.js', 'site/ui.css', 'site/p/x.html',
                     'site/templates/_nav.html.j2', 'data/professors/buaa/cs/a.yaml',
                     'data/admissions_checks.json']:
            with self.subTest(name=name):
                self.assertTrue(package_release.allowed(name))
        for name in ['DELIVERY_OLD.md', 'docs/private.md', 'scripts/ai_enrich.py',
                     'data/changes/a.jsonl',
                     'data/admissions_fragments/a.yaml', 'data/professors/a.yaml', 'site/x.txt']:
            self.assertFalse(package_release.allowed(name), name)

    def test_missing_release_documents_fail_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Missing required release files'):
                package_release.build(root)
            self.assertFalse((root / 'dist').exists())

    def test_symlink_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'real.txt'
            target.write_text('private', encoding='utf-8')
            link = root / 'README.md'
            try:
                link.symlink_to(target)
            except OSError:
                # Windows may lack symlink creation privileges; still verify rejection.
                with patch.object(Path, 'is_symlink', return_value=True):
                    with self.assertRaisesRegex(ValueError, 'Symlink'):
                        package_release.checked_path(root, link)
                return
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                package_release.checked_path(root, link)

    def test_manifest_hashes_and_archive_exclusion_with_private_files_present(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = package_release.FIXED | package_release.REQUIRED_SITE | {
                'crawler/model.py', 'sites/demo/cs.yaml',
                'data/professors/demo/cs/person.yaml', 'site/p/demo-cs-person.html'}
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('public fixture', encoding='utf-8')
            fixtures = {
                'VERSION': '1.0.0', 'release.json': json.dumps({'version':'1.0.0','edition':'local'}),
                'data/schools.yaml': 'schools: [{id: demo, name: Demo}]',
                'data/admissions.yaml': 'sources: {}\npolicies: []',
                'data/admissions_entries.yaml': 'version: 1\nentries: []',
                'data/admissions_checks.json': '{}', 'data/notices.json': '{"notices": []}',
            }
            for name, content in fixtures.items():
                (root / name).write_text(content, encoding='utf-8')
            counts = package_release.public_counts(root)
            (root / 'docs/DATA_SNAPSHOT.json').write_text(json.dumps({'counts':counts}), encoding='utf-8')
            for name in ['data/outreach.yaml','data/student.yaml','data/student_sop.md',
                         'data/workflow.yaml','data/discovery.yaml','sources/private.json','cache/ai/private.json']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('PRIVATE_MARKER_12345', encoding='utf-8')
            with patch.object(package_release.subprocess, 'check_output', side_effect=['a'*40, '']):
                result = package_release.build(root)
            with zipfile.ZipFile(result['zip']) as archive:
                prefix = 'mentor-assistant-v1.0.0/'
                manifest = json.loads(archive.read(prefix + 'MANIFEST.json'))
                self.assertEqual(manifest['source_git_commit'], 'a'*40)
                self.assertEqual(set(archive.namelist()), {prefix + n for n in names} | {prefix + 'MANIFEST.json'})
                self.assertEqual(set(manifest['files']), names)
                for name, metadata in manifest['files'].items():
                    raw = archive.read(prefix + name)
                    self.assertEqual(metadata, {'size':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()})
                    self.assertNotIn(b'PRIVATE_MARKER_12345', raw)
            self.assertEqual(json.loads(Path(result['manifest']).read_text(encoding='utf-8')), manifest)
            self.assertEqual(result['sha256'], hashlib.sha256(Path(result['zip']).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
