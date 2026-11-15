"""Maintainer automation/alerts/source actions preserve evidence and loopback boundaries."""
import hashlib
import json
from unittest.mock import patch

import yaml
import unittest
import threading
from crawler import maintenance_push, opportunity_review as review, source_discovery
from scripts import serve_review
import test_review_dashboard as legacy


class AutomationDashboardTests(unittest.TestCase):
    setUp = legacy.DashboardTests.setUp
    body = legacy.DashboardTests.body
    def test_summary_reads_public_operation_outputs_not_secret_configuration(self):
        secret = self.root / 'var/ai/config.json'
        secret.parent.mkdir(parents=True)
        secret.write_text('{"api_key":"private-secret-sentinel"}', encoding='utf8')
        review.atomic_json(self.root / 'cache/automatic-review.json', dict(version=1, mode='publish', completed_at='2026-11-15T00:00:00+00:00', counts={'manual_required':1}, errors=['AI服务HTTP 503'], private='must-not-return'))
        review.atomic_json(self.root / 'cache/review-pipeline.json', dict(status='partial', failures={'automatic':'AI服务HTTP 503'}, private='must-not-return'))
        d = review.read_queue(self.queue)
        d['drafts'][0]['automatic_review'] = dict(state='manual_required', reasons=['材料缺少证据'], checked_at='2026-11-15T00:00:00+00:00')
        review.atomic_json(self.queue, d)
        result = self.dashboard.listing()
        self.assertEqual(result['automation']['counts']['manual_required'], 1)
        self.assertEqual(result['pipeline']['status'], 'partial')
        self.assertEqual(result['drafts'][0]['automatic_review']['state'], 'manual_required')
        self.assertIn('due_at', result['drafts'][0]['queue'])
        self.assertNotIn('private-secret-sentinel', json.dumps(result))
        self.assertNotIn('must-not-return', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_manual_save_preserves_uneditable_evidence_and_sets_explicit_protection(self):
        q = review.read_queue(self.queue); d = q['drafts'][0]
        mapping = dict(quote='面向2028届本科毕业生', source_url=self.url, locator='正文申请对象', content_sha256=d['fetch']['content_sha256'])
        d['reviewed_fields'] = {'research_directions':mapping}
        review.atomic_json(self.queue, q)
        original = self.dashboard.detail(self.id)
        saved = self.dashboard.mutate(self.id, 'save', dict(revision=original['revision'], item={'title':'仅调整标题'}, quotes=original['quotes'], reviewed_fields={}))
        self.assertEqual(saved['reviewed_fields']['research_directions'], mapping)
        self.assertEqual(self.dashboard.find(self.id)['manual_edit']['action'], 'save')
        with self.assertRaisesRegex(ValueError, '不能修改'):
            self.dashboard.mutate(self.id, 'save', self.body(item={}, quotes=original['quotes'], reviewed_fields={'research_directions':dict(mapping, quote='偷换证据')}))

    def test_missing_automation_record_is_not_reported_as_success(self):
        result = self.dashboard.listing()
        self.assertFalse(result['automation']['available'])
        self.assertIsNone(result['pipeline'])
        self.assertEqual(result['sources']['candidates'], [])
        self.assertEqual(result['alerts']['active'], [])


class SourceActionServerTests(unittest.TestCase):
    body = legacy.DashboardTests.body
    request = legacy.ReviewServerTests.request

    def setUp(self):
        legacy.DashboardTests.setUp(self)
        (self.root/'site').mkdir()
        (self.root/'site/review.html').write_text('local review', encoding='utf8')
        self.server = serve_review.make_server(self.root, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = f'127.0.0.1:{self.server.server_port}'

    def source_fixture(self):
        raw = '<html><title>计算机科研实践栏目</title><a href="camp2.htm">2027年大学生冬令营报名通知</a></html>'.encode()
        url = 'https://cs.example.edu.cn/research.htm'
        candidate = dict(id='new-source', url=url, label='科研实践', school='example', dept='', unit='示例大学科研实践', parent_url=self.listing, parent_label='已配置官方栏目', first_seen='2026-11-15T00:00:00+00:00', checked_at='2026-11-15T00:00:00+00:00', status='candidate', kind='column', reason='同机构候选', **source_discovery.inspect(raw, url))
        review.atomic_json(self.root/'cache/source-discovery.json', dict(version=1, checked_at=candidate['checked_at'], candidates=[candidate]))
        return candidate, raw

    def test_source_approval_requires_same_origin_token_and_current_version(self):
        candidate, raw = self.source_fixture()
        original = (self.root/'sites/opportunities.yaml').read_bytes()
        token = json.loads(self.request()[1])['token']
        body = dict(id=candidate['id'], action='approve', confirmed=True, sha256=candidate['source_sha256'])
        headers = {'Content-Type':'application/json', 'Origin':'http://'+self.host, 'X-Review-Token':token}
        self.assertEqual(self.request('/api/review/source-action', 'POST', body, {**headers, 'X-Review-Token':'bad'})[0], 403)
        self.assertEqual((self.root/'sites/opportunities.yaml').read_bytes(), original)
        parent = '<meta charset="utf-8"><a href="research.htm">科研实践</a>'.encode()
        with patch.object(source_discovery, 'fetch_html', side_effect=lambda url,*_: parent if url==self.listing else raw):
            stale = dict(body, sha256='a'*64)
            self.assertEqual(self.request('/api/review/source-action', 'POST', stale, headers)[0], 400)
            status, answer, _ = self.request('/api/review/source-action', 'POST', body, headers)
        self.assertEqual(status, 200, answer)
        self.assertEqual(json.loads(answer)['candidates'][0]['status'], 'approved')
        config = yaml.safe_load((self.root/'sites/opportunities.yaml').read_text(encoding='utf8'))
        self.assertEqual(len(config['targets']), 2)
        self.assertFalse((self.root/'data/opportunities.json').exists())
        backup = self.root/'cache/source-discovery-backups'/(hashlib.sha256(original).hexdigest()+'.yaml')
        self.assertEqual(backup.read_bytes(), original)

    def test_reject_failed_candidate_never_changes_monitoring_config(self):
        candidate, _ = self.source_fixture()
        data = source_discovery.read(self.root);data['candidates'][0].update(status='error', source_sha256=None)
        review.atomic_json(self.root/'cache/source-discovery.json', data)
        original = (self.root/'sites/opportunities.yaml').read_bytes()
        result = self.dashboard.source_action(candidate['id'], dict(action='reject', confirmed=True, sha256=None))
        self.assertEqual(result['candidates'][0]['status'], 'rejected')
        self.assertEqual((self.root/'sites/opportunities.yaml').read_bytes(), original)

    def test_maintainer_push_routes_require_same_origin_token_and_separate_payload(self):
        token = json.loads(self.request()[1])['token']
        headers = {'Content-Type':'application/json', 'Origin':'http://'+self.host, 'X-Review-Token':token}
        with patch.object(maintenance_push, 'settings', return_value=dict(enabled=False, public_key=None)):
            self.assertFalse(json.loads(self.request('/api/review/notifications')[1])['enabled'])
            self.assertEqual(self.request('/api/review/notifications', headers={'Origin':'https://evil.example'})[0],403)
        for action, function in [('subscribe','subscribe'),('unsubscribe','unsubscribe'),('test','test_notification')]:
            payload = {'id':'subscriber-id','token':'subscriber-token'}
            body = dict(id='notifications',action='notifications_'+action,payload=payload)
            with patch.object(maintenance_push, function, return_value=dict(ok=True)) as target:
                self.assertEqual(self.request('/api/review/action','POST',body,{**headers,'X-Review-Token':'bad'})[0],403)
                target.assert_not_called()
                self.assertEqual(self.request('/api/review/action','POST',body,headers)[0],200)
                target.assert_called_once_with(self.root,payload)
        self.assertEqual(self.request('/api/review/action','POST',dict(id='notifications',action='notifications_test'),headers)[0],400)
        self.assertFalse((self.root/'var/push/alerts.sqlite').exists())
