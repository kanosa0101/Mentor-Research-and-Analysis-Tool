import copy
import unittest

from crawler import contact_util as contact
from crawler import project_util as projects
from crawler.workflow_util import empty_workflow, update_entry


class ProjectModelTests(unittest.TestCase):
    def setUp(self):
        core, self.project = update_entry(empty_workflow(), 'projects', {'name': '旧申请', 'school': '测试', 'year': 2027}, set())
        self.old = contact.upgrade(core, set())
        self.context = {'units': {'test': {'cs'}}, 'sources': {'official': {'url': 'https://example.edu/policy'}}, 'policies': []}

    def upgrade(self):
        return projects.upgrade(self.old, set(), self.context)

    def test_upgrade_is_in_memory_and_preserves_unknown_scope(self):
        before = copy.deepcopy(self.old)
        data = self.upgrade()
        self.assertEqual(data['version'], 3)
        self.assertEqual(data['projects'][self.project['id']]['school_id'], '')
        self.assertEqual(self.old, before)

    def test_scope_validation_and_core_merge_preserve_fields(self):
        data, entry = projects.update(self.upgrade(), {'school_id': 'test', 'dept_id': 'cs', 'degree': 'master', 'route': 'recommend', 'track': 'ordinary'}, set(), self.context, self.project['id'])
        base, _ = update_entry(contact.core_view(data), 'reminders', {'title': '准备', 'project_id': entry['id'], 'due_date': '2026-11-01'}, set())
        merged = contact.merge_core(data, base, set())
        self.assertEqual(merged['projects'][entry['id']]['school_id'], 'test')
        for body in ({'school_id': 'fake'}, {'dept_id': 'fake'}, {'degree': 'bad'}):
            with self.assertRaises(ValueError):
                projects.update(data, body, set(), self.context, entry['id'])

    def test_policy_event_requires_exact_scope_and_snapshot(self):
        event = dict(label='申请截止', kind='deadline', at='2026-11-01', quote='原文截止', locator='第1段')
        policy = dict(id='p', school='test', dept='cs', level='dept', year=2027, degree='master', route='recommend', track='ordinary', program='', program_code='', source_id='official', events=[event])
        self.context['policies'] = [policy]
        snapshot = dict(event, origin='policy', policy_id='p', source_ids=['official'], source_url='https://example.edu/policy')
        scope = dict(school_id='test', dept_id='cs', degree='master', route='recommend', track='ordinary', deadlines=[snapshot])
        data, entry = projects.update(self.upgrade(), scope, set(), self.context, self.project['id'])
        for body in ({'year': 2028}, {'deadlines': [dict(snapshot, at='2026-12-01')]}, {'deadlines': [snapshot, snapshot]}):
            with self.assertRaises(ValueError):
                projects.update(data, body, set(), self.context, entry['id'])
        projects.update(data, {'year': 2028, 'deadlines': []}, set(), self.context, entry['id'])
        self.context['policies'] = []
        historical = projects.upgrade(data, set(), self.context)
        projects.update(historical, {'notes': '历史快照仍可查看'}, set(), self.context, entry['id'])
        with self.assertRaises(ValueError):
            projects.update(historical, {'deadlines': [dict(snapshot, label='改动')]}, set(), self.context, entry['id'])

    def test_manual_dates_require_valid_iso_and_personal_origin(self):
        event = dict(label='个人计划：准备材料', kind='plan', at='2026-11-01', origin='manual', policy_id='', source_ids=[], source_url='', quote='', locator='')
        data, entry = projects.update(self.upgrade(), {'deadlines': [event]}, set(), self.context, self.project['id'])
        for changed in ({'at': '2026-11-01T12:00:00'}, {'at': '2026-02-30'}, {'policy_id': 'p'}, {'origin': 'official'}):
            with self.assertRaises(ValueError):
                projects.update(data, {'deadlines': [dict(event, **changed)]}, set(), self.context, entry['id'])

    def test_conditional_program_and_special_school_are_not_applicable(self):
        entry = dict(school_id='test', dept_id='cs', year=2027, degree='master', route='recommend', track='ordinary', program_name='', program_code='')
        policy = dict(school='test', dept='cs', year=2027, degree='master', route='recommend', track='ordinary', level='program', program='计算机', program_code='0812')
        self.assertFalse(projects.applicable(entry, policy))
        self.assertTrue(projects.applicable(dict(entry, program_name='计算机', program_code='0812'), policy))
        self.assertFalse(projects.applicable(dict(entry, track='special'), dict(policy, level='school', dept='', track='general', program='', program_code='')))
        self.assertFalse(projects.applicable(dict(entry, year=2028), policy))

    def test_manual_invalid_source_urls_are_rejected(self):
        event = dict(label='个人计划', kind='plan', at='2026-11-01T12:00:00+08:00', origin='manual', policy_id='', source_ids=[], source_url='', quote='', locator='')
        for url in ('javascript:alert(1)', 'https://user:secret@example.edu/', 'file:///tmp/policy'):
            with self.assertRaises(ValueError):
                projects.update(self.upgrade(), {'deadlines': [dict(event, source_url=url)]}, set(), self.context, self.project['id'])
        projects.update(self.upgrade(), {'deadlines': [dict(event, source_url='https://example.edu/notice', quote='用户登记说明', locator='通知正文')]}, set(), self.context, self.project['id'])

    def test_event_url_uses_first_actual_reference_instead_of_policy_primary(self):
        event = dict(label='申请截止', kind='deadline', at='2026-11-01', quote='PDF截止原文', locator='PDF第2页', source_ids=['attachment', 'official'])
        self.context['sources']['attachment'] = {'url': 'https://example.edu/rules.pdf'}
        self.context['policies'] = [dict(id='p', school='test', dept='cs', level='dept', year=2027, degree='master', route='recommend', track='ordinary', program='', program_code='', source_id='official', events=[event])]
        snapshot = dict(event, origin='policy', policy_id='p', source_url='https://example.edu/rules.pdf')
        scope = dict(school_id='test', dept_id='cs', degree='master', route='recommend', track='ordinary', deadlines=[snapshot])
        projects.update(self.upgrade(), scope, set(), self.context, self.project['id'])
        with self.assertRaises(ValueError):
            projects.update(self.upgrade(), dict(scope, deadlines=[dict(snapshot, source_url='https://example.edu/policy')]), set(), self.context, self.project['id'])


if __name__ == '__main__':
    unittest.main()
