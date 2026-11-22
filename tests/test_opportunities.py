import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import unittest
import json
import tempfile
from pathlib import Path

import test_applications
from crawler import opportunity_util as opportunities


class OpportunityTests(unittest.TestCase):
    setUp = test_applications.ApplicationTests.setUp
    close_server = test_applications.ApplicationTests.close_server
    request = test_applications.ApplicationTests.request

    def catalog(self):
        item = copy.deepcopy(next(row for row in opportunities.load(self.serve.ROOT)['opportunities']
            if opportunities.content_scope(row) == 'institutional_activity' and row['kind'] == 'winter_camp' and row['cycle'] == 'current'))
        item.update(source_state='verified', cycle='current', checked_at=opportunities.today().isoformat(),
                    verified_at=opportunities.today().isoformat(), registration_start=opportunities.today().isoformat(),
                    deadline=(opportunities.today()+timedelta(days=10)).isoformat())
        return {'version': 1, 'opportunities': [item]}

    def test_atomic_save_snapshot_reminder_duplicate_backup_and_later_edit(self):
        catalog=self.catalog();item=catalog['opportunities'][0]
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            body=dict(opportunity_id=item['id'],name='我的冬令营',reminder_date=opportunities.today().isoformat())
            code,result=self.request('/api/workflow/opportunities',body,'POST')
            self.assertEqual(code,200,result)
            pid=result['project_id'];data=self.request('/api/workflow')[1]
            self.assertEqual(data['projects'][pid]['opportunity'],item)
            self.assertIsNone(data['projects'][pid]['year'])
            self.assertEqual(data['projects'][pid]['route'],'')
            self.assertEqual(len(data['reminders']),1)
            self.assertTrue(self.request('/api/workflow/opportunities',body,'POST')[1]['duplicate'])
            self.assertEqual(len(self.request('/api/workflow')[1]['reminders']),1)
            self.assertEqual(self.request('/api/workflow/projects/'+pid,{'notes':'个人备注'},'PATCH')[0],200)
            self.assertEqual(self.request('/api/workflow')[1]['projects'][pid]['opportunity'],item)
            backup=self.request('/api/workflow/backup')[1]
            self.assertEqual(self.request('/api/workflow/restore',backup,'POST')[0],200)
            self.assertEqual(self.request('/api/workflow')[1]['projects'][pid]['opportunity'],item)

    def test_invalid_date_cannot_leave_half_created_project(self):
        catalog=self.catalog();item=catalog['opportunities'][0]
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            yesterday=(opportunities.today()-timedelta(days=1)).isoformat()
            code,_=self.request('/api/workflow/opportunities',dict(opportunity_id=item['id'],name='冬令营',reminder_date=yesterday),'POST')
            self.assertEqual(code,400)
            self.assertFalse(self.outreach.with_name('workflow.yaml').exists())
            self.assertEqual(self.request('/api/workflow')[1]['projects'],{})

    def test_lost_save_response_can_be_confirmed_after_the_reminder_date(self):
        catalog=self.catalog();item=catalog['opportunities'][0]
        day=opportunities.today()
        body=dict(opportunity_id=item['id'],name='我的冬令营',reminder_date=day.isoformat())
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            code,created=self.request('/api/workflow/opportunities',body,'POST')
            self.assertEqual(code,200,created)
            original=self.request('/api/workflow')[1]
            with patch.object(opportunities,'today',return_value=day+timedelta(days=1)):
                code,retry=self.request('/api/workflow/opportunities',body,'POST')
                self.assertEqual(code,200,retry)
                self.assertEqual(retry,{'project_id':created['project_id'],'duplicate':True})
                code,retry=self.request('/api/workflow/opportunities',dict(body,name='不要覆盖原项目'),'POST')
                self.assertEqual((code,retry),(200,{'project_id':created['project_id'],'duplicate':True}))
        self.assertEqual(self.request('/api/workflow')[1],original)
        self.assertEqual(len(original['projects']),1)
        self.assertEqual(len(original['reminders']),1)

    def test_existing_activity_still_checks_payload_date_format_and_registered_id(self):
        catalog=self.catalog();item=catalog['opportunities'][0]
        body=dict(opportunity_id=item['id'],name='我的冬令营',reminder_date='')
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            self.assertEqual(self.request('/api/workflow/opportunities',body,'POST')[0],200)
            original=self.request('/api/workflow')[1]
            for invalid in (dict(body,name='  '),dict(body,reminder_date='2026-02-30'),dict(body,extra=True)):
                self.assertEqual(self.request('/api/workflow/opportunities',invalid,'POST')[0],400)
        with patch.object(self.serve.opportunities,'observed',return_value=dict(catalog,opportunities=[])):
            self.assertEqual(self.request('/api/workflow/opportunities',body,'POST')[0],404)
        self.assertEqual(self.request('/api/workflow')[1],original)

    def test_pdf_evidence_survives_project_save_backup_and_restore(self):
        catalog=self.catalog();item=catalog['opportunities'][0]
        item['source_documents']=[dict(url='https://example.edu.cn/requirements.pdf',sha256='a'*64,
            page_count=2,checked_at=opportunities.today().isoformat(),
            field_evidence={'eligibility':{'quote':'申请对象为本科生','pages':[1]}})]
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            code,result=self.request('/api/workflow/opportunities',dict(opportunity_id=item['id'],name='PDF来源项目',reminder_date=''),'POST')
            self.assertEqual(code,200,result)
            backup=self.request('/api/workflow/backup')[1]
            self.assertEqual(self.request('/api/workflow/restore',backup,'POST')[0],200)
            saved=self.request('/api/workflow')[1]['projects'][result['project_id']]['opportunity']
            self.assertEqual(saved['source_documents'],item['source_documents'])

    def test_unverified_candidate_is_not_open_and_can_save_personal_review_reminder(self):
        catalog=self.catalog();item=catalog['opportunities'][0];item['source_state']='unavailable'
        self.assertEqual(opportunities.state(item),'review')
        with patch.object(self.serve.opportunities,'observed',return_value=catalog):
            code,result=self.request('/api/workflow/opportunities',dict(opportunity_id=item['id'],name='待核对活动',reminder_date=opportunities.today().isoformat()),'POST')
            self.assertEqual(code,200,result)
            reminder=next(iter(self.request('/api/workflow')[1]['reminders'].values()))
            self.assertTrue(reminder['title'].startswith('核对活动信息'))

    def test_forged_snapshot_and_invalid_restore_rejected(self):
        item=self.catalog()['opportunities'][0]
        code,_=self.request('/api/workflow/projects',{'name':'伪造','opportunity':item},'POST')
        self.assertEqual(code,400)
        self.assertFalse(self.outreach.with_name('workflow.yaml').exists())

    def test_state_expires_and_history_stays_history(self):
        item=self.catalog()['opportunities'][0]
        self.assertEqual(opportunities.state(item),'open')
        item['checked_at']=(opportunities.today()-timedelta(days=8)).isoformat()
        self.assertEqual(opportunities.state(item),'review')
        item['cycle']='historical'
        self.assertEqual(opportunities.state(item),'closed')

    def test_remote_feed_preserves_local_mode_and_caches_only_public_data(self):
        catalog=self.catalog()
        with tempfile.TemporaryDirectory() as directory, patch.object(opportunities.requests,'Session') as factory:
            response=factory.return_value.__enter__.return_value.get.return_value
            response.json.return_value=dict(catalog, mode='public', monitoring=None)
            result=opportunities.remote_catalog(directory,'http://example.org/api/opportunities')
            self.assertEqual(result['mode'],'local')
            self.assertEqual(result['opportunities'],catalog['opportunities'])
            opportunities.remote_catalog(directory,'http://example.org/api/opportunities')
            self.assertEqual(factory.call_count,1)
            self.assertFalse((Path(directory)/'data/workflow.yaml').exists())

    def test_server_catalog_ignores_retired_client_feed_even_if_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            (root/'data/opportunities.json').write_text(json.dumps(self.catalog()),encoding='utf-8')
            (root/'data/opportunity_feed.json').write_text(json.dumps({'enabled':True,'url':'http://example.org/api/opportunities'}),encoding='utf-8')
            with patch.object(opportunities,'remote_catalog',side_effect=AssertionError('server must not fetch itself')) as remote:
                result=opportunities.observed(root)
            remote.assert_not_called()
            self.assertNotIn('feed_error',result)
            self.assertEqual(result['opportunities'],self.catalog()['opportunities'])
            self.assertEqual(opportunities.state(result['opportunities'][0]),'open')

    def test_stopped_monitor_cannot_keep_claiming_registration_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir();(root/'cache').mkdir()
            catalog=self.catalog();item=catalog['opportunities'][0]
            (root/'data/opportunities.json').write_text(json.dumps(catalog),encoding='utf-8')
            (root/'cache/opportunities_live.json').write_text(json.dumps({
                'next_check_at':'2000-01-01T00:00:00+00:00',
                'opportunity_checks':{item['id']:{'status':'unchanged','last_success':item['checked_at']}}
            }),encoding='utf-8')
            result=opportunities.observed(root)
            self.assertEqual(opportunities.state(result['opportunities'][0]),'review')
            self.assertEqual(opportunities.load(root)['opportunities'][0]['source_state'],'verified')

    def test_monitor_quarter_hour_wake_does_not_flicker_current_activity(self):
        now = datetime.now(timezone(timedelta(hours=8))).replace(hour=16, minute=27, second=0, microsecond=0).astimezone(timezone.utc)
        due = now.replace(minute=15, second=16)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir();(root/'cache').mkdir()
            catalog=self.catalog();item=catalog['opportunities'][0]
            (root/'data/opportunities.json').write_text(json.dumps(catalog),encoding='utf-8')
            (root/'cache/opportunities_live.json').write_text(json.dumps({
                'next_check_at':due.isoformat(),
                'opportunity_checks':{item['id']:{'status':'unchanged','last_success':item['checked_at']}}
            }),encoding='utf-8')
            # The 16:15 wake runs just before 16:15:16; the next wake is 16:30.
            with patch.object(opportunities,'datetime',wraps=datetime) as clock:
                for moment,expected in ((now,'open'),(due+timedelta(minutes=15),'open'),
                                        (due+timedelta(minutes=15,seconds=1),'review')):
                    with self.subTest(moment=moment):
                        clock.now.return_value=moment
                        result=opportunities.observed(root)
                        self.assertEqual(opportunities.state(result['opportunities'][0]),expected)
                for invalid in ('invalid','2026-11-16T16:15:16','2027-02-30T16:15:16+08:00'):
                    with self.subTest(invalid=invalid):
                        (root/'cache/opportunities_live.json').write_text(json.dumps({'next_check_at':invalid}),encoding='utf-8')
                        self.assertEqual(opportunities.state(opportunities.observed(root)['opportunities'][0]),'review')

    def test_monitor_grace_never_hides_failure_changes_or_stale_evidence(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir();(root/'cache').mkdir()
            for status,age,review_age in [('error',0,0),('changed',0,0),('unbased',0,0),
                                         ('unchanged',8,0),('unchanged',0,31)]:
                with self.subTest(status=status,age=age,review_age=review_age):
                    catalog=self.catalog();item=catalog['opportunities'][0]
                    item['verified_at']=(opportunities.today()-timedelta(days=review_age)).isoformat()
                    last_success=(opportunities.today()-timedelta(days=age)).isoformat()
                    (root/'data/opportunities.json').write_text(json.dumps(catalog),encoding='utf-8')
                    (root/'cache/opportunities_live.json').write_text(json.dumps({
                        'next_check_at':(now-timedelta(minutes=10)).isoformat(),
                        'opportunity_checks':{item['id']:{'status':status,'last_success':last_success}}
                    }),encoding='utf-8')
                    with patch.object(opportunities,'datetime',wraps=datetime) as clock:
                        clock.now.return_value=now
                        self.assertEqual(opportunities.state(opportunities.observed(root)['opportunities'][0]),'review')


if __name__=='__main__':unittest.main()
