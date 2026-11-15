import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from crawler import public_snapshot as snapshot, public_update


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
