import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler import contact_util as contact
from crawler import online_materials as storage
from crawler import project_util as projects
from crawler.workflow_util import empty_workflow


class OnlineMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.user = self.root / 'a'
        self.other = self.root / 'b'
        self.known = {'school-cs-mentor'}
        self.context = {'units': {}, 'sources': {}, 'policies': []}
        self.data = projects.upgrade(empty_workflow(), self.known, self.context)

    def payload(self, raw=b'%PDF-test', filename='个人简历.pdf', **extra):
        return dict(filename=filename, content_base64=base64.b64encode(raw).decode(), **extra)

    def upload(self, **extra):
        return storage.add_upload(self.user, self.data, self.payload(**extra), self.known)

    def test_upload_download_preserves_bytes_and_unicode_name(self):
        data, record = self.upload()
        self.assertEqual(self.data['materials'], {})
        self.assertEqual(record['title'], '个人简历.pdf')
        self.assertEqual(data['materials'][record['id']], record)
        path, filename = storage.download(self.user, data, record['id'])
        self.assertEqual(path.read_bytes(), b'%PDF-test')
        self.assertEqual(filename, '个人简历.pdf')
        storage.validate_storage_paths(data, self.user)
        headers = storage.download_headers(filename)
        self.assertEqual(headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("filename*=UTF-8''%", headers['Content-Disposition'])
        self.assertTrue(headers['Content-Disposition'].startswith('attachment;'))

    def test_two_accounts_cannot_download_or_restore_each_others_paths(self):
        data, record = self.upload()
        with self.assertRaises(KeyError):
            storage.download(self.other, self.data, record['id'])
        with self.assertRaises(ValueError):
            storage.download(self.other, data, record['id'])
        with self.assertRaises(ValueError):
            storage.validate_storage_paths(data, self.other)

    def test_filenames_and_client_paths_rejected_before_writing(self):
        for name in ['../secret', '/tmp/secret', 'C:\\secret', '.', '..', 'x\r\nHeader', 'a/b.pdf',
                     'a\\b.pdf', 'x:stream', 'con.pdf', ' a.pdf', 'a.pdf.', 'x' * 201]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.upload(filename=name)
        with self.assertRaises(ValueError):
            self.upload(path='/etc/passwd')
        self.assertFalse(self.user.exists())

    def test_invalid_refs_cleanup_uploaded_bytes(self):
        with self.assertRaises(ValueError):
            self.upload(project_ids=['f' * 32])
        self.assertEqual(list((self.user / 'materials').iterdir()), [])

    def test_file_and_account_limits_do_not_overwrite_existing_upload(self):
        with patch.object(storage, 'MAX_FILE_BYTES', 8):
            with self.assertRaises(ValueError):
                self.upload(raw=b'123456789')
        data, record = self.upload(raw=b'12345678')
        with patch.object(storage, 'MAX_USER_BYTES', 12):
            with self.assertRaises(ValueError):
                storage.add_upload(self.user, data, self.payload(raw=b'12345'), self.known)
        self.assertEqual(Path(record['path']).read_bytes(), b'12345678')
        self.assertEqual(len(list((self.user / 'materials').iterdir())), 1)

    def test_invalid_encoding_and_empty_file(self):
        for value in ['!!!', 'é', '', 3, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                storage.add_upload(self.user, self.data,
                                   {'filename': 'cv.pdf', 'content_base64': value}, self.known)

    def test_draft_and_historical_paths_are_checked_before_read(self):
        data, record = self.upload()
        for kind in ('drafts', 'communications', 'material_tasks'):
            malicious = copy.deepcopy(data)
            malicious[kind] = {'x': {'attachments': [{'path': str(self.root / 'secret.txt')}]}}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                storage.validate_storage_paths(malicious, self.user)
        malicious = copy.deepcopy(data)
        malicious['materials'][record['id']]['path'] = str(self.user / 'workflow.yaml')
        with self.assertRaises(ValueError):
            storage.validate_storage_paths(malicious, self.user)

    def test_upload_preserves_material_task_wrapper_and_attachment_snapshot(self):
        self.data.update(version=4, material_tasks={})
        data, record = self.upload()
        self.assertEqual(data['version'], 4)
        self.assertEqual(data['material_tasks'], {})
        snapshot = contact.snapshots(data, [record['id']])[0]
        self.assertEqual(snapshot['path'], record['path'])
        self.assertEqual(snapshot['size'], len(b'%PDF-test'))
        self.assertEqual(len(snapshot['sha256']), 64)

    def test_rollback_removes_only_new_upload(self):
        data, first = self.upload()
        data, second = storage.add_upload(self.user, data, self.payload(), self.known)
        storage.rollback_upload(self.user, second)
        self.assertFalse(Path(second['path']).exists())
        self.assertTrue(Path(first['path']).exists())
        with self.assertRaises(ValueError):
            storage.rollback_upload(self.other, first)

    def test_symlink_outside_storage_is_rejected(self):
        data, record = self.upload()
        path = Path(record['path'])
        path.unlink()
        outside = self.root / 'private.txt'
        outside.write_bytes(b'private')
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest('Creating symlinks is unavailable on this platform')
        with self.assertRaises(ValueError):
            storage.download(self.user, data, record['id'])
        self.assertEqual(outside.read_bytes(), b'private')

    def test_unreferenced_delete_frees_storage_and_preserves_other_upload(self):
        data, first = self.upload()
        data, second = storage.add_upload(self.user, data, self.payload(), self.known)
        saved = []
        result = storage.delete_upload(self.user, data, first['id'], lambda value: saved.append(value))
        self.assertTrue(result['deleted'])
        self.assertNotIn(first['id'], saved[-1]['materials'])
        self.assertFalse(Path(first['path']).exists())
        self.assertTrue(Path(second['path']).exists())
        self.assertIn(first['id'], data['materials'])

    def test_referenced_material_cannot_be_deleted(self):
        data, record = self.upload()
        for kind in ('drafts', 'communications', 'material_tasks'):
            used = copy.deepcopy(data)
            used[kind] = {'example': {'material_ids': [record['id']]}}
            with self.subTest(kind=kind), self.assertRaises(storage.Conflict):
                storage.delete_upload(self.user, used, record['id'], lambda value: self.fail('must not save'))
        self.assertTrue(Path(record['path']).exists())

    def test_delete_save_failure_and_file_failure_restore_original(self):
        data, record = self.upload()
        path = Path(record['path'])
        with self.assertRaises(OSError):
            storage.delete_upload(self.user, data, record['id'],
                                  lambda value: (_ for _ in ()).throw(OSError('write failed')))
        self.assertEqual(path.read_bytes(), b'%PDF-test')
        saved = []
        original_unlink = Path.unlink

        def fail_pending(item, *args, **kwargs):
            if item.name == storage.PENDING_DELETE:
                raise OSError('delete failed')
            return original_unlink(item, *args, **kwargs)

        with patch.object(Path, 'unlink', fail_pending), self.assertRaises(OSError):
            storage.delete_upload(self.user, data, record['id'], lambda value: saved.append(value))
        self.assertEqual(saved[-1], data)
        self.assertEqual(path.read_bytes(), b'%PDF-test')
        self.assertFalse(path.with_name(storage.PENDING_DELETE).exists())

    def test_interrupted_delete_quarantine_reclaimed_before_upload_quota(self):
        data, record = self.upload(raw=b'12345678')
        path = Path(record['path'])
        del data['materials'][record['id']]
        path.rename(path.with_name(storage.PENDING_DELETE))
        with patch.object(storage, 'MAX_USER_BYTES', 8):
            updated, new_record = storage.add_upload(self.user, data, self.payload(raw=b'abcdefgh'), self.known)
        self.assertFalse(path.parent.exists())
        self.assertEqual(Path(new_record['path']).read_bytes(), b'abcdefgh')


if __name__ == '__main__':
    unittest.main()
