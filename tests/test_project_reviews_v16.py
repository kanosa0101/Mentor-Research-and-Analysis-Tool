import copy
import unittest
from datetime import date, timedelta
import json
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import test_workflow

from crawler import discovery_util as discovery
from crawler import project_review_util as review


class ProjectReviewTests(unittest.TestCase):
    def setUp(self):
        self.goal = dict(school_id='test', dept_id='cs', year=2027, degree='master',
                         route='recommend', track='ordinary', program_code='0812', program_name='计算机')
        self.workflow = {'projects': {'p1': dict(self.goal, id='p1', name='申请')}, 'communications': {}}
        self.mentors = {'test-cs-example': {'school': 'test', 'dept': 'cs'}}
        self.context = {'units': {'test': {'cs'}}, 'sources': {'s1': {'url': 'https://test.edu.cn/notice'}},
                        'checks': {'s1': {'status': 'ok', 'hash': 'a' * 64, 'last_success': date.today().isoformat()}}}
        self.evidence = dict(kind='official', source_url='https://test.edu.cn/unregistered', quote='本年接收', scope='本项目')
        self.body = dict(project_id='p1', mentor_id='test-cs-example', expected_goal=self.goal,
                         opportunity='pass', eligibility='unknown', opportunity_evidence=self.evidence,
                         eligibility_evidence=None, confirmed=True)

    def save(self, body=None, data=None):
        return review.save(data or discovery.empty(), body or self.body, self.workflow, self.mentors, self.context)

    def test_first_explicit_save_upgrades_without_changing_legacy(self):
        old = discovery.empty()
        original = copy.deepcopy(old)
        data, entry = self.save(data=old)
        self.assertEqual(old, original)
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['preferences'], original['preferences'])
        self.assertEqual(data['reviews'], original['reviews'])
        discovery.validate(data, self.mentors)
        self.assertEqual(entry['goal_snapshot'], self.goal)

    def test_projects_and_changed_goal_have_different_ids(self):
        data, first = self.save()
        self.workflow['projects']['p2'] = dict(self.goal, id='p2', name='第二申请')
        body = dict(self.body, project_id='p2', opportunity='fail')
        data, second = self.save(body, data)
        self.assertNotEqual(first['id'], second['id'])
        self.workflow['projects']['p1']['track'] = 'special'
        with self.assertRaises(review.GoalChanged):
            self.save(data=data)
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][first['id']]
        self.assertFalse(state['applicable'])
        self.assertIn('goal_changed', state['reasons'])
        body = dict(self.body, expected_goal=review.goal_snapshot(self.workflow['projects']['p1']))
        data, third = self.save(body, data)
        self.assertNotEqual(first['id'], third['id'])
        self.assertEqual(len(data['project_reviews']), 3)

    def test_confirmation_completeness_unit_and_client_fields(self):
        for patch in [dict(confirmed=False), dict(opportunity_evidence=None), dict(source_hash='fake'),
                      dict(mentor_id='missing'), dict(expected_goal={})]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.save(dict(self.body, **patch))
        self.workflow['projects']['p1']['program_name'] = ''
        with self.assertRaises(ValueError):
            self.save(dict(self.body, expected_goal=review.goal_snapshot(self.workflow['projects']['p1'])))
        self.workflow['projects']['p1']['program_name'] = '计算机'
        self.mentors['test-cs-example']['dept'] = 'other'
        with self.assertRaises(ValueError):
            self.save()

    def test_reply_requires_received_same_project_mentor_and_quote(self):
        event = dict(id='c1', project_id='p1', mentor_id='test-cs-example', kind='replied',
                     subject='答复', date=date.today().isoformat(), content='本年没有名额')
        self.workflow['communications']['c1'] = event
        evidence = dict(kind='reply', communication_id='c1', quote='没有名额', scope='本项目')
        body = dict(self.body, opportunity='fail', opportunity_evidence=evidence)
        data, entry = self.save(body)
        self.assertEqual(entry['opportunity_evidence']['communication_hash'], review.fingerprint(event))
        for key, values in [('kind', ['draft', 'sent', 'note']), ('project_id', ['p2']), ('mentor_id', ['other']), ('content', ['其他内容'])]:
            for value in values:
                changed = dict(event, **{key: value})
                self.workflow['communications']['c1'] = changed
                with self.assertRaises(ValueError):
                    self.save(body)
                state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
                self.assertEqual(state['opportunity_status'], 'unknown')
        self.workflow['communications'].clear()
        self.assertEqual(review.view(data, self.workflow, self.mentors, self.context)['replies'], {})

    def test_independent_sources_and_expiry(self):
        body = dict(self.body, eligibility='pass', eligibility_evidence=self.evidence,
                    opportunity_evidence=dict(self.evidence, source_id='s1', source_url='https://test.edu.cn/notice'))
        data, entry = self.save(body)
        self.assertEqual(entry['opportunity_evidence']['source_hash'], 'a' * 64)
        self.context['checks']['s1']['hash'] = 'b' * 64
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
        self.assertTrue(state['applicable'])
        self.assertEqual(state['opportunity_status'], 'unknown')
        self.assertEqual(state['eligibility_status'], 'pass')
        self.assertIn('source_unmonitored', state['eligibility_reasons'])
        self.assertIn('source_changed', state['opportunity_reasons'])
        entry['checked_at'] = (date.today() - timedelta(days=31)).isoformat()
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
        self.assertFalse(state['applicable'])

    def test_registered_source_binding_and_failed_checks(self):
        evidence = dict(self.evidence, source_id='s1', source_url='https://test.edu.cn/notice')
        for patch in [dict(source_url='https://other.edu.cn'), dict(source_hash='a' * 64), dict(source_id='missing')]:
            with self.assertRaises(ValueError):
                self.save(dict(self.body, opportunity_evidence=dict(evidence, **patch)))
        for check in [{'status': 'error', 'hash': 'a' * 64},
                      {'status': 'ok', 'hash': 'a' * 64, 'last_success': (date.today()-timedelta(days=8)).isoformat()}]:
            self.context['checks']['s1'] = check
            with self.assertRaises(ValueError):
                self.save(dict(self.body, opportunity_evidence=evidence))

    def test_source_unavailable_and_missing_preserve_other_dimension(self):
        body = dict(self.body, eligibility='fail', eligibility_evidence=self.evidence,
                    opportunity_evidence=dict(self.evidence, source_id='s1', source_url='https://test.edu.cn/notice'))
        data, entry = self.save(body)
        for check in [dict(status='error', hash='a' * 64, last_success=date.today().isoformat()),
                      dict(status='ok', hash='a' * 64, last_success=(date.today()-timedelta(days=8)).isoformat()), []]:
            self.context['checks']['s1'] = check
            state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
            self.assertEqual(state['opportunity_status'], 'unknown')
            self.assertEqual(state['eligibility_status'], 'fail')
            self.assertIn('source_unavailable', state['opportunity_reasons'])
        self.context['sources'].clear()
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
        self.assertIn('source_missing', state['opportunity_reasons'])
        self.workflow['projects'].clear()
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
        self.assertIn('project_missing', state['reasons'])
        self.assertEqual(state['eligibility_status'], 'unknown')

    def test_ordinary_and_special_completeness(self):
        for track, code, name, expected in [('ordinary', '', '', True), ('ordinary', '0812', '', False),
                                           ('special', '', '', False), ('special', '', '专项名称', True)]:
            goal = dict(self.goal, track=track, program_code=code, program_name=name)
            self.assertEqual(review.complete(goal), expected)

    def test_registered_url_binds_server_hash_and_cannot_bypass_failed_source(self):
        evidence = dict(self.evidence, source_url='https://test.edu.cn/notice')
        data, entry = self.save(dict(self.body, opportunity_evidence=evidence))
        self.assertEqual(entry['opportunity_evidence']['source_id'], 's1')
        self.assertEqual(entry['opportunity_evidence']['source_hash'], 'a' * 64)
        self.context['checks']['s1']['status'] = 'error'
        with self.assertRaises(ValueError):
            self.save(dict(self.body, opportunity_evidence=evidence))
        self.context['sources']['s2'] = self.context['sources']['s1'].copy()
        self.context['checks']['s2'] = dict(status='ok', hash='b'*64, last_success=date.today().isoformat())
        data, entry = self.save(dict(self.body, opportunity_evidence=evidence))
        self.assertEqual(entry['opportunity_evidence']['source_id'], 's2')

    def test_html_fragments_and_default_port_cannot_bypass_registered_resource(self):
        evidence = dict(self.evidence, source_url='HTTPS://TEST.EDU.CN:443/notice#eligibility')
        for source_format in ('html', 'pdf'):
            self.context['sources']['s1']['format'] = source_format
            self.context['checks']['s1']['status'] = 'error'
            with self.assertRaises(ValueError):
                self.save(dict(self.body, opportunity_evidence=evidence))
            self.context['checks']['s1']['status'] = 'ok'
            data, entry = self.save(dict(self.body, opportunity_evidence=evidence))
            self.assertEqual(entry['opportunity_evidence']['source_id'], 's1')
            self.assertEqual(entry['opportunity_evidence']['source_hash'], 'a' * 64)
            state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
            self.assertEqual(state['opportunity_status'], 'pass')

    def test_new_registration_requires_reconfirmation_without_mutating_old_record(self):
        body = dict(self.body, eligibility='fail', eligibility_evidence=dict(self.evidence, source_url='https://other.edu.cn/unknown'))
        data, entry = self.save(body)
        before = copy.deepcopy(data)
        self.context['sources']['new'] = dict(url=self.evidence['source_url'] + '#scope', format='html')
        for status in ('error', 'ok'):
            self.context['checks']['new'] = dict(status=status, hash='b' * 64, last_success=date.today().isoformat())
            state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
            self.assertEqual(state['opportunity_status'], 'unknown')
            self.assertEqual(state['eligibility_status'], 'fail')
            self.assertIn('source_registered', state['opportunity_reasons'])
            if status == 'error':
                self.assertIn('source_unavailable', state['opportunity_reasons'])
            self.assertEqual(data, before)
        data, entry = self.save(body, data)
        self.assertEqual(entry['opportunity_evidence']['source_hash'], 'b' * 64)

    def test_json_article_fragments_are_distinct_resources(self):
        self.context['sources'] = {'json': dict(url='https://test.edu.cn/#/article/one', format='json')}
        self.context['checks'] = {'json': dict(status='error', hash='a' * 64, last_success=date.today().isoformat())}
        evidence = dict(self.evidence, source_url='https://test.edu.cn/#/article/two')
        data, entry = self.save(dict(self.body, opportunity_evidence=evidence))
        self.assertNotIn('source_id', entry['opportunity_evidence'])
        state = review.view(data, self.workflow, self.mentors, self.context)['project_reviews'][entry['id']]
        self.assertEqual(state['opportunity_status'], 'pass')
        self.assertEqual(state['opportunity_reasons'], ['source_unmonitored'])
        evidence['source_url'] = 'HTTPS://TEST.EDU.CN:443/#/article/one'
        with self.assertRaises(ValueError):
            self.save(dict(self.body, opportunity_evidence=evidence))


class ProjectReviewAPITests(unittest.TestCase):
    close_server = test_workflow.WorkflowTests.close_server
    request = test_workflow.WorkflowTests.request

    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        self.addCleanup(patch.stopall)
        patch.object(self.serve, 'ROOT', self.root).start()
        data = self.root / 'data'
        data.mkdir()
        (data / 'schools.yaml').write_text('schools:\n- id: test\n', encoding='utf-8')
        (data / 'admissions.yaml').write_text('sources: {}\npolicies: []\n', encoding='utf-8')
        unit = self.root / 'sites' / 'test'
        unit.mkdir(parents=True)
        (unit / 'cs.yaml').write_text('school: test\ndept: cs\n', encoding='utf-8')
        mentor = data / 'professors' / 'test' / 'cs'
        mentor.mkdir(parents=True)
        (mentor / 'example.yaml').write_text('school: test\ndept: cs\n', encoding='utf-8')
        self.goal = dict(school_id='test', dept_id='cs', year=2027, degree='master', route='recommend',
                         track='ordinary', program_code='', program_name='')
        self.project = self.request('/api/workflow/projects', dict(self.goal, name='私人申请'), 'POST')[1]
        self.body = dict(project_id=self.project['id'], mentor_id=self.pid, expected_goal=self.goal,
                         opportunity='pass', eligibility='unknown',
                         opportunity_evidence=dict(kind='official', source_url='https://test.edu.cn/notice', quote='接收', scope='本项目'),
                         eligibility_evidence=None, confirmed=True)
        self.path = self.outreach.with_name('discovery.yaml')

    def test_get_v1_no_migration_and_save_roundtrip(self):
        workflow_bytes = self.outreach.with_name('workflow.yaml').read_bytes()
        self.assertEqual(self.request('/api/discovery/project-reviews')[0], 200)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.outreach.with_name('workflow.yaml').read_bytes(), workflow_bytes)
        prefs = self.request('/api/discovery')[1]['preferences']
        self.request('/api/discovery', prefs, 'POST')
        before = self.path.read_bytes()
        self.assertEqual(self.request('/api/discovery/project-reviews')[0], 200)
        self.assertEqual(before, self.path.read_bytes())
        code, entry = self.request('/api/discovery/project-reviews', self.body, 'POST')
        self.assertEqual(code, 200, entry)
        self.assertEqual(self.request('/api/discovery')[1]['version'], 2)
        state = self.request('/api/discovery/project-reviews')[1]['project_reviews'][entry['id']]
        self.assertEqual(state['opportunity_status'], 'pass')
        backup = self.request('/api/discovery/backup')[1]
        self.assertEqual(backup['version'], 2)
        self.assertNotIn('applicable', backup['discovery']['project_reviews'][entry['id']])

    def test_goal_changed_after_form_open_does_not_write(self):
        code, _ = self.request('/api/workflow/projects/' + self.project['id'], {'track': 'special', 'program_name': '专项'}, 'PATCH')
        self.assertEqual(code, 200)
        code, result = self.request('/api/discovery/project-reviews', self.body, 'POST')
        self.assertEqual(code, 409, result)
        self.assertFalse(self.path.exists())

    def test_legacy_writes_preserve_v2_restore_and_original_bytes(self):
        code, entry = self.request('/api/discovery/project-reviews', self.body, 'POST')
        self.assertEqual(code, 200, entry)
        prefs = self.request('/api/discovery')[1]['preferences']
        self.assertEqual(self.request('/api/discovery', prefs, 'POST')[0], 200)
        old_review = dict(mentor_id=self.pid, year=2027, degree='master', route='recommend',
                          opportunity='pass', eligibility='unknown', source_url='https://test.edu.cn', quote='原文', confirmed=True)
        self.assertEqual(self.request('/api/discovery/reviews', old_review, 'POST')[0], 200)
        backup = self.request('/api/discovery/backup')[1]
        self.assertEqual(backup['discovery']['project_reviews'][entry['id']], entry)
        original = b'broken: [ # preserve exact bytes\r\n'
        self.path.write_bytes(original)
        self.assertEqual(self.request('/api/discovery/restore', backup, 'POST')[0], 200)
        self.assertIn(original, [p.read_bytes() for p in (self.path.parent / 'backups').glob('discovery-*')])
        before = self.path.read_bytes()
        self.assertEqual(self.request('/api/discovery/restore', dict(backup, version=1), 'POST')[0], 400)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.request('/api/discovery/restore', {'version': 1, 'discovery': discovery.empty()}, 'POST')[0], 200)
        self.assertEqual(self.request('/api/discovery')[1]['version'], 1)

    def test_guards_and_reply_api(self):
        for header in [{'Origin': 'https://evil.example'}, {'Host': 'evil.example'}, {'Content-Type': 'text/plain'}, {'Sec-Fetch-Site': 'cross-site'}]:
            req = Request(self.base + '/api/discovery/project-reviews', method='POST', data=json.dumps(self.body).encode(),
                          headers={'Content-Type': 'application/json', **header})
            with self.assertRaises(HTTPError) as error:
                self.http.open(req)
            self.assertIn(error.exception.code, (403, 415))
            error.exception.close()
        event = dict(mentor_id=self.pid, project_id=self.project['id'], kind='replied',
                     date=date.today().isoformat(), subject='回复', content='没有名额')
        code, reply = self.request('/api/workflow/communications', event, 'POST')
        self.assertEqual(code, 200, reply)
        body = dict(self.body, opportunity='fail', opportunity_evidence=dict(kind='reply', communication_id=reply['id'], quote='没有名额', scope='本项目'))
        code, entry = self.request('/api/discovery/project-reviews', body, 'POST')
        self.assertEqual(code, 200, entry)
        self.assertEqual(self.request('/api/discovery/project-reviews')[1]['replies'][reply['id']]['content'], '没有名额')

    def test_invalid_port_backup_restore_is_rejected_without_writing(self):
        code, entry = self.request('/api/discovery/project-reviews', self.body, 'POST')
        self.assertEqual(code, 200, entry)
        before = self.path.read_bytes()
        backup = self.request('/api/discovery/backup')[1]
        backup['discovery']['project_reviews'][entry['id']]['opportunity_evidence']['source_url'] = 'https://test.edu.cn:bad/'
        self.assertEqual(self.request('/api/discovery/restore', backup, 'POST')[0], 400)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.request('/api/discovery/project-reviews')[0], 200)
