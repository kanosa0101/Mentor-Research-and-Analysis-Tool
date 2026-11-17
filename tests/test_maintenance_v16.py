import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from crawler import opportunity_monitor as monitor, opportunity_review as review, pipeline_metrics
from crawler import ai_evidence as ai, ai_transport
import test_push_util


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'live.json'
        self.now=datetime(2026,11,15,0,tzinfo=timezone.utc)
        self.cfg=dict(school='demo',dept='cs',url='https://demo.edu.cn/list',selector='li a',title_selector='self')
        self.html='<li><a href="/camp">2027冬令营报名</a></li>'

    def test_current_hourly_ordinary_six_hour_and_history_daily(self):
        cfgs=[dict(self.cfg,source_id='current',priority='current'),dict(self.cfg,source_id='normal'),dict(self.cfg,source_id='history',priority='historical')]
        seen=[]
        def fetch(c):seen.append(c['source_id']);return self.html
        first=monitor.run_once(cfgs,self.path,fetcher=fetch,now=self.now,scheduled=True)
        self.assertEqual(first['next_check_at'],(self.now+timedelta(hours=1)).isoformat(timespec='seconds'))
        seen.clear()
        result=monitor.run_once(cfgs,self.path,fetcher=fetch,now=self.now+timedelta(hours=1),scheduled=True)
        self.assertEqual(seen,['current']);self.assertEqual(result['summary']['sources_skipped'],2)
        self.assertEqual(len(result['sources']),3)

    def test_failure_backoff_preserves_evidence_and_force_can_recheck(self):
        first=monitor.run_once([self.cfg],self.path,fetcher=lambda _:self.html,now=self.now)
        later=self.now+timedelta(hours=6)
        failed=monitor.run_once([self.cfg],self.path,fetcher=lambda _:'',now=later,scheduled=True)
        self.assertEqual(failed['sources']['demo/cs']['next_check_at'],(later+timedelta(hours=12)).isoformat(timespec='seconds'))
        self.assertEqual(failed['candidates'][0]['last_seen'],first['candidates'][0]['last_seen'])
        with patch.object(monitor,'fetch_source',side_effect=AssertionError('not due')):
            skipped=monitor.run_once([self.cfg],self.path,fetcher=lambda _:self.fail('not due'),now=later+timedelta(hours=1),scheduled=True)
        self.assertEqual(skipped['summary']['sources_attempted'],0)
        fresh=monitor.run_once([self.cfg],self.path,fetcher=lambda _:self.html,now=later+timedelta(hours=1),scheduled=False)
        self.assertEqual(fresh['sources']['demo/cs']['consecutive_failures'],0)

    def test_partial_parser_drop_does_not_mark_old_entries_disappeared(self):
        many=''.join(f'<li><a href="/camp{i}">冬令营报名{i}</a></li>' for i in range(20))
        first=monitor.run_once([self.cfg],self.path,fetcher=lambda _:many,now=self.now)
        second=monitor.run_once([self.cfg],self.path,fetcher=lambda _:self.html,now=self.now+timedelta(hours=6))
        self.assertEqual(second['summary']['sources_error'],1)
        self.assertEqual(second['sources']['demo/cs']['last_success'],first['sources']['demo/cs']['last_success'])
        self.assertTrue(all(c['seen_in_latest_list'] for c in second['candidates']))

    def test_per_host_throttle_does_not_delay_other_hosts(self):
        clock=[0.0];wait=[]
        def sleep(seconds):wait.append(seconds);clock[0]+=seconds
        fetch=monitor.DomainThrottle(lambda c:c['url'],1,lambda:clock[0],sleep)
        fetch({'url':'https://a.edu.cn/1'});fetch({'url':'https://b.edu.cn/1'});fetch({'url':'https://a.edu.cn/2'})
        self.assertEqual(wait,[1])

    def test_duplicate_source_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'来源标识重复'):
            monitor.run_once([self.cfg,self.cfg],self.path,fetcher=lambda _:self.html)


class TriageTests(unittest.TestCase):
    def test_classification_preserves_human_claims_and_stale_version_is_invalidated(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'queue.json'
            draft=dict(id='a',source_url='https://demo.edu.cn/a',item={'title':'旧冬令营'},quotes=['人工摘录'],first_seen='2026-11-01T00:00:00+00:00',fetch={'status':'ok','sha256':'a'*64})
            path.write_text(json.dumps({'version':1,'drafts':[draft]}),encoding='utf-8')
            audit={'checked_at':'2026-11-15','candidates':[{'id':'a','classification':'historical','reason':'官方明确2026入学','source_url':draft['source_url']}]}
            self.assertEqual(review.apply_triage(path,audit),1)
            actual=review.read_queue(path)['drafts'][0]
            self.assertEqual(actual['item'],draft['item']);self.assertEqual(actual['quotes'],draft['quotes'])
            self.assertEqual(review.status(actual),'pending_review')
            self.assertEqual(review.triage(actual)['classification'],'historical')
            before=path.read_bytes()
            audit['candidates'][0]['content_sha256']='changed-content'
            with self.assertRaisesRegex(ValueError,'正文版本不一致'):review.apply_triage(path,audit)
            self.assertEqual(path.read_bytes(),before)
            actual['fetch']['sha256']='b'*64
            self.assertEqual(review.triage(actual)['classification'],'unknown')

    def test_metrics_exclude_explicitly_archived_from_active_backlog(self):
        with tempfile.TemporaryDirectory() as folder:
            base=dict(id='a',item={},first_seen='2026-11-14T00:00:00+00:00',fetch={'status':'ok'})
            q={'drafts':[base,dict(base,id='b',triage={'classification':'historical'})]}
            m=pipeline_metrics.summarize(folder,q,datetime(2026,11,15,tzinfo=timezone.utc))
            self.assertEqual(m['pending_active'],1);self.assertEqual(m['oldest_pending_seconds'],86400)
            self.assertIsNone(m['discovery_to_review_max_seconds'])


class SemanticPushTests(unittest.TestCase):
    setUp = test_push_util.PushTests.setUp
    register = test_push_util.PushTests.register
    record = test_push_util.PushTests.record
    def test_whitespace_and_order_only_change_does_not_notify(self):
        self.record();self.register()
        self.record(test_push_util.activity(materials=['简历','成绩单']))
        self.assertEqual(self.record(test_push_util.activity(materials=[' 成绩单\n','简历 '])),0)
        self.assertEqual(self.record(test_push_util.activity(materials=['简历','盖章成绩单'])),1)


class AISuggestionTests(unittest.TestCase):
    def test_unquoted_and_unsupported_claims_rejected(self):
        text='申请人应为2028届本科生，材料包括个人简历。'
        accepted=ai.validate({'suggestions':[{'field':'eligibility','value':'2028届本科生','quote':'申请人应为2028届本科生'}]},text)
        self.assertEqual(len(accepted),1)
        for row in ({'field':'eligibility','value':'无需资格限制','quote':'申请人应为2028届本科生'},
                    {'field':'deadline','value':'2026-12-31','quote':'2026-12-31'}):
            with self.assertRaises(ValueError):ai.validate({'suggestions':[row]},text)

    def test_disabled_never_calls_external_service(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(ai.os.environ,{},clear=True),patch.object(ai_transport.requests,'Session') as session:
            with self.assertRaises(ValueError):ai.suggest(folder,'https://demo.edu.cn/a','公开正文')
            session.assert_not_called()

    def test_budget_request_bounds_and_no_key_in_prompt_or_result(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(ai.os.environ,{'MENTOR_AI_ENABLED':'true','MENTOR_AI_API_KEY':'fixture-credential'},clear=True):
            settings=Path(folder)/'var/ai/config.json';settings.parent.mkdir(parents=True);settings.write_text('{"daily_limit":1}')
            with patch.object(ai_transport.requests,'Session') as factory:
                client=factory.return_value;response=client.post.return_value
                response.headers={'Content-Type':'application/json'};response.iter_content.side_effect=lambda **kwargs: iter([json.dumps(response.json.return_value).encode()])
                response.status_code=200;response.content=b'{}';response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"suggestions":[]}'}}]}
                result=ai.suggest(folder,'https://demo.edu.cn/a','公开正文'*10000)
                call=client.post.call_args.kwargs
                self.assertEqual(call['json']['max_tokens'],6000);self.assertFalse(call['allow_redirects']);self.assertEqual(call['timeout'],(10,45));self.assertTrue(call['stream']);self.assertEqual(call['json']['reasoning_effort'],'none')
                self.assertNotIn('fixture-credential',json.dumps(call['json']))
                self.assertNotIn('fixture-credential',json.dumps(result))
                self.assertEqual(result['input_chars'],18000)
                with self.assertRaisesRegex(ValueError,'每日调用上限'):ai.suggest(folder,'https://demo.edu.cn/a','公开正文')
                self.assertEqual(client.post.call_count,1)

    def test_length_finish_is_rejected_even_for_valid_json(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(ai.os.environ,{'MENTOR_AI_ENABLED':'true','MENTOR_AI_API_KEY':'fixture-credential'},clear=True),patch.object(ai_transport.requests,'Session') as factory:
            response=factory.return_value.post.return_value
            response.status_code=200;response.content=b'{}'
            response.headers={'Content-Type':'application/json'};response.iter_content.side_effect=lambda **kwargs: iter([json.dumps(response.json.return_value).encode()])
            response.json.return_value={'choices':[{'finish_reason':'length','message':{'content':'{"suggestions":[]}'}}]}
            with self.assertRaisesRegex(ValueError,'不完整'):ai.suggest(folder,'https://demo.edu.cn/a','公开正文')

    def test_extract_count_and_length_are_bounded(self):
        row={'field':'materials','value':'简历','quote':'简历'}
        with self.assertRaises(ValueError):ai.validate({'suggestions':[row]*7},'简历')
        with self.assertRaises(ValueError):ai.validate({'suggestions':[dict(row,quote='简'*301)]},'简'*301)
