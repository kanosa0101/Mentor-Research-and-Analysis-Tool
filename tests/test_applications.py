import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch

import test_workflow


class ApplicationTests(unittest.TestCase):
    setUp = test_workflow.WorkflowTests.setUp
    close_server = test_workflow.WorkflowTests.close_server
    request = test_workflow.WorkflowTests.request

    def create(self, kind, body):
        code, result = self.request('/api/workflow/' + kind, body, 'POST')
        self.assertEqual(code, 200, result)
        return result

    def project(self, year=None):
        return self.create('projects', {'name': '夏令营', 'school': '测试学校', 'college': '计算机',
                                      'application_type': '夏令营', 'year': year, 'mentor_ids': [self.pid]})

    def test_empty_workspace_is_independent_and_not_created_on_read(self):
        code, data = self.request('/api/workflow')
        self.assertEqual(code, 200)
        self.assertEqual(data, {'version': 2, 'projects': {}, 'materials': {}, 'communications': {}, 'reminders': {}, 'targets': {}, 'drafts': {}})
        self.assertFalse((self.outreach.parent / 'workflow.yaml').exists())

    def test_projects_keep_same_mentor_across_years_and_unknown_year(self):
        a, b = self.project(2027), self.project()
        self.assertNotEqual(a['id'], b['id'])
        self.assertIsNone(b['year'])
        self.assertEqual(self.request('/api/workflow/projects/' + a['id'], {'status': 'submitted'}, 'PATCH')[0], 200)
        data = self.request('/api/workflow')[1]
        self.assertEqual(data['projects'][b['id']]['status'], 'planned')
        self.assertFalse(self.outreach.exists())

    def test_invalid_project_payloads_reject_without_write(self):
        for body in [[], {'name': ''}, {'name': 'x', 'mentor_ids': ['unknown']},
                     {'name': 'x', 'year': True}, {'name': 'x', 'year': '2027'}, {'name': 'x', 'extra': 'bad'}]:
            self.assertEqual(self.request('/api/workflow/projects', body, 'POST')[0], 400)
        self.assertFalse((self.outreach.parent / 'workflow.yaml').exists())

    def test_scan_preserves_manual_associations_and_missing_files(self):
        project = self.project()
        folder = self.root / 'materials'
        folder.mkdir()
        material = folder / '同名导师草稿.md'
        material.write_text('私人草稿', encoding='utf-8')
        code, result = self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        self.assertEqual(code, 200, result)
        data = self.request('/api/workflow')[1]
        mid, entry = next(iter(data['materials'].items()))
        self.assertEqual(entry['mentor_ids'], [])
        self.assertEqual(entry['project_ids'], [])
        patch = {'title': '人工分类', 'kind': 'letter', 'mentor_ids': [self.pid], 'project_ids': [project['id']]}
        self.assertEqual(self.request('/api/workflow/materials/' + mid, patch, 'PATCH')[0], 200)
        material.write_text('变更后的草稿', encoding='utf-8')
        self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        entry = self.request('/api/workflow')[1]['materials'][mid]
        self.assertEqual(entry['title'], '人工分类')
        self.assertEqual(entry['project_ids'], [project['id']])
        self.assertEqual(entry['size'], material.stat().st_size)
        material.unlink()
        self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        entry = self.request('/api/workflow')[1]['materials'][mid]
        self.assertTrue(entry['missing'])
        self.assertEqual(entry['mentor_ids'], [self.pid])

    def test_material_register_and_unknown_links_reject(self):
        f = self.root / 'paper.pdf'
        f.write_bytes(b'fixture')
        entry = self.create('materials', {'path': str(f), 'kind': 'paper', 'mentor_ids': [self.pid]})
        self.assertEqual(entry['path'], str(f.resolve()))
        before = (self.outreach.parent / 'workflow.yaml').read_bytes()
        self.assertEqual(self.request('/api/workflow/materials/' + entry['id'], {'project_ids': ['unknown']}, 'PATCH')[0], 400)
        self.assertEqual(before, (self.outreach.parent / 'workflow.yaml').read_bytes())
        self.assertEqual(self.request('/api/workflow/materials', {'path': 'relative.txt'}, 'POST')[0], 400)

    def test_communication_events_append_without_changing_contact_status(self):
        project = self.project()
        for kind in ('draft', 'sent', 'replied'):
            self.create('communications', {'mentor_id': self.pid, 'project_id': project['id'],
                                          'kind': kind, 'date': '2026-10-14', 'subject': kind, 'content': '<script>私人内容</script>'})
        data = self.request('/api/workflow')[1]
        self.assertEqual(len(data['communications']), 3)
        entry = next(iter(data['communications'].values()))
        self.assertEqual(self.request('/api/workflow/communications/' + entry['id'], {'kind': 'sent'}, 'PATCH')[0], 400)
        self.assertFalse(self.outreach.exists())
        self.assertEqual(data['projects'][project['id']]['status'], 'planned')

    def test_multiple_reminders_complete_and_reschedule_independently(self):
        project = self.project()
        a = self.create('reminders', {'title': '准备材料', 'project_id': project['id'], 'due_date': '2026-10-15'})
        b = self.create('reminders', {'title': '跟进', 'mentor_id': self.pid, 'due_date': '2026-10-16'})
        self.assertEqual(self.request('/api/workflow/reminders/' + a['id'], {'completed': True}, 'PATCH')[0], 200)
        self.assertEqual(self.request('/api/workflow/reminders/' + b['id'], {'due_date': '2026-10-20'}, 'PATCH')[0], 200)
        data = self.request('/api/workflow')[1]['reminders']
        self.assertTrue(data[a['id']]['completed'])
        self.assertFalse(data[b['id']]['completed'])
        self.assertEqual(data[b['id']]['due_date'], '2026-10-20')

    def test_dates_and_orphan_reminders_reject(self):
        for body in [{'title': 'x', 'due_date': '2026-10-15'},
                     {'title': 'x', 'mentor_id': self.pid, 'due_date': '2026-02-30'}]:
            self.assertEqual(self.request('/api/workflow/reminders', body, 'POST')[0], 400)
        self.assertEqual(self.request('/api/workflow/communications', {'mentor_id': self.pid, 'kind': 'sent', 'date': 'bad', 'subject': 'x'}, 'POST')[0], 400)

    def test_full_backup_restore_keeps_links_and_rejects_invalid_before_write(self):
        p = self.project()
        self.create('reminders', {'title': 'x', 'project_id': p['id'], 'due_date': '2026-10-15'})
        backup = self.request('/api/workflow/backup')[1]
        path = self.outreach.parent / 'workflow.yaml'
        original = path.read_bytes()
        self.request('/api/workflow/projects/' + p['id'], {'notes': 'changed'}, 'PATCH')
        changed = path.read_bytes()
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(any(x.read_bytes() == changed for x in (path.parent / 'backups').glob('workflow-*.yaml')))
        backup['workflow']['projects'][p['id']]['mentor_ids'] = ['unknown']
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 400)
        self.assertEqual(path.read_bytes(), original)

    def test_cross_origin_private_reads_and_writes_rejected(self):
        for method, endpoint in [('GET', '/api/workflow'), ('POST', '/api/workflow/projects')]:
            req = Request(self.base + endpoint, method=method, data=b'{}' if method == 'POST' else None,
                          headers={'Origin': 'https://evil.example', 'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as err:
                self.http.open(req)
            self.assertEqual(err.exception.code, 403)
            err.exception.close()
        self.assertFalse((self.outreach.parent / 'workflow.yaml').exists())

    def test_rescan_does_not_mark_existing_excluded_files_missing(self):
        folder = self.root / 'materials'
        excluded = folder / 'cache'
        excluded.mkdir(parents=True)
        file = excluded / 'paper.pdf'
        file.write_bytes(b'fixture')
        entry = self.create('materials', {'path': str(file)})
        self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        self.assertFalse(self.request('/api/workflow')[1]['materials'][entry['id']]['missing'])
        file.unlink()
        self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        self.assertTrue(self.request('/api/workflow')[1]['materials'][entry['id']]['missing'])
        file.write_bytes(b'restored file')
        self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')
        restored = self.request('/api/workflow')[1]['materials'][entry['id']]
        self.assertFalse(restored['missing'])
        self.assertEqual(restored['size'], file.stat().st_size)

    def test_restore_duplicate_material_paths_rejected_without_write(self):
        file = self.root / 'paper.pdf'
        file.write_bytes(b'fixture')
        entry = self.create('materials', {'path': str(file)})
        backup = self.request('/api/workflow/backup')[1]
        duplicate = dict(entry, id='0' * 32)
        backup['workflow']['materials'][duplicate['id']] = duplicate
        before = (self.outreach.parent / 'workflow.yaml').read_bytes()
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 400)
        self.assertEqual((self.outreach.parent / 'workflow.yaml').read_bytes(), before)

    def test_valid_backup_recovers_corrupt_index_and_preserves_raw_copy(self):
        self.project()
        backup = self.request('/api/workflow/backup')[1]
        path = self.outreach.parent / 'workflow.yaml'
        corrupt = b'version: [broken]\n'
        path.write_bytes(corrupt)
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        self.assertTrue(any(x.read_bytes() == corrupt for x in (path.parent / 'backups').glob('workflow-*.yaml')))
        self.assertEqual(self.request('/api/workflow')[1], backup['workflow'])

    def test_cumulative_backup_larger_than_single_request_is_restorable(self):
        for _ in range(2):
            self.create('communications', {'mentor_id': self.pid, 'kind': 'note', 'subject': '大记录',
                                          'date': '2026-10-14', 'content': 'x' * 1_050_000})
        backup = self.request('/api/workflow/backup')[1]
        self.assertGreater(len(json.dumps(backup)), 2_000_000)
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)

    def test_index_size_limit_rejects_growth_before_write(self):
        with patch('crawler.workflow_util.MAX_BACKUP_BYTES', 300, create=True):
            self.assertEqual(self.request('/api/workflow/projects', {'name': 'x'}, 'POST')[0], 400)
        self.assertFalse((self.outreach.parent / 'workflow.yaml').exists())


if __name__ == '__main__':
    unittest.main()
