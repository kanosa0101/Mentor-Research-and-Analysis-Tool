import base64
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import serve_public
from crawler import online_materials


class OnlineMaterialsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        profiles = self.root / 'site' / 'p'
        profiles.mkdir(parents=True)
        self.mentor = 'bit-cs-danchun'
        (profiles / (self.mentor + '.html')).write_text('Public fixture', encoding='utf8')
        self.server = serve_public.create_server(self.root, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.a = self.account('applicant-a')
        self.b = self.account('applicant-b')

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, account, path, body=None, method='GET', extra=None):
        headers = {'Origin': self.base, 'Content-Type': 'application/json'}
        if account:
            headers.update(Cookie=account['cookie'], **{'X-CSRF-Token': account['csrf']})
        headers.update(extra or {})
        with requests.Session() as session:
            session.trust_env = False
            return session.request(method, self.base + path, json=body, headers=headers,
                                   timeout=30, allow_redirects=False)

    def account(self, username):
        response = self.request(None, '/api/auth/register',
                                {'username': username, 'password': 'Passphrase-for-testing-42'}, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        return {'cookie': response.headers['Set-Cookie'].split(';')[0],
                'csrf': response.json()['csrf_token']}

    def upload(self, account, project_id=None):
        body = {'filename': '申请简历.pdf', 'content_base64': base64.b64encode(b'%PDF-PRIVATE-CV').decode(),
                'kind': 'cv', 'mentor_ids': [self.mentor]}
        if project_id:
            body['project_ids'] = [project_id]
        response = self.request(account, '/api/materials/upload', body, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['material']

    def test_two_sessions_upload_download_and_eml_are_account_isolated(self):
        project = self.request(self.a, '/api/workflow/projects',
                               {'name': '我的申请', 'mentor_ids': [self.mentor]}, 'POST')
        self.assertEqual(project.status_code, 200, project.text)
        material = self.upload(self.a, project.json()['id'])
        download_path = '/api/materials/' + material['id'] + '/download'
        response = self.request(self.a, download_path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b'%PDF-PRIVATE-CV')
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.request(self.b, download_path).status_code, 404)
        self.assertEqual(self.request(None, download_path).status_code, 401)
        mine = self.request(self.a, '/api/workflow').json()
        other = self.request(self.b, '/api/workflow').json()
        self.assertEqual(other['materials'], {})
        self.assertEqual(other['projects'], {})
        target = next(iter(mine['targets']))
        draft = self.request(self.a, '/api/workflow/drafts',
                             {'target_id': target, 'recipient': 'mentor@example.edu',
                              'subject': '研究咨询', 'body': '希望了解研究机会。',
                              'basis': '已阅读公开研究方向', 'material_ids': [material['id']]}, 'POST')
        self.assertEqual(draft.status_code, 200, draft.text)
        draft_path = '/api/workflow/drafts/' + draft.json()['id'] + '/eml'
        eml = self.request(self.a, draft_path)
        self.assertEqual(eml.status_code, 200, eml.text)
        message = BytesParser(policy=policy.default).parsebytes(eml.content)
        attachment = next(message.iter_attachments())
        self.assertEqual(attachment.get_filename(), '申请简历.pdf')
        self.assertEqual(attachment.get_payload(decode=True), b'%PDF-PRIVATE-CV')
        self.assertEqual(self.request(self.b, draft_path).status_code, 404)
        self.assertEqual(self.request(None, draft_path).status_code, 401)
        self.assertEqual(self.request(self.a, '/api/materials/' + material['id'], {}, 'DELETE').status_code, 409)
        confirmed = self.request(self.a, '/api/workflow/drafts/' + draft.json()['id'] + '/confirm',
                                 {'sent': True, 'date': '2026-11-15'}, 'POST')
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(self.request(self.a, '/api/materials/' + material['id'], {}, 'DELETE').status_code, 409)
        self.assertEqual(self.request(self.b, '/api/workflow/materials/' + material['id'],
                                      {'title': 'other-user-edit'}, 'PATCH').status_code, 404)
        self.assertEqual(self.request(self.a, download_path).content, b'%PDF-PRIVATE-CV')

    def test_delete_requires_owner_and_csrf_and_releases_unreferenced_file(self):
        material = self.upload(self.a)
        path = '/api/materials/' + material['id']
        self.assertEqual(self.request(self.b, path, {}, 'DELETE').status_code, 404)
        self.assertEqual(self.request(None, path, {}, 'DELETE').status_code, 401)
        self.assertEqual(self.request(self.a, path, {}, 'DELETE', {'X-CSRF-Token': ''}).status_code, 403)
        self.assertTrue(Path(material['path']).exists())
        response = self.request(self.a, path, {}, 'DELETE')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['deleted'])
        self.assertFalse(Path(material['path']).exists())
        self.assertEqual(self.request(self.a, path + '/download').status_code, 404)
        self.assertEqual(self.request(self.a, '/api/workflow').json()['materials'], {})

    def test_restore_and_direct_file_paths_cannot_read_server_files(self):
        material = self.upload(self.a)
        backup = self.request(self.a, '/api/workflow/backup').json()
        secret = self.root / 'secret.txt'
        secret.write_text('SERVER-PRIVATE', encoding='utf8')
        path = '/api/workflow/materials/' + material['id']
        self.assertEqual(self.request(self.a, path, {'path': str(secret)}, 'PATCH').status_code, 400)
        self.assertEqual(self.request(self.a, '/api/workflow/materials',
                                      {'path': str(secret)}, 'POST').status_code, 400)
        self.assertEqual(self.request(self.a, '/api/workflow/scan',
                                      {'root': str(self.root)}, 'POST').status_code, 400)
        malicious = copy.deepcopy(backup)
        malicious['workflow']['materials'][material['id']]['path'] = str(secret)
        response = self.request(self.a, '/api/workflow/restore', malicious, 'POST')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn('SERVER-PRIVATE', response.text)
        response = self.request(self.b, '/api/workflow/restore', backup, 'POST')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.request(self.b, '/api/workflow').json()['materials'], {})
        self.assertEqual(secret.read_text(), 'SERVER-PRIVATE')

    def test_upload_requires_same_origin_csrf_and_valid_associations(self):
        body = {'filename': 'x.txt', 'content_base64': 'eA=='}
        for headers in [{'X-CSRF-Token': ''}, {'Origin': 'https://elsewhere.invalid'}]:
            response = self.request(self.a, '/api/materials/upload', body, 'POST', headers)
            self.assertEqual(response.status_code, 403, response.text)
        response = self.request(self.b, '/api/materials/upload',
                                {**body, 'project_ids': ['f' * 32]}, 'POST')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.request(self.b, '/api/workflow').json()['materials'], {})

    def test_missing_file_does_not_block_project_material_or_communication_work(self):
        project = self.request(self.a, '/api/workflow/projects',
                               {'name': '继续申请', 'mentor_ids': [self.mentor]}, 'POST').json()
        missing = self.upload(self.a, project['id'])
        healthy = self.upload(self.a, project['id'])
        Path(missing['path']).unlink()

        response = self.request(self.a, '/api/workflow')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['materials'][missing['id']]['missing'])
        self.assertFalse(response.json()['materials'][healthy['id']]['missing'])
        self.assertEqual(self.request(self.a, '/api/materials/' + healthy['id'] + '/download').content,
                         b'%PDF-PRIVATE-CV')
        self.assertEqual(self.request(self.a, '/api/materials/' + missing['id'] + '/download').status_code, 400)
        uploaded = self.upload(self.a, project['id'])
        self.assertNotEqual(uploaded['id'], missing['id'])
        response = self.request(self.a, '/api/workflow/materials/' + missing['id'],
                                {'notes': '需要补传'}, 'PATCH')
        self.assertEqual(response.status_code, 200, response.text)
        response = self.request(self.a, '/api/workflow/communications',
                                {'mentor_id': self.mentor, 'project_id': project['id'], 'kind': 'note',
                                 'date': '2026-11-16', 'subject': '继续记录沟通'}, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        backup = self.request(self.a, '/api/workflow/backup').json()
        self.assertTrue(backup['workflow']['materials'][missing['id']]['missing'])
        response = self.request(self.a, '/api/workflow/restore', backup, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['missing_materials'], 1)
        self.assertEqual(len(self.request(self.a, '/api/workflow').json()['communications']), 1)
        response = self.request(self.a, '/api/materials/' + missing['id'], {}, 'DELETE')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(missing['id'], self.request(self.a, '/api/workflow').json()['materials'])

    def test_restore_valid_backup_does_not_depend_on_corrupt_old_index(self):
        material = self.upload(self.a)
        backup = self.request(self.a, '/api/workflow/backup').json()
        user_root = Path(material['path']).parents[2]
        old_bytes = b'invalid: [workflow'
        (user_root / 'workflow.yaml').write_bytes(old_bytes)
        response = self.request(self.a, '/api/workflow/restore', backup, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['missing_materials'], 0)
        self.assertIn(material['id'], self.request(self.a, '/api/workflow').json()['materials'])
        self.assertEqual([p.read_bytes() for p in (user_root / 'backups').glob('workflow-*.yaml')], [old_bytes])

    def test_missing_historical_attachment_preserves_records_and_blocks_export(self):
        project = self.request(self.a, '/api/workflow/projects',
                               {'name': '历史材料', 'mentor_ids': [self.mentor]}, 'POST').json()
        material = self.upload(self.a, project['id'])
        target = next(iter(self.request(self.a, '/api/workflow').json()['targets']))
        draft = self.request(self.a, '/api/workflow/drafts',
                             {'target_id': target, 'recipient': 'mentor@example.edu', 'subject': '申请',
                              'body': '申请正文', 'basis': '研究资料', 'material_ids': [material['id']]}, 'POST').json()
        backup = self.request(self.a, '/api/workflow/backup').json()
        Path(material['path']).unlink()
        response = self.request(self.a, '/api/workflow/restore', backup, 'POST')
        self.assertEqual(response.status_code, 200, response.text)
        data = self.request(self.a, '/api/workflow').json()
        self.assertEqual(data['drafts'][draft['id']]['attachments'], draft['attachments'])
        self.assertTrue(data['materials'][material['id']]['missing'])
        self.assertEqual(self.request(self.a, '/api/workflow/drafts/' + draft['id'] + '/eml').status_code, 400)
        self.assertEqual(self.request(self.a, '/api/materials/' + material['id'], {}, 'DELETE').status_code, 409)

    def test_restore_path_check_and_save_are_serialized_with_material_delete(self):
        material = self.upload(self.a)
        backup = self.request(self.a, '/api/workflow/backup').json()
        checked, release = threading.Event(), threading.Event()
        original = online_materials.validate_storage_paths

        def pause_after_incoming_validation(data, user_root):
            original(data, user_root)
            # A first upload is stored as v1; GET backup projects it to v3.
            if data.get('version') == backup['version'] and material['id'] in data.get('materials', {}) and not checked.is_set():
                checked.set()
                self.assertTrue(release.wait(5), 'restore test release timed out')

        with patch.object(online_materials, 'validate_storage_paths', pause_after_incoming_validation):
            with ThreadPoolExecutor(max_workers=2) as pool:
                restored = pool.submit(self.request, self.a, '/api/workflow/restore', backup, 'POST')
                self.assertTrue(checked.wait(5), 'incoming backup was not checked')
                deleted = pool.submit(self.request, self.a, '/api/materials/' + material['id'], {}, 'DELETE')
                try:
                    with self.assertRaises(FutureTimeout):
                        deleted.result(timeout=0.2)
                finally:
                    release.set()
                response = restored.result(timeout=5)
                self.assertEqual(response.status_code, 200, response.text)
                response = deleted.result(timeout=5)
                self.assertEqual(response.status_code, 200, response.text)
        response = self.request(self.a, '/api/workflow')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['materials'], {})

    def test_slow_material_download_does_not_hold_other_accounts_workflow_lock(self):
        material = self.upload(self.a)
        response = self.assert_download_does_not_block('/api/materials/' + material['id'] + '/download',
                                                      'application/octet-stream')
        self.assertEqual(response.content, b'%PDF-PRIVATE-CV')

    def test_slow_eml_download_does_not_hold_other_accounts_workflow_lock(self):
        project = self.request(self.a, '/api/workflow/projects',
                               {'name': '申请邮件', 'mentor_ids': [self.mentor]}, 'POST').json()
        material = self.upload(self.a, project['id'])
        target = next(iter(self.request(self.a, '/api/workflow').json()['targets']))
        draft = self.request(self.a, '/api/workflow/drafts',
                             {'target_id': target, 'recipient': 'mentor@example.edu', 'subject': '申请',
                              'body': '申请正文', 'basis': '已核对研究资料', 'material_ids': [material['id']]}, 'POST')
        self.assertEqual(draft.status_code, 200, draft.text)
        response = self.assert_download_does_not_block('/api/workflow/drafts/' + draft.json()['id'] + '/eml',
                                                      'message/rfc822')
        message = BytesParser(policy=policy.default).parsebytes(response.content)
        self.assertEqual(next(message.iter_attachments()).get_payload(decode=True), b'%PDF-PRIVATE-CV')

    def assert_download_does_not_block(self, path, expected_type):
        sending, release = threading.Event(), threading.Event()
        original = serve_public.Handler.reply

        def pause_network_write(handler, status, body=b'', content_type='application/json; charset=utf-8', headers=None):
            if content_type == expected_type:
                sending.set()
                self.assertTrue(release.wait(6), 'download test release timed out')
            return original(handler, status, body, content_type, headers)

        with patch.object(serve_public.Handler, 'reply', pause_network_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                download = pool.submit(self.request, self.a, path)
                self.assertTrue(sending.wait(5), 'material download did not begin')
                try:
                    other = pool.submit(self.request, self.b, '/api/workflow').result(timeout=3)
                    self.assertEqual(other.status_code, 200, other.text)
                finally:
                    release.set()
                response = download.result(timeout=5)
                self.assertEqual(response.status_code, 200, response.text)
                return response


if __name__ == '__main__':
    unittest.main()
