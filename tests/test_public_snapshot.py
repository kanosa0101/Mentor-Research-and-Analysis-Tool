import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup
from crawler import public_snapshot as snapshot, public_update
from crawler.model import Professor


class SnapshotTests(unittest.TestCase):
    def setup_root(self, root):
        (root/'VERSION').write_text('1.5.0')
        for name in snapshot.FIXED | {'data/professors/test/cs/teacher.yaml'}:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
        (root/'data/workflow.yaml').write_text('private')
        (root/'data/opportunity_feed.json').write_text('private configuration')

    def test_complete_snapshot_contains_no_private_records_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.setup_root(root)
            first=snapshot.build(root);second=snapshot.build(root)
            self.assertEqual(first,second)
            archive=root/'cache/public_snapshots'/f"{first['id']}.zip"
            manifest=snapshot.unpack(archive,root/'expanded',first,'1.5.0')
            self.assertNotIn('data/workflow.yaml',manifest['files'])
            self.assertNotIn('data/opportunity_feed.json',manifest['files'])
            self.assertEqual((root/'data/workflow.yaml').read_text(),'private')

    def test_bad_hash_and_client_version_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.setup_root(root);d=snapshot.build(root)
            archive=root/'cache/public_snapshots'/f"{d['id']}.zip"
            with self.assertRaises(ValueError):snapshot.unpack(archive,root/'bad',d,'1.4.0')
            with self.assertRaises(ValueError):snapshot.unpack(archive,root/'bad',dict(d,sha256='0'*64),'1.5.0')
            self.assertFalse((root/'bad').exists())

    def test_private_and_traversal_paths_are_not_allowed(self):
        self.assertTrue(snapshot.allowed('data/professors/tsinghua/cs/yangjiahai（校内兼职）.yaml'))
        for name in ('../data/workflow.yaml','data/workflow.yaml','data/letters/a.txt',
                     'data/professors/../../student.yaml','sites/a/b/c.yaml','/data/schools.yaml'):
            self.assertFalse(snapshot.allowed(name),name)

    def test_incomplete_archive_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('MANIFEST.json',json.dumps({'files':{}}))
            descriptor={'schema':1,'client_version':'1.5.0','sha256':snapshot.digest(archive.read_bytes())}
            with self.assertRaises(ValueError):snapshot.unpack(archive,root/'expanded',descriptor,'1.5.0')

    def test_apply_failure_restores_old_public_files_and_keeps_private(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'root';stage=Path(folder)/'stage';backup=Path(folder)/'backup'
            for base,value in ((root,'old'),(stage,'new')):
                (base/'data').mkdir(parents=True)
                for name in ('admissions.yaml','notices.json'):(base/'data'/name).write_text(value)
            (root/'data/workflow.yaml').write_text('private')
            original=public_update.os.replace
            def replace(source,target):
                if Path(source)==stage/'data/notices.json':raise OSError('simulated interruption')
                return original(source,target)
            with patch.object(public_update.os,'replace',side_effect=replace),self.assertRaises(OSError):
                public_update.apply_stage(root,stage,backup,['data/admissions.yaml','data/notices.json'])
            self.assertEqual((root/'data/admissions.yaml').read_text(),'old')
            self.assertEqual((root/'data/notices.json').read_text(),'old')
            self.assertEqual((root/'data/workflow.yaml').read_text(),'private')

    def test_newer_remote_version_does_not_start_install(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'VERSION').write_text('1.5.0')
            with patch.object(public_update,'check',return_value={'id':'a'*64,'client_version':'1.6.0'}):
                with self.assertRaisesRegex(ValueError,'升级'):public_update.update(root,'a'*64)
            self.assertFalse((root/'cache/public_updates').exists())


class PublicUpdateStageTests(unittest.TestCase):
    dependencies = ('discovery-core.js', 'discovery.js', 'browser-library-core.js', 'browser-library.js', 'ui.css', 'account-session.js', 'cloud-library.js',
                    'admissions-core.js', 'material-actions.js', 'opportunities-core.js', 'workflow.js')

    def fixture(self, folder, invalid=False):
        source = Path(__file__).resolve().parents[1]
        remote = Path(folder) / 'remote'; remote.mkdir()
        content = {
            'data/schools.yaml': {'schools': [{'id': 'test', 'name': '更新后的公共目录大学'}]},
            'data/admissions.yaml': {'version': 1, 'sources': {}, 'policies': [{'broken': True}] if invalid else []},
            'data/admissions_entries.yaml': {'version': 1, 'entries': []},
            'data/admissions_checks.json': {}, 'data/notices.json': {'notices': [], 'sources': {}},
            'data/opportunities.json': {'version': 1, 'checked_at': '2026-11-15', 'coverage_note': 'stage fixture', 'opportunities': []},
            'sites/notices.yaml': {'targets': []}, 'sites/opportunities.yaml': {'sources': []},
            'sites/test/cs.yaml': {'school': 'test', 'dept': 'cs', 'dept_name': '计算机学院'},
            'data/professors/test/cs/example.yaml': Professor(slug='example', name='测试导师', school='test', dept='cs', detail_url='https://example.edu/mentor').model_dump(mode='json'),
        }
        for name, value in content.items():
            path = remote / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        shutil.copy2(source / 'VERSION', remote / 'VERSION')
        descriptor = snapshot.build(remote)
        archive = remote / 'cache/public_snapshots' / (descriptor['id'] + '.zip')
        client = Path(folder) / 'client'; client.mkdir()
        for name in ('data', 'sites'):
            shutil.copytree(remote / name, client / name)
        (client / 'data/schools.yaml').write_text('schools: [{id: test, name: old-school}]', encoding='utf-8')
        (client / 'data/workflow.yaml').write_text('private-sentinel', encoding='utf-8')
        (client / 'data/opportunity_feed.json').write_text(json.dumps({'notification_origin': 'https://example.edu'}), encoding='utf-8')
        shutil.copytree(source / 'crawler', client / 'crawler', ignore=shutil.ignore_patterns('__pycache__'))
        (client / 'scripts').mkdir()
        for script in (source / 'scripts').glob('*.py'):
            shutil.copy2(script, client / 'scripts' / script.name)
        shutil.copytree(source / 'site/templates', client / 'site/templates')
        for name in self.dependencies:
            shutil.copy2(source / 'site' / name, client / 'site' / name)
        for name in ('VERSION', 'release.json'):
            shutil.copy2(source / name, client / name)
        (client / 'site/discovery.html').write_text('old-public-page', encoding='utf-8')
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [archive.read_bytes()]
        return client, descriptor, response

    def test_actual_staged_rebuild_installs_inline_page_and_preserves_private_and_client_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root, descriptor, response = self.fixture(folder)
            original_sources = {name: (root / 'site' / name).read_bytes() for name in self.dependencies}
            with patch.object(public_update, 'check', return_value=descriptor), patch.object(public_update.requests, 'get', return_value=response):
                result = public_update.update(root, descriptor['id'])
            self.assertTrue(result['private_data_unchanged'])
            html = (root / 'site/discovery.html').read_text(encoding='utf-8')
            self.assertIn('更新后的公共目录大学', html)
            page = BeautifulSoup(html, 'html.parser')
            self.assertFalse(page.select('link[rel=stylesheet]'))
            self.assertEqual({node['src'].split('?')[0] for node in page.select('script[src]')},
                             {'account-session.js', 'cloud-library.js'})
            self.assertEqual((root / 'data/workflow.yaml').read_text(), 'private-sentinel')
            self.assertEqual({name: (root / 'site' / name).read_bytes() for name in self.dependencies}, original_sources)
            self.assertEqual(json.loads((root / 'cache/public-data-installed.json').read_text())['id'], descriptor['id'])
            self.assertEqual((Path(result['backup']) / 'site/discovery.html').read_text(), 'old-public-page')

    def test_actual_build_failure_still_preserves_old_public_and_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root, descriptor, response = self.fixture(folder, invalid=True)
            original = {name: (root / name).read_bytes() for name in ('data/schools.yaml', 'data/workflow.yaml', 'site/discovery.html')}
            with patch.object(public_update, 'check', return_value=descriptor), patch.object(public_update.requests, 'get', return_value=response):
                with self.assertRaisesRegex(ValueError, '原资料未替换'):
                    public_update.update(root, descriptor['id'])
            self.assertEqual({name: (root / name).read_bytes() for name in original}, original)
            self.assertFalse((root / 'cache/public-data-installed.json').exists())
