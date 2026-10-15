"""Regression for conditional v20 deadlines using public policy data and temporary workflow storage."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_workflow
from crawler import project_util as projects

ROOT = Path(__file__).resolve().parents[1]
POLICY_IDS = (
    'tsinghua-2027-master-registration-v20north',
    'bit-2027-master-testcenter1107-v20north',
    'buaa-2027-master-testcenter1106-v20north',
)


def public_context():
    return projects.load_context(ROOT)


def ordinary_goal(policy):
    return dict(school_id=policy['school'], dept_id='cs', year=policy['year'],
                degree='master', route='exam', track='ordinary',
                program_code='', program_name='', deadlines=[])


class ConditionalDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.context = public_context()
        by_id = {p['id']: p for p in self.context['policies']}
        self.policies = [by_id[pid] for pid in POLICY_IDS]

    def test_policy_conditions_protect_each_special_scope(self):
        for policy in self.policies:
            with self.subTest(policy=policy['id']):
                condition = policy.get('applies_if')
                self.assertTrue(condition, 'Special deadline policy needs its own condition')
                self.assertTrue(condition['quote'])
                self.assertTrue(condition['locator'])
                self.assertTrue(set(condition['source_ids']) <= set(policy['review_hashes']))

    def test_ordinary_goal_cannot_automatically_apply_special_policy(self):
        for policy in self.policies:
            with self.subTest(policy=policy['id']):
                self.assertFalse(projects.applicable(ordinary_goal(policy), policy))

    def test_special_events_cannot_be_imported_as_ordinary_dates(self):
        for policy in self.policies:
            self.assertTrue(policy.get('events'))
            for event in policy['events']:
                with self.subTest(policy=policy['id'], event=event['label']):
                    goal = ordinary_goal(policy)
                    refs = event.get('source_ids', [policy['source_id']])
                    goal['deadlines'] = [dict(copy.deepcopy(event), origin='policy',
                                              policy_id=policy['id'], source_ids=refs,
                                              source_url=self.context['sources'][refs[0]]['url'])]
                    with self.assertRaisesRegex(ValueError, '政策时间不适用于当前目标'):
                        projects.validate_imports(goal, None, self.context)

    def test_actions_keep_specific_identity_conditions_and_event_bindings(self):
        for policy in self.policies:
            self.assertTrue(policy.get('material_actions'))
            for action in policy['material_actions']:
                with self.subTest(policy=policy['id'], action=action['id']):
                    self.assertTrue(action.get('applies_if'))
                    self.assertNotEqual(action['applies_if']['text'], policy.get('applies_if', {}).get('text'))
                    for index in action.get('event_indexes', []):
                        self.assertIs(type(index), int)
                        self.assertLess(index, len(policy['events']))
        tsinghua = self.policies[0]
        actions = {a['id']: a for a in tsinghua['material_actions']}
        self.assertEqual(actions['submit-second-degree-permission']['event_indexes'], [0])
        for action_id in ('submit-graduate-permission', 'submit-unverified-academic-record'):
            self.assertEqual(actions[action_id]['event_indexes'], [1])


class ConditionalDeadlineGetTests(unittest.TestCase):
    setUp = test_workflow.WorkflowTests.setUp
    close_server = test_workflow.WorkflowTests.close_server
    request = test_workflow.WorkflowTests.request

    def test_get_keeps_conditions_without_creating_records_or_judging_identity(self):
        context = public_context()
        context['checks'] = json.loads((ROOT / 'data' / 'admissions_checks.json').read_text(encoding='utf-8'))
        self.serve.ROOT = self.root
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'admissions_checks.json').write_text(json.dumps(context['checks']), encoding='utf-8')
        workflow = self.outreach.with_name('workflow.yaml')
        with patch.object(self.serve.projects, 'load_context', return_value=context):
            self.assertEqual(self.request('/api/workflow/material-tasks')[0], 200)
            self.assertFalse(workflow.exists())
            for policy_id in POLICY_IDS:
                policy = next(p for p in context['policies'] if p['id'] == policy_id)
                code, project = self.request('/api/workflow/projects',
                    dict(ordinary_goal(policy), name='temporary ordinary CS applicant'), 'POST')
                self.assertEqual(code, 200, project)
                self.assertEqual(project['deadlines'], [])
            before = workflow.read_bytes()
            code, view = self.request('/api/workflow/material-tasks')
            self.assertEqual(code, 200, view)
            self.assertEqual(view['records'], {})
            for policy_id in POLICY_IDS:
                rows = [row for group in view['actions'].values() for row in group if row['policy_id'] == policy_id]
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual({c['scope'] for c in row['conditions']}, {'policy', 'action'})
                    self.assertIsNone(row['latest_record_id'])
                    self.assertNotIn('confirmed_conditions', row)
            self.assertEqual(workflow.read_bytes(), before)
            self.assertFalse(self.outreach.exists())
            self.assertFalse(self.outreach.with_name('discovery.yaml').exists())


if __name__ == '__main__':
    unittest.main()
