import hashlib
import unittest
from email import policy
from email.parser import BytesParser
from urllib.error import HTTPError
from urllib.request import Request

import test_applications
from crawler.workflow_util import empty_workflow, update_entry


class ContactFlowTests(unittest.TestCase):
    setUp = test_applications.ApplicationTests.setUp
    close_server = test_applications.ApplicationTests.close_server
    request = test_applications.ApplicationTests.request
    create = test_applications.ApplicationTests.create
    project = test_applications.ApplicationTests.project

    def target(self, project=None):
        project = project or self.project(2027)
        return self.create('targets', {'project_id': project['id'], 'mentor_id': self.pid,
                                       'reason': '已核对官网方向，与我的项目相关', 'priority': 'high'})

    def draft(self, target=None, materials=None):
        target = target or self.target()
        return self.create('drafts', {'target_id': target['id'], 'recipient': 'prof@example.edu',
                                     'subject': '2027 硕士申请咨询', 'body': '老师您好，这是我的真实研究经历。',
                                     'basis': '官网研究方向和我的项目经历', 'material_ids': materials or []})

    def sent(self, draft):
        return self.request('/api/workflow/drafts/' + draft['id'] + '/confirm',
                            {'sent': True, 'date': '2026-10-14'}, 'POST')

    def test_read_upgrades_v1_in_memory_and_keeps_file_unchanged(self):
        core, project = update_entry(empty_workflow(), 'projects', {'name': '旧项目', 'mentor_ids': [self.pid]}, {self.pid})
        self.serve.save_outreach(core, self.outreach.with_name('workflow.yaml'))
        before = self.outreach.with_name('workflow.yaml').read_bytes()
        code, data = self.request('/api/workflow')
        self.assertEqual(code, 200)
        self.assertEqual(data['version'], 3)
        self.assertEqual(len(data['targets']), 1)
        self.assertEqual(next(iter(data['targets'].values()))['project_id'], project['id'])
        self.assertEqual(before, self.outreach.with_name('workflow.yaml').read_bytes())
        self.assertEqual(next(iter(data['targets'])), next(iter(self.request('/api/workflow')[1]['targets'])))

    def test_target_pair_is_unique_and_separate_across_years(self):
        project = self.project(2027)
        a = self.target(project)
        again = self.target(project)
        b = self.target(self.project(2028))
        self.assertEqual(a['id'], again['id'])
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(self.request('/api/workflow/targets/' + a['id'], {'stage': 'closed'}, 'PATCH')[0], 200)
        self.assertEqual(self.request('/api/workflow')[1]['targets'][b['id']]['stage'], 'research')
        self.assertFalse(self.outreach.exists())

    def test_invalid_target_and_draft_references_do_not_write(self):
        self.project()
        before = self.outreach.with_name('workflow.yaml').read_bytes()
        for kind, body in [('targets', {'project_id': 'unknown', 'mentor_id': self.pid}),
                           ('targets', {'project_id': 'unknown', 'mentor_id': 'unknown'}),
                           ('drafts', {'target_id': 'unknown'}), ('targets', [])]:
            self.assertEqual(self.request('/api/workflow/' + kind, body, 'POST')[0], 400)
        self.assertEqual(before, self.outreach.with_name('workflow.yaml').read_bytes())

    def test_incomplete_draft_is_saved_but_cannot_confirm_sent(self):
        target = self.target()
        draft = self.create('drafts', {'target_id': target['id']})
        self.assertEqual(self.sent(draft)[0], 400)
        data = self.request('/api/workflow')[1]
        self.assertEqual(data['targets'][target['id']]['stage'], 'preparing')
        self.assertEqual(len(data['communications']), 0)

    def test_confirm_requires_explicit_sent_and_is_idempotent(self):
        draft = self.draft()
        self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'] + '/confirm', {'date': '2026-10-14'}, 'POST')[0], 400)
        code, event = self.sent(draft)
        self.assertEqual(code, 200, event)
        self.assertEqual(self.sent(draft)[1]['id'], event['id'])
        data = self.request('/api/workflow')[1]
        self.assertEqual(len(data['communications']), 1)
        self.assertEqual(data['targets'][draft['target_id']]['stage'], 'waiting')
        self.assertEqual(event['recipient'], 'prof@example.edu')
        self.assertEqual(event['content'], draft['body'])
        self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'], {'body': '不应修改已发版本'}, 'PATCH')[0], 400)

    def test_eml_contains_attachment_and_does_not_count_as_sent(self):
        file = self.root / 'cv.txt'
        file.write_bytes(b'original CV')
        material = self.create('materials', {'path': str(file)})
        draft = self.draft(materials=[material['id']])
        try:
            with self.http.open(self.base + '/api/workflow/drafts/' + draft['id'] + '/eml') as response:
                self.assertEqual(response.status, 200)
                mail = BytesParser(policy=policy.default).parsebytes(response.read())
        except HTTPError as error:
            error.close()
            self.fail('缺少 EML 导出接口')
        self.assertEqual(mail['To'], 'prof@example.edu')
        self.assertEqual(str(mail['Subject']), draft['subject'])
        attachments = list(mail.iter_attachments())
        self.assertEqual(attachments[0].get_payload(decode=True), b'original CV')
        self.assertEqual(len(self.request('/api/workflow')[1]['communications']), 0)

    def test_changed_or_missing_attachment_blocks_export_and_confirmation(self):
        file = self.root / 'cv.txt'
        file.write_bytes(b'first version')
        material = self.create('materials', {'path': str(file)})
        draft = self.draft(materials=[material['id']])
        file.write_bytes(b'changed version')
        self.assertEqual(self.sent(draft)[0], 400)
        self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'] + '/eml')[0], 400)
        file.unlink()
        self.assertEqual(self.sent(draft)[0], 400)
        self.assertEqual(len(self.request('/api/workflow')[1]['communications']), 0)

    def test_sent_attachment_snapshot_is_immutable(self):
        file = self.root / 'cv.txt'
        file.write_bytes(b'original')
        material = self.create('materials', {'path': str(file)})
        draft = self.draft(materials=[material['id']])
        code, event = self.sent(draft)
        self.assertEqual(code, 200, event)
        snapshot = event['attachments'][0]
        self.assertEqual(snapshot['size'], len(b'original'))
        self.assertEqual(len(snapshot['sha256']), 64)
        file.write_bytes(b'replacement')
        self.request('/api/workflow/materials/' + material['id'], {'title': '新版简历'}, 'PATCH')
        self.assertEqual(self.request('/api/workflow')[1]['communications'][event['id']]['attachments'][0], snapshot)

    def test_reply_and_task_are_atomic_and_keep_context(self):
        draft = self.draft()
        self.sent(draft)
        target_id = draft['target_id']
        before = self.outreach.with_name('workflow.yaml').read_bytes()
        bad = {'content': '请补充简历', 'date': '2026-10-14', 'stage': 'materials',
               'task': {'title': '补简历', 'due_date': '2026-02-30'}}
        endpoint = '/api/workflow/targets/' + target_id + '/reply'
        self.assertEqual(self.request(endpoint, bad, 'POST')[0], 400)
        self.assertEqual(before, self.outreach.with_name('workflow.yaml').read_bytes())
        bad['task']['due_date'] = '2026-10-20'
        code, result = self.request(endpoint, bad, 'POST')
        self.assertEqual(code, 200, result)
        data = self.request('/api/workflow')[1]
        self.assertEqual(data['targets'][target_id]['stage'], 'materials')
        self.assertEqual(len(data['communications']), 2)
        task = next(iter(data['reminders'].values()))
        target = data['targets'][target_id]
        self.assertEqual((task['project_id'], task['mentor_id']), (target['project_id'], target['mentor_id']))

    def test_v1_backup_restore_and_v2_roundtrip(self):
        core, _ = update_entry(empty_workflow(), 'projects', {'name': '旧项目', 'mentor_ids': [self.pid]}, {self.pid})
        self.assertEqual(self.request('/api/workflow/restore', {'version': 1, 'workflow': core}, 'POST')[0], 200)
        self.draft()
        backup = self.request('/api/workflow/backup')[1]
        self.assertEqual(backup['version'], 3)
        before = self.outreach.with_name('workflow.yaml').read_bytes()
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        self.assertEqual(before, self.outreach.with_name('workflow.yaml').read_bytes())

    def test_export_is_same_origin_only(self):
        draft = self.draft()
        req = Request(self.base + '/api/workflow/drafts/' + draft['id'] + '/eml', headers={'Origin': 'https://evil.example'})
        with self.assertRaises(HTTPError) as err:
            self.http.open(req)
        self.assertEqual(err.exception.code, 403)
        err.exception.close()

    def test_cross_site_navigation_cannot_download_private_eml(self):
        draft = self.draft()
        req = Request(self.base + '/api/workflow/drafts/' + draft['id'] + '/eml',
                      headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Referer': 'https://evil.example/'})
        with self.assertRaises(HTTPError) as err:
            self.http.open(req)
        self.assertEqual(err.exception.code, 403)
        err.exception.close()

    def test_restored_draft_cannot_read_unregistered_file(self):
        registered = self.root / 'registered.txt'
        registered.write_bytes(b'selected')
        other = self.root / 'unregistered.txt'
        other.write_bytes(b'not selected')
        material = self.create('materials', {'path': str(registered)})
        draft = self.draft(materials=[material['id']])
        backup = self.request('/api/workflow/backup')[1]
        snapshot = backup['workflow']['drafts'][draft['id']]['attachments'][0]
        snapshot.update(path=str(other.resolve()), size=other.stat().st_size,
                        sha256=hashlib.sha256(other.read_bytes()).hexdigest())
        before = self.outreach.with_name('workflow.yaml').read_bytes()
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 400)
        self.assertEqual(before, self.outreach.with_name('workflow.yaml').read_bytes())


if __name__ == '__main__':
    unittest.main()
