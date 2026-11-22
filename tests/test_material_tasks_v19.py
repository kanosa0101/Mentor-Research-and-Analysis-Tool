import copy
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.request import Request
from urllib.error import HTTPError

import test_applications
from crawler import material_task_util as tasks
from crawler import project_util as projects
from crawler.workflow_util import empty_workflow


def admissions_day():
    return datetime.now(timezone(timedelta(hours=8))).date()


def fixture():
    today = admissions_day().isoformat()
    event = dict(label='复试查验', kind='qualification', at='2026-11-01T01:00:00+00:00', quote='复试查验原件', locator='第二段')
    action = dict(id='originals', label='查验原件', stage='interview', instruction=dict(text='带原件到院系查验', quote='查验原件', locator='第二段'), event_indexes=[0])
    policy = dict(id='p', title='正式政策', school='test', dept='cs', level='dept', year=2027, degree='phd', route='assessment', track='ordinary', program='', program_code='', source_id='s', review_hashes={'s': 'a'*64}, reviewed_at=today, events=[event], material_actions=[action])
    return dict(units={'test': {'cs'}}, sources={'s': {'url': 'https://example.edu/p'}}, policies=[policy], checks={'s': dict(status='ok', hash='a'*64, last_success=today)})


class MaterialTaskV19Tests(unittest.TestCase):
    def test_v3_projection_v4_preserves_tasks(self):
        old = projects.upgrade(empty_workflow(), set(), fixture())
        wrapper = dict(old, version=4, material_tasks={})
        self.assertEqual(tasks.project(wrapper), old)
        self.assertEqual(tasks.merge(wrapper, old)['version'], 4)


class MaterialTaskApiTests(unittest.TestCase):
    setUp = test_applications.ApplicationTests.setUp
    close_server = test_applications.ApplicationTests.close_server
    request = test_applications.ApplicationTests.request
    create = test_applications.ApplicationTests.create

    def setup_context(self):
        context = fixture()
        ctxpatch = patch.object(self.serve.projects, 'load_context', return_value=context)
        ctxpatch.start()
        self.addCleanup(ctxpatch.stop)
        # Endpoint loads checks from a fixture ROOT; never writes real policy/private data.
        self.serve.ROOT = self.root
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'admissions_checks.json').write_text(json.dumps(context['checks']), encoding='utf-8')
        return context

    def project(self, **changes):
        body = dict(name='测试申请', school_id='test', dept_id='cs', year=2027, degree='phd', route='assessment', track='ordinary')
        body.update(changes)
        return self.create('projects', body)

    def row(self, project):
        code, view = self.request('/api/workflow/material-tasks')
        self.assertEqual(code, 200, view)
        return view['actions'][project['id']][0]

    def body(self, project, **changes):
        row = self.row(project)
        body = dict(project_id=project['id'], expected_goal=row['goal_snapshot'], policy_id=row['policy_id'], action_id=row['action_id'], expected_action=row['action_fingerprint'], status='prepared', material_ids=[], notes='人工确认', confirmed_conditions=False)
        body.update(changes)
        return body

    def saved(self, project, **changes):
        code, result = self.request('/api/workflow/material-tasks', self.body(project, **changes), 'POST')
        self.assertEqual(code, 200, result)
        return result

    def test_empty_reads_legacy_upgrades_and_no_discovery_creation(self):
        self.setup_context()
        path = self.outreach.with_name('workflow.yaml')
        self.assertEqual(self.request('/api/workflow/material-tasks')[1], dict(version=1, actions={}, records={}))
        self.assertFalse(path.exists())
        self.assertFalse(self.outreach.with_name('discovery.yaml').exists())
        from crawler import contact_util as contact
        for old in [empty_workflow(), contact.upgrade(empty_workflow(), {self.pid}), projects.upgrade(empty_workflow(), {self.pid}, fixture())]:
            self.serve.save_outreach(old, path)
            raw = path.read_bytes()
            self.assertEqual(self.request('/api/workflow/material-tasks')[0], 200)
            self.assertEqual(self.request('/api/workflow')[1]['version'], 3)
            self.assertEqual(self.request('/api/workflow/backup')[1]['version'], 3)
            self.assertEqual(raw, path.read_bytes())

    def test_append_backup_and_restore_replace(self):
        self.setup_context()
        project = self.project()
        legacy = self.request('/api/workflow/backup')[1]
        a, b = self.saved(project), self.saved(project, status='submitted')
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(self.row(project)['latest_record_id'], b['id'])
        backup = self.request('/api/workflow/backup')[1]
        self.assertEqual(backup['version'], 4)
        self.assertEqual(set(backup['workflow']['material_tasks']), {a['id'], b['id']})
        self.assertNotIn('material_tasks', self.request('/api/workflow')[1])
        path = self.outreach.with_name('workflow.yaml')
        raw = path.read_bytes()
        self.assertEqual(self.request('/api/workflow/restore', legacy, 'POST')[0], 200)
        self.assertEqual(self.request('/api/workflow/material-tasks')[1]['records'], {})
        self.assertTrue(any(p.read_bytes() == raw for p in (path.parent / 'backups').glob('*.yaml')))
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        self.assertEqual(set(self.request('/api/workflow/material-tasks')[1]['records']), {a['id'], b['id']})

    def test_all_legacy_writes_preserve_and_discovery_reads_v4(self):
        self.setup_context()
        project = self.project()
        record = self.saved(project)
        folder = self.root / 'materials'
        folder.mkdir()
        f = folder / 'cv.txt'
        f.write_text('fixture', encoding='utf-8')
        material = self.create('materials', dict(path=str(f)))
        self.assertEqual(self.request('/api/workflow/scan', {'root': str(folder)}, 'POST')[0], 200)
        self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'notes': 'notes'}, 'PATCH')[0], 200)
        self.assertEqual(self.request('/api/workflow/materials/' + material['id'], {'title': 'CV'}, 'PATCH')[0], 200)
        target = self.create('targets', dict(project_id=project['id'], mentor_id=self.pid))
        self.assertEqual(self.request('/api/workflow/targets/' + target['id'], {'reason': '人工'}, 'PATCH')[0], 200)
        draft = self.create('drafts', dict(target_id=target['id'], recipient='fixture@example.edu', basis='fixture', subject='test', body='test', material_ids=[material['id']]))
        self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'], {'body': 'new'}, 'PATCH')[0], 200)
        with self.http.open(self.base + '/api/workflow/drafts/' + draft['id'] + '/eml') as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b'fixture@example.edu', response.read())
        self.assertEqual(self.request('/api/workflow/drafts/' + draft['id'] + '/confirm', {'sent': True, 'date': '2026-10-15'}, 'POST')[0], 200)
        self.assertEqual(self.request('/api/workflow/targets/' + target['id'] + '/reply', {'content': '回复', 'date': '2026-10-15', 'stage': 'materials', 'task': {'title': '准备', 'due_date': '2026-11-01'}}, 'POST')[0], 200)
        self.create('communications', dict(mentor_id=self.pid, project_id=project['id'], date='2026-10-15', subject='note'))
        reminder = self.create('reminders', dict(project_id=project['id'], title='人工', due_date='2026-11-01'))
        self.assertEqual(self.request('/api/workflow/reminders/' + reminder['id'], {'completed': True}, 'PATCH')[0], 200)
        self.assertEqual(set(self.request('/api/workflow/backup')[1]['workflow']['material_tasks']), {record['id']})
        self.assertEqual(self.request('/api/discovery/project-reviews')[0], 200)

    def test_goal_source_conflicts_conditions_and_program_isolation(self):
        context = self.setup_context()
        project = self.project()
        body = self.body(project)
        self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'year': 2028}, 'PATCH')[0], 200)
        self.assertEqual(self.request('/api/workflow/material-tasks', body, 'POST')[0], 409)
        self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'year': 2027}, 'PATCH')[0], 200)
        policy = context['policies'][0]
        policy['material_actions'][0]['instruction']['text'] = 'changed'
        self.assertEqual(self.request('/api/workflow/material-tasks', body, 'POST')[0], 409)
        policy['applies_if'] = dict(text='条件', quote='条件', locator='第三段')
        self.assertEqual(self.request('/api/workflow/material-tasks', self.body(project), 'POST')[0], 400)
        self.saved(project, confirmed_conditions=True)
        policy.update(level='program', program='正式专业', program_code='0812')
        self.assertTrue(self.row(project)['program_pending'])
        self.assertEqual(self.request('/api/workflow/material-tasks', self.body(project, confirmed_conditions=True), 'POST')[0], 409)
        other = self.project(program_name='其他专业', program_code='0813')
        self.assertEqual(self.request('/api/workflow/material-tasks')[1]['actions'][other['id']], [])
        policy['material_actions'] = []
        self.assertEqual(self.request('/api/workflow/material-tasks')[1]['actions'][project['id']], [])

    def test_file_content_hash_history_and_snapshot_injection(self):
        self.setup_context()
        project, second = self.project(), self.project(name='第二项目')
        f = self.root / 'cv.txt'
        f.write_bytes(b'aaaa')
        material = self.create('materials', dict(path=str(f)))
        record = self.saved(project, material_ids=[material['id']])
        self.assertIsNone(self.row(second)['latest_record_id'])
        self.assertEqual(record['files'][0]['state'], 'unchanged')
        stat = f.stat()
        f.write_bytes(b'bbbb')
        os.utime(f, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        changed = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertEqual(changed['files'][0]['state'], 'changed')
        self.assertTrue(changed['review_required'])
        reminder_body = dict(expected_goal=record['goal_snapshot'], expected_action=record['action_fingerprint'], event_index=0)
        code, reminder = self.request('/api/workflow/material-tasks/' + record['id'] + '/reminders', reminder_body, 'POST')
        self.assertEqual(code, 200, reminder)
        self.assertIn('关联文件版本需复核', reminder['notes'])
        f.unlink()
        missing = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertEqual(missing['files'][0]['state'], 'missing')
        self.assertEqual(self.request('/api/workflow/material-tasks', self.body(project, attachments=[]), 'POST')[0], 400)

    def test_reminders_only_explicit_events_deduplicate_and_keep_raw_kind(self):
        self.setup_context()
        project = self.project()
        record = self.saved(project)
        body = dict(expected_goal=record['goal_snapshot'], expected_action=record['action_fingerprint'], event_index=0)
        path = '/api/workflow/material-tasks/' + record['id'] + '/reminders'
        code, reminder = self.request(path, body, 'POST')
        self.assertEqual(code, 200, reminder)
        self.assertFalse(reminder['duplicate'])
        self.assertIn('qualification', reminder['notes'])
        self.assertIn('2026-11-01T01:00:00+00:00', reminder['notes'])
        self.assertEqual(reminder['due_date'], '2026-11-01')
        self.assertTrue(self.request(path, body, 'POST')[1]['duplicate'])
        for index in [True, 1, -1]:
            self.assertEqual(self.request(path, dict(body, event_index=index), 'POST')[0], 400)
        self.assertEqual(self.request('/api/workflow')[1]['projects'][project['id']]['deadlines'], [])

    def test_source_change_goal_change_and_old_record_history(self):
        context = self.setup_context()
        project = self.project()
        record = self.saved(project)
        checks = self.root / 'data' / 'admissions_checks.json'
        checks.write_text(json.dumps({'s': dict(status='ok', hash='b'*64, last_success=admissions_day().isoformat())}), encoding='utf-8')
        changed = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertIn('source_changed', changed['review_reasons'])
        body = dict(expected_goal=record['goal_snapshot'], expected_action=record['action_fingerprint'], event_index=0)
        self.assertEqual(self.request('/api/workflow/material-tasks/' + record['id'] + '/reminders', body, 'POST')[0], 409)
        checks.write_text(json.dumps(context['checks']), encoding='utf-8')
        self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'year': 2028}, 'PATCH')[0], 200)
        self.assertIn('goal_changed', self.request('/api/workflow/material-tasks')[1]['records'][record['id']]['review_reasons'])
        context['policies'] = []
        historical = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertIn('action_unavailable', historical['review_reasons'])
        self.assertEqual(historical['status'], 'prepared')

    def test_aged_sources_allow_personal_progress_but_not_official_reminders(self):
        context = self.setup_context()
        project = self.project()
        checks = self.root / 'data' / 'admissions_checks.json'
        for days in [7, 8, 30, 60]:
            with self.subTest(days=days):
                checked_at = (admissions_day() - timedelta(days=days)).isoformat()
                checks.write_text(json.dumps({'s': dict(status='ok', hash='a'*64, last_success=checked_at)}), encoding='utf-8')
                row = self.row(project)
                self.assertTrue(row['can_record'])
                self.assertEqual(row['quality']['state'], 'checked' if days == 7 else 'stale')
                record = self.saved(project, status='prepared')
                self.assertEqual(record['status'], 'prepared')
                self.assertEqual(record['review_required'], days > 7)
                self.assertEqual(record['applicable'], days == 7)
                self.assertEqual(self.row(project)['latest_record_id'], record['id'])
                reminder = dict(expected_goal=record['goal_snapshot'], expected_action=record['action_fingerprint'], event_index=0)
                self.assertEqual(self.request('/api/workflow/material-tasks/' + record['id'] + '/reminders', reminder, 'POST')[0], 200 if days == 7 else 409)
        backup = self.request('/api/workflow/backup')[1]
        self.assertEqual(len(backup['workflow']['material_tasks']), 4)
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        restored = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertIn('source_stale', restored['review_reasons'])
        self.assertEqual(restored['status'], 'prepared')

    def test_old_summary_personal_progress_stays_unverified_until_reviewed(self):
        context = self.setup_context()
        project = self.project()
        context['policies'][0]['reviewed_at'] = (admissions_day() - timedelta(days=31)).isoformat()
        self.assertEqual(self.row(project)['quality']['state'], 'review')
        record = self.saved(project, status='submitted')
        self.assertIn('source_review', record['review_reasons'])
        self.assertFalse(record['applicable'])
        reminder = dict(expected_goal=record['goal_snapshot'], expected_action=record['action_fingerprint'], event_index=0)
        self.assertEqual(self.request('/api/workflow/material-tasks/' + record['id'] + '/reminders', reminder, 'POST')[0], 409)
        context['policies'][0]['reviewed_at'] = admissions_day().isoformat()
        reviewed = self.request('/api/workflow/material-tasks')[1]['records'][record['id']]
        self.assertFalse(reviewed['review_required'])
        self.assertEqual(reviewed['status'], 'submitted')

    def test_changed_failed_or_missing_source_still_blocks_personal_record(self):
        self.setup_context()
        project = self.project()
        body = self.body(project)
        checks = self.root / 'data' / 'admissions_checks.json'
        for state, observation in [
            ('changed', dict(status='ok', hash='b'*64, last_success=admissions_day().isoformat())),
            ('error', dict(status='error', hash='a'*64, last_success=admissions_day().isoformat())),
            ('unknown', {})
        ]:
            with self.subTest(state=state):
                checks.write_text(json.dumps({'s': observation}), encoding='utf-8')
                self.assertEqual(self.row(project)['quality']['state'], state)
                self.assertFalse(self.row(project)['can_record'])
                self.assertEqual(self.request('/api/workflow/material-tasks', body, 'POST')[0], 409)
        self.assertEqual(self.request('/api/workflow/material-tasks')[1]['records'], {})

    def test_scope_matrix_rejects_policy_borrowing_and_actions_independent(self):
        context = self.setup_context()
        project = self.project()
        record = self.saved(project)
        original = copy.deepcopy(context['policies'][0])
        for field, value in [('year', 2028), ('school', 'other'), ('dept', 'other'), ('degree', 'master'), ('route', 'exam'), ('track', 'special'), ('program', 'specific')]:
            context['policies'][0] = dict(copy.deepcopy(original), **{field: value})
            rows = self.request('/api/workflow/material-tasks')[1]['actions'][project['id']]
            if field == 'program':
                self.assertTrue(rows[0]['program_pending'])
            else:
                self.assertEqual(rows, [])
        context['policies'][0] = original
        action = copy.deepcopy(original['material_actions'][0])
        action['id'] = 'second-action'
        context['policies'][0]['material_actions'].append(action)
        rows = self.request('/api/workflow/material-tasks')[1]['actions'][project['id']]
        self.assertEqual(rows[0]['latest_record_id'], record['id'])
        self.assertIsNone(rows[1]['latest_record_id'])

    def test_historical_unknown_or_moved_paths_never_open_snapshot(self):
        self.setup_context()
        project = self.project()
        f = self.root / 'cv.txt'
        f.write_bytes(b'fixture')
        material = self.create('materials', dict(path=str(f)))
        record = self.saved(project, material_ids=[material['id']])
        backup = self.request('/api/workflow/backup')[1]
        stored = backup['workflow']['material_tasks'][record['id']]
        stored['attachments'][0]['path'] = str(self.root / 'unregistered-secret.txt')
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        with patch.object(tasks.contact, 'file_bytes', side_effect=AssertionError('must not read historical path')):
            self.assertEqual(self.request('/api/workflow/material-tasks')[1]['records'][record['id']]['files'][0]['state'], 'path_changed')
        del backup['workflow']['materials'][material['id']]
        self.assertEqual(self.request('/api/workflow/restore', backup, 'POST')[0], 200)
        with patch.object(tasks.contact, 'file_bytes', side_effect=AssertionError('must not read unindexed path')):
            self.assertEqual(self.request('/api/workflow/material-tasks')[1]['records'][record['id']]['files'][0]['state'], 'unknown_material')

    def test_backup_snapshot_validation_and_whole_workflow_limit(self):
        self.setup_context()
        project = self.project()
        record = self.saved(project)
        backup = self.request('/api/workflow/backup')[1]
        for mutate in [lambda e: e['source_snapshot']['sources']['s'].update(url='https://user:pass@example.edu/'),
                       lambda e: e.update(action_fingerprint='0'*64),
                       lambda e: e.update(material_ids=[{}]),
                       lambda e: e['action'].update(stage='invented')]:
            broken = copy.deepcopy(backup)
            mutate(broken['workflow']['material_tasks'][record['id']])
            self.assertEqual(self.request('/api/workflow/restore', broken, 'POST')[0], 400)
        # Isolate wrapper sizing: core is small; full task notes force total envelope over limit.
        data = backup['workflow']
        core_size = len(json.dumps(tasks.project(data), ensure_ascii=False, indent=2).encode())
        with patch.object(tasks.core, 'MAX_BACKUP_BYTES', core_size + 1000):
            with self.assertRaisesRegex(ValueError, '16 MB'):
                tasks.validate(data, {self.pid}, fixture())

    def test_material_attachment_total_limit_and_missing_error(self):
        self.setup_context()
        project = self.project()
        f = self.root / 'large.bin'
        with f.open('wb') as stream:
            stream.truncate(tasks.contact.ATTACHMENT_LIMIT + 1)
        material = self.create('materials', dict(path=str(f)))
        code, error = self.request('/api/workflow/material-tasks', self.body(project, material_ids=[material['id']]), 'POST')
        self.assertEqual(code, 400)
        self.assertIn('材料附件总量最多 20 MB', error['error'])
        f.unlink()
        code, error = self.request('/api/workflow/material-tasks', self.body(project, material_ids=[material['id']]), 'POST')
        self.assertEqual(code, 400)
        self.assertIn('不存在', error['error'])


    def test_latest_record_never_borrows_old_goal_or_action_revision(self):
        context = self.setup_context()
        project = self.project()
        record = self.saved(project, status='submitted')
        self.assertEqual(self.row(project)['latest_record_id'], record['id'])
        context['policies'][0]['material_actions'][0]['instruction']['text'] = 'new requirement'
        self.assertIsNone(self.row(project)['latest_record_id'])
        context['policies'][0]['material_actions'][0]['instruction']['text'] = '带原件到院系查验'
        self.assertEqual(self.request('/api/workflow/projects/' + project['id'], {'program_code': '0812', 'program_name': '正式专业'}, 'PATCH')[0], 200)
        self.assertIsNone(self.row(project)['latest_record_id'])
        self.assertIn(record['id'], self.request('/api/workflow/material-tasks')[1]['records'])

    def test_incomplete_program_pair_blocks_even_general_actions(self):
        self.setup_context()
        project = self.project(program_code='0812')
        row = self.row(project)
        self.assertFalse(row['can_record'])
        self.assertTrue(row['program_pending'])
        self.assertIn('goal_incomplete', row['applicability_reasons'])
        self.assertEqual(self.request('/api/workflow/material-tasks', self.body(project, confirmed_conditions=True), 'POST')[0], 409)


    def test_guards_reject_and_do_not_create_index(self):
        self.setup_context()
        path = '/api/workflow/material-tasks'
        for headers in [{'Content-Type': 'application/json', 'Host': 'evil.example'}, {'Content-Type': 'application/json', 'Origin': 'https://evil.example'}, {'Content-Type': 'text/plain'}]:
            req = Request(self.base + path, data=b'{}', method='POST', headers=headers)
            with self.assertRaises(HTTPError) as error:
                self.http.open(req)
            self.assertIn(error.exception.code, (400, 403, 415))
            error.exception.close()
        self.assertFalse(self.outreach.with_name('workflow.yaml').exists())


if __name__ == '__main__': unittest.main()
