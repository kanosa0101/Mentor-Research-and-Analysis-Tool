import unittest
from unittest.mock import patch
import test_applications


class ConditionalProjectTests(unittest.TestCase):
    setUp = test_applications.ApplicationTests.setUp
    close_server = test_applications.ApplicationTests.close_server
    request = test_applications.ApplicationTests.request
    create = test_applications.ApplicationTests.create

    def test_post_rejects_conditional_and_old_get_patch_preserve_snapshot(self):
        event = dict(label='考点补充材料', kind='deadline', at='2026-10-31T12:00:00+08:00', quote='10月31日12:00', locator='二（三）')
        policy = dict(id='p', school='test', dept='', level='school', year=2027, degree='master', route='exam', track='ordinary', program='', program_code='', source_id='s', events=[event])
        context = {'units': {'test': {'cs'}}, 'sources': {'s': {'url': 'https://example.edu/policy'}}, 'policies': [policy]}
        snapshot = dict(event, origin='policy', policy_id='p', source_ids=['s'], source_url='https://example.edu/policy')
        body = dict(name='历史项目', school_id='test', dept_id='cs', year=2027, degree='master', route='exam', track='ordinary', deadlines=[snapshot])
        with patch.object(self.serve.projects, 'load_context', return_value=context):
            old = self.create('projects', body)
            policy['applies_if'] = dict(text='仅适用于6112报考点', quote='考点说明', locator='二')
            path = self.outreach.with_name('workflow.yaml')
            before = path.read_bytes()
            self.assertEqual(self.request('/api/workflow/projects', dict(body, name='新项目'), 'POST')[0], 400)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.request('/api/workflow')[1]['projects'][old['id']]['deadlines'], [snapshot])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.request('/api/workflow/projects/'+old['id'], {'notes': '保留历史'}, 'PATCH')[0], 200)
            self.assertEqual(self.request('/api/workflow')[1]['projects'][old['id']]['deadlines'], [snapshot])
