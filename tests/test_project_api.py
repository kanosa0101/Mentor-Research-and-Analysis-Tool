import copy
import unittest
from unittest.mock import patch

import test_applications
from crawler import contact_util as contact
from crawler.workflow_util import empty_workflow, update_entry


class ProjectApiTests(unittest.TestCase):
    setUp = test_applications.ApplicationTests.setUp
    close_server = test_applications.ApplicationTests.close_server
    request = test_applications.ApplicationTests.request
    create = test_applications.ApplicationTests.create

    def test_upgrade_old_files_and_backups_without_read_writes(self):
        core, project = update_entry(empty_workflow(), 'projects', {'name': '旧项目'}, {self.pid})
        v2 = contact.upgrade(core, {self.pid})
        path = self.outreach.with_name('workflow.yaml')
        for old in (core, v2):
            self.serve.save_outreach(old, path)
            before = path.read_bytes()
            code, data = self.request('/api/workflow')
            self.assertEqual(code, 200, data)
            self.assertEqual(data['version'], 3)
            self.assertEqual(data['projects'][project['id']]['school_id'], '')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.request('/api/workflow/backup')[1]['version'], 3)
            self.assertEqual(self.request('/api/workflow/restore', {'version': old['version'], 'workflow': old}, 'POST')[0], 200)
            self.assertTrue(any(p.read_bytes() == before for p in (path.parent / 'backups').glob('*.yaml')))

    def test_create_update_and_invalid_restore_are_atomic(self):
        context = {'units': {'test': {'cs'}}, 'sources': {}, 'policies': []}
        with patch.object(self.serve.projects, 'load_context', return_value=context):
            entry = self.create('projects', dict(name='申请', school_id='test', dept_id='cs', degree='master', route='exam', track='ordinary'))
            path = self.outreach.with_name('workflow.yaml')
            before = path.read_bytes()
            self.assertEqual(self.request('/api/workflow/projects/' + entry['id'], {'dept_id': 'unknown'}, 'PATCH')[0], 400)
            self.assertEqual(before, path.read_bytes())
            backup = self.request('/api/workflow/backup')[1]
            broken = copy.deepcopy(backup)
            broken['workflow']['projects'][entry['id']]['degree'] = 'unknown'
            self.assertEqual(self.request('/api/workflow/restore', broken, 'POST')[0], 400)
            self.assertEqual(before, path.read_bytes())
            broken['workflow']['projects'][entry['id']] = []
            self.assertEqual(self.request('/api/workflow/restore', broken, 'POST')[0], 400)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)

    def test_material_scan_contact_draft_and_reminder_preserve_scope(self):
        context = {'units': {'test': {'cs'}}, 'sources': {}, 'policies': []}
        with patch.object(self.serve.projects, 'load_context', return_value=context):
            scope = dict(school_id='test', dept_id='cs', year=2027, degree='master', route='exam', track='ordinary', program_name='计算机', program_code='0812')
            event = dict(label='个人计划', kind='plan', at='2026-11-01', origin='manual', policy_id='', source_ids=[], source_url='', quote='', locator='')
            project = self.create('projects', dict(scope, name='申请', deadlines=[event]))
            folder = self.root / 'materials'
            folder.mkdir()
            (folder / 'cv.txt').write_text('fixture', encoding='utf-8')
            self.assertEqual(self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')[0], 200)
            mid = next(iter(self.request('/api/workflow')[1]['materials']))
            self.assertEqual(self.request('/api/workflow/materials/' + mid, {'project_ids': [project['id']]}, 'PATCH')[0], 200)
            target = self.create('targets', {'project_id': project['id'], 'mentor_id': self.pid})
            draft = self.create('drafts', {'target_id': target['id'], 'recipient': 'fixture@example.edu', 'subject': '申请', 'body': '正文', 'basis': 'fixture', 'material_ids': [mid]})
            self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'] + '/confirm', {'sent': True, 'date': '2026-10-15'}, 'POST')[0], 200)
            self.assertEqual(self.request('/api/workflow/targets/' + target['id'] + '/reply', {'content': '回复', 'date': '2026-10-15', 'stage': 'materials', 'task': {'title': '准备', 'due_date': '2026-11-01'}}, 'POST')[0], 200)
            self.create('communications', {'mentor_id': self.pid, 'project_id': project['id'], 'date': '2026-10-15', 'subject': '人工备注', 'kind': 'note'})
            saved = self.request('/api/workflow')[1]['projects'][project['id']]
            for key, value in scope.items():
                self.assertEqual(saved[key], value)
            self.assertEqual(saved['deadlines'], [event])

    def test_historical_policy_removal_keeps_read_restore_scan_and_notes_usable(self):
        event = dict(label='报名截止', kind='deadline', at='2026-11-01', quote='原文', locator='第一段')
        policy = dict(id='p', school='test', dept='cs', level='dept', year=2027, degree='master', route='exam', track='ordinary', program='', program_code='', source_id='s', events=[event])
        context = {'units': {'test': {'cs'}}, 'sources': {'s': {'url': 'https://example.edu/policy'}}, 'policies': [policy]}
        snapshot = dict(event, origin='policy', policy_id='p', source_ids=['s'], source_url='https://example.edu/policy')
        with patch.object(self.serve.projects, 'load_context', return_value=context):
            project = self.create('projects', dict(name='申请', school_id='test', dept_id='cs', year=2027, degree='master', route='exam', track='ordinary', deadlines=[snapshot]))
            backup = self.request('/api/workflow/backup')[1]
            context['policies'] = []
            context['sources'] = {}
            context['units'] = {}
            self.assertEqual(self.request('/api/workflow')[0], 200)
            self.assertEqual(self.request('/api/workflow/backup')[0], 200)
            self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'notes': '保留历史来源'}, 'PATCH')[0], 200)
            self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
            folder = self.root / 'materials'
            folder.mkdir()
            self.assertEqual(self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')[0], 200)
            self.assertEqual(self.request('/api/workflow')[1]['projects'][project['id']]['deadlines'], [snapshot])
            path = self.outreach.with_name('workflow.yaml')
            before = path.read_bytes()
            self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'year': 2028}, 'PATCH')[0], 400)
            self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'deadlines': [dict(snapshot, label='改动')]}, 'PATCH')[0], 400)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.request('/api/workflow/projects', {'name': '无效新申请', 'school_id': 'test', 'dept_id': 'cs'}, 'POST')[0], 400)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
