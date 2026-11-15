import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from crawler import opportunity_review as review
from crawler.review_dashboard import Dashboard
from scripts import serve_review


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.queue = self.root/'cache/opportunity_review.json'
        self.url = 'https://cs.example.edu.cn/camp.htm'
        self.listing = 'https://cs.example.edu.cn/list.htm'
        self.raw = '<article><p>2027年冬令营面向2028届本科毕业生，报名截止2026年12月31日。</p></article>'.encode()
        self.configs = [dict(url=self.listing)]
        (self.root/'sites').mkdir()
        (self.root/'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=self.configs)),encoding='utf-8')
        candidate = dict(url=self.url,source=self.listing,title='2027年冬令营',school='example',dept='cs',unit='计算机学院',first_seen='2026-11-01T00:00:00+00:00',last_seen='2026-11-15T00:00:00+00:00')
        q = review.sync(dict(candidates=[candidate]),self.queue,self.configs,fetcher=lambda _:self.raw)
        d = q['drafts'][0]
        d['item'].update(kind='winter_camp',cycle='current',school_name='示例大学',eligibility=['面向2028届本科毕业生'],evidence=['官方原文逐项核验'])
        d['quotes']=['2027年冬令营面向2028届本科毕业生，报名截止2026年12月31日。']
        review.atomic_json(self.queue,q)
        self.id=d['id'];self.dashboard=Dashboard(self.root)

    def body(self, **extra):
        return dict(revision=self.dashboard.detail(self.id)['revision'],**extra)

    def test_detail_has_public_text_diff_and_no_file_locations(self):
        d=self.dashboard.detail(self.id)
        self.assertIn('2028',d['source_text'])
        self.assertEqual(d['blockers'],[])
        self.assertTrue(d['current_cycle'])
        self.assertNotIn('evidence_file',json.dumps(d))
        self.assertNotIn(str(self.root),json.dumps(d))
        self.assertIn('deadline',d['suggested_fields'])

    def test_explicit_save_accept_publish_and_stale_edit_are_separate(self):
        original=self.dashboard.detail(self.id)
        with self.assertRaisesRegex(ValueError,'明确勾选'):
            self.dashboard.mutate(self.id,'accept',self.body(fields=[]))
        accepted=self.dashboard.mutate(self.id,'accept',self.body(fields=['deadline']))
        self.assertEqual(accepted['item']['deadline'],'2026-12-31')
        self.assertFalse((self.root/'data/opportunities.json').exists())
        with self.assertRaisesRegex(ValueError,'其他操作'):
            self.dashboard.mutate(self.id,'save',dict(revision=original['revision'],item={'title':'stale'}))
        with self.assertRaisesRegex(ValueError,'明确确认'):
            self.dashboard.mutate(self.id,'publish',self.body())
        with patch.object(review,'fetch_source',return_value=self.raw):
            result=self.dashboard.mutate(self.id,'publish',self.body(confirmed=True,sha256=accepted['source_sha256'],reviewer='测试',note='逐项核验'))
        self.assertEqual(result['status'],'published')
        self.assertTrue((self.root/'data/opportunities.json').exists())

    def test_source_managed_fields_and_changed_versions_are_not_bypassable(self):
        with self.assertRaisesRegex(ValueError,'只能编辑'):
            self.dashboard.mutate(self.id,'save',self.body(item={'source_state':'verified'}))
        before=self.dashboard.detail(self.id)
        with patch.object(review,'fetch_source',return_value=self.raw.replace(b'31',b'30')):
            with self.assertRaisesRegex(ValueError,'SHA'):
                self.dashboard.mutate(self.id,'publish',self.body(confirmed=True,sha256=before['source_sha256'],reviewer='测试',note='测试'))
        self.assertFalse((self.root/'data/opportunities.json').exists())
        self.assertEqual(self.dashboard.detail(self.id)['item'],before['item'])

    def test_stale_revision_is_checked_inside_original_accept_and_publish_locks(self):
        d=self.dashboard.find(self.id)
        stale=review.item_hash(d)
        self.dashboard.mutate(self.id,'save',dict(revision=stale,item={'title':'另一个窗口已编辑'},quotes=d['quotes'],reviewed_fields={}))
        with self.assertRaisesRegex(ValueError,'其他操作'):
            review.accept(self.queue,self.id,['deadline'],expected_revision=stale)
        with self.assertRaisesRegex(ValueError,'其他操作'):
            review.publish(self.queue,self.id,self.root,self.configs,acknowledged_hash=d['fetch']['sha256'],reviewer='test',note='test',expected_revision=stale)

    def test_private_or_tampered_evidence_paths_are_never_read(self):
        d=self.dashboard.find(self.id)
        self.assertRaises(ValueError,self.dashboard.evidence,'../../private','.html')
        path=self.queue.parent/'opportunity_evidence'/(d['fetch']['sha256']+'.html')
        path.write_bytes(b'private sentinel')
        detail=self.dashboard.detail(self.id)
        self.assertNotIn('private sentinel',json.dumps(detail))
        self.assertTrue(detail['blockers'])

    def test_pdf_diff_uses_version_bound_cache_and_reports_missing_old_evidence(self):
        q=review.read_queue(self.queue);d=q['drafts'][0]
        old_raw=b'%PDF-old-evidence';old_hash=hashlib.sha256(old_raw).hexdigest();url='https://cs.example.edu.cn/camp.pdf'
        old_path=self.queue.parent/'opportunity_evidence'/(old_hash+'.pdf');old_path.write_bytes(old_raw)
        d['fetch']['pdfs']=[dict(url=url,sha256='a'*64,page_count=1,text_status='readable',pages=[dict(page=1,text='新的截止条件')])]
        d['review']=dict(source_sha256=d['fetch']['sha256'],content_sha256=d['fetch']['content_sha256'],item_sha256=review.item_hash(d['item']),quotes=d['quotes'],source_documents=[dict(url=url,sha256=old_hash)])
        review.atomic_json(self.queue,q)
        with patch('crawler.review_dashboard.extract.pdf_document',return_value=dict(pages=[dict(page=1,text='原截止条件')])):
            difference=self.dashboard.detail(self.id)['pdfs'][0]['difference']
        self.assertIn('-原截止条件',difference)
        self.assertIn('+新的截止条件',difference)
        old_path.unlink()
        self.assertIn('不可读取',self.dashboard.detail(self.id)['pdfs'][0]['difference'])

    def test_html_is_plain_text_and_historical_title_year_never_becomes_graduation(self):
        q=review.read_queue(self.queue);d=copy.deepcopy(q['drafts'][0]);d['id']='other';d['item'].update(title='2027年推免',cycle='historical',graduation_year=None);d['suggestions'].pop('graduation_year',None);q['drafts'].append(d);review.atomic_json(self.queue,q)
        rows=self.dashboard.listing()['drafts']
        historical=next(d for d in rows if d['id']=='other')
        self.assertFalse(historical['current_cycle'])
        self.assertIsNone(historical['graduation_year'])


class ReviewServerTests(DashboardTests):
    def setUp(self):
        super().setUp()
        (self.root/'site').mkdir()
        (self.root/'site/review.html').write_text('local review',encoding='utf-8')
        self.server=serve_review.make_server(self.root,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host=f'127.0.0.1:{self.server.server_port}'

    def request(self, path='/api/review', method='GET', body=None, headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        c.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers or {})
        response=c.getresponse();result=(response.status,response.read(),dict(response.getheaders()));c.close();return result

    def test_loopback_host_origin_token_and_explicit_route_guards(self):
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        status,raw,headers=self.request();self.assertEqual(status,200)
        token=json.loads(raw)['token']
        self.assertEqual(headers['X-Frame-Options'],'DENY')
        for bad in ({'Host':'evil.example'},{'Origin':'https://evil.example'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request(headers=bad)[0],403)
        for path in ('/var/push.json','/data/workflow.yaml','/cache/opportunity_review.json','/../site/review.html','/api/workflow'):
            self.assertEqual(self.request(path)[0],404)
        body=dict(id=self.id,action='save',**self.body(item={'title':'edited'},quotes=[],reviewed_fields={}))
        base={'Content-Type':'application/json','Origin':'http://'+self.host,'X-Review-Token':token}
        for bad in ({**base,'Origin':'null'},{**base,'X-Review-Token':'wrong'},{k:v for k,v in base.items() if k!='Origin'}):
            self.assertEqual(self.request('/api/review/action','POST',body,bad)[0],403)
        self.assertEqual(self.request('/api/review/action','POST',body,base)[0],200)
        self.assertEqual(self.request('/api/review/action','POST',body,base)[0],409)


if __name__=='__main__':
    unittest.main()
