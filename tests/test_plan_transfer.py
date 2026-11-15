import copy
import unittest
from pathlib import Path
from crawler import plan_transfer, project_util, opportunity_util, material_task_util, workflow_util

ROOT = Path(__file__).resolve().parents[1]


class PlanTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = project_util.load_context(ROOT)
        cls.catalog = opportunity_util.load(ROOT)
        cls.known = {'pku-cs-test'}

    def data(self):
        return material_task_util.project(material_task_util.upgrade(workflow_util.empty_workflow(), self.known, self.context))

    def body(self):
        goal = dict(id='goal_one', path='recommend', year=2028, schools=[{'id':'pku','name':'北京大学'}], interest='系统安全', created_at='2026-11-15')
        return dict(kind='target', item=goal, target=None, school_id='pku', name='北大申请准备', notes='希望先了解方向', todos=[
            dict(id='todo_one', title='核对材料', done=False, due_date='2026-12-01', target_id='goal_one', created_at='2026-11-15'),
            dict(id='todo_two', title='整理研究经历', done=True, due_date='', target_id='goal_one', created_at='2026-11-15')])

    def save(self, data, body):
        return plan_transfer.save(data, body, self.known, self.context, self.catalog)

    def test_recommend_graduation_never_becomes_entry_year_and_todos_survive(self):
        before=self.data();data,result=self.save(before,self.body());project=data['projects'][result['project_id']]
        self.assertIsNone(project['year']);self.assertEqual(project['route'],'recommend')
        self.assertIn('本科毕业届别：2028',project['notes']);self.assertIn('已完成：整理研究经历',project['notes'])
        self.assertEqual(result['reminder_count'],1);reminder=next(iter(data['reminders'].values()))
        self.assertEqual(reminder['project_id'],project['id']);self.assertEqual(reminder['due_date'],'2026-12-01')
        self.assertFalse(before['projects'])

    def test_repeated_transfer_is_idempotent_and_preserves_later_manual_edit(self):
        data,result=self.save(self.data(),self.body());data['projects'][result['project_id']]['notes']='later manual edit'
        same,again=self.save(data,self.body());self.assertTrue(again['duplicate']);self.assertEqual(same,data)
        self.assertEqual(len(same['reminders']),1)

    def test_exam_keeps_entry_year(self):
        body=self.body();body['item']['path']='exam';body['item']['year']=2027
        data,result=self.save(self.data(),body);self.assertEqual(data['projects'][result['project_id']]['year'],2027)

    def test_multi_school_requires_one_explicit_choice(self):
        body=self.body();body['item']['schools'].append({'id':'tsinghua','name':'清华大学'});body['school_id']=''
        with self.assertRaises(ValueError):self.save(self.data(),body)

    def test_unknown_school_wrong_todo_and_malformed_links_reject_without_mutation(self):
        for change in (lambda b:b.update(school_id='fake'),lambda b:b['todos'][0].update(target_id='other'),lambda b:b['todos'][0].update(due_date='2026-02-30'),lambda b:b['todos'][0].update(due_date=None)):
            data=self.data();before=copy.deepcopy(data);body=self.body();change(body)
            with self.assertRaises(ValueError):self.save(data,body)
            self.assertEqual(data,before)
        for url in ('https://evil.test/p/pku-cs-test.html','p/../test.html','p/%2e%2e/test.html','javascript:alert(1)'):
            body=self.body();body.update(kind='bookmark',target=body['item'],item=dict(id='b',kind='mentor',title='导师',url=url,created_at='2026-11-15'))
            with self.assertRaises(ValueError):self.save(self.data(),body)

    def test_mentor_bookmark_creates_linked_target(self):
        body=self.body();body.update(kind='bookmark',target=body['item'],item=dict(id='b',kind='mentor',title='测试导师',url='p/pku-cs-test.html',created_at='2026-11-15'))
        data,result=self.save(self.data(),body);p=data['projects'][result['project_id']]
        self.assertEqual(p['mentor_ids'],['pku-cs-test']);self.assertEqual(p['dept_id'],'cs')
        self.assertTrue(any(t['project_id']==p['id'] and t['mentor_id']=='pku-cs-test' for t in data['targets'].values()))

    def test_opportunity_uses_catalog_snapshot_and_original_entry_year(self):
        item=self.catalog['opportunities'][0];body=self.body();body.update(kind='bookmark',target=None,school_id='',todos=[],item=dict(id='b',kind='opportunity',title='browser title',url='opportunities.html?id='+item['id'],created_at='2026-11-15'))
        data,result=self.save(self.data(),body);p=data['projects'][result['project_id']]
        self.assertEqual(p['opportunity'],item);self.assertEqual(p['year'],item['admission_year'])
        same,again=self.save(data,body);self.assertTrue(again['duplicate']);self.assertEqual(same,data)

    def test_notice_title_is_personal_reference_not_official_deadline(self):
        body=self.body();body.update(kind='bookmark',target=None,school_id='',todos=[],item=dict(id='b',kind='notice',title='通知',url='notices.html?notice_cycle=all&q=title',created_at='2026-11-15'))
        data,result=self.save(self.data(),body);p=data['projects'][result['project_id']]
        self.assertIsNone(p['year']);self.assertEqual(p['deadlines'],[]);self.assertIn('收藏页面：',p['notes'])
