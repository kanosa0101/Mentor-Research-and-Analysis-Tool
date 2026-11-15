import copy
from unittest.mock import patch
import unittest
import test_workflow
from crawler import opportunity_util


class PlanTransferAPITests(unittest.TestCase):
    setUp = test_workflow.WorkflowTests.setUp
    close_server = test_workflow.WorkflowTests.close_server
    request = test_workflow.WorkflowTests.request

    def body(self):
        return dict(kind='target',item=dict(id='goal_api',path='recommend',year=2028,schools=[dict(id='pku',name='北京大学')],interest='系统',created_at='2026-11-15'),
            target=None,school_id='pku',name='隔离转换项目',notes='个人备注',todos=[dict(id='todo_api',title='准备成绩单',done=False,due_date='2026-12-01',target_id='goal_api',created_at='2026-11-15')])

    def test_atomic_save_backup_restore_and_repeat_keep_original_progress(self):
        catalog=opportunity_util.load(self.serve.ROOT)
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            code,saved=self.request('/api/workflow/browser-transfer',self.body(),'POST')
            self.assertEqual(code,200,saved)
            workflow=self.request('/api/workflow')[1];project=workflow['projects'][saved['project_id']]
            self.assertIsNone(project['year']);self.assertEqual(len(workflow['reminders']),1)
            self.assertEqual(self.request('/api/workflow/projects/'+project['id'],{'notes':'edited later'},'PATCH')[0],200)
            before=self.outreach.with_name('workflow.yaml').read_bytes()
            code,repeated=self.request('/api/workflow/browser-transfer',self.body(),'POST')
            self.assertEqual(code,200);self.assertTrue(repeated['duplicate'])
            self.assertEqual(self.outreach.with_name('workflow.yaml').read_bytes(),before)
            backup=self.request('/api/workflow/backup')[1]
            self.assertEqual(self.request('/api/workflow/restore',backup,'POST')[0],200)
            restored=self.request('/api/workflow')[1]
            self.assertEqual(restored['projects'][project['id']]['notes'],'edited later')
            self.assertEqual(len(restored['reminders']),1)

    def test_invalid_transfer_never_creates_half_project(self):
        catalog=opportunity_util.load(self.serve.ROOT)
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            for change in (lambda b:b.update(school_id='unknown'),lambda b:b['todos'][0].update(target_id='wrong'),lambda b:b['todos'][0].update(due_date='bad')):
                body=self.body();change(body)
                self.assertEqual(self.request('/api/workflow/browser-transfer',body,'POST')[0],400)
                self.assertFalse(self.outreach.with_name('workflow.yaml').exists())
