import copy
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from crawler import opportunity_review as review
from crawler import opportunity_util as opportunities
from scripts import review_opportunities as cli


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.queue = self.root / 'cache/review.json'
        self.catalog = self.root / 'data/opportunities.json'
        self.url = 'https://cs.example.edu.cn/info/123.htm'
        self.listing = 'https://cs.example.edu.cn/admissions.htm'
        self.configs = [{'url': self.listing}]
        self.raw = '<html><meta charset="utf-8"><p>本次活动面向2028届本科毕业生，报名截止2026年12月31日。</p></html>'.encode('utf-8')
        self.monitoring = {'candidates': [dict(url=self.url, source=self.listing, school='example', dept='cs',
                                             unit='示例计算机学院', title='2027年冬令营',
                                             first_seen='2026-11-15T00:00:00+00:00', last_seen='2026-11-15T00:00:00+00:00')]}

    def sync(self, raw=None):
        return review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: raw or self.raw)

    def ready(self):
        queue = self.sync()
        draft = queue['drafts'][0]
        draft['item'].update(kind='winter_camp', cycle='current', school_name='示例大学',
                             eligibility=['面向2028届本科毕业生'], evidence=['原文明示面向2028届毕业生'])
        draft['quotes'] = ['本次活动面向2028届本科毕业生，报名截止2026年12月31日。']
        review.atomic_json(self.queue, queue)
        return draft

    def publish(self, draft, raw=None, **kwargs):
        return review.publish(self.queue, draft['id'], self.root, self.configs,
                              acknowledged_hash=draft['fetch']['sha256'], reviewer='维护者', note='逐项核对官方正文',
                              fetcher=lambda _: raw or self.raw, **kwargs)

    def test_sync_never_infers_claims_and_preserves_manual_edits(self):
        draft = self.ready()
        queue = self.sync()
        self.assertEqual(len(queue['drafts']), 1)
        saved = queue['drafts'][0]
        self.assertEqual(saved['item'], draft['item'])
        self.assertEqual(saved['quotes'], draft['quotes'])
        self.assertEqual(saved['first_seen'], self.monitoring['candidates'][0]['first_seen'])
        for key in opportunities.YEARS:
            self.assertIsNone(saved['item'][key])
        self.assertEqual(saved['item']['deadline'], '')
        self.assertFalse(self.catalog.exists())
        self.assertEqual(Path(saved['fetch']['evidence_file']).read_bytes(), self.raw)

    def test_explicit_publish_preserves_other_records_and_adds_audit(self):
        draft = self.ready()
        item = self.publish(draft)
        self.assertEqual(opportunities.state(item), 'unknown')
        self.assertEqual(item['source_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(item['source_content_sha256'], review.read_queue(self.queue)['drafts'][0]['fetch']['content_sha256'])
        catalog = opportunities.load(self.root)
        other = copy.deepcopy(item)
        other.update(id='other', source_url='https://cs.example.edu.cn/other.htm')
        catalog['opportunities'].append(other)
        review.atomic_json(self.catalog, catalog)
        self.publish(draft)
        catalog = opportunities.load(self.root)
        self.assertEqual(len(catalog['opportunities']), 2)
        self.assertEqual(catalog['opportunities'][1], other)
        self.assertEqual(catalog['review_log'][-1]['reviewer'], '维护者')
        self.assertEqual(catalog['review_log'][-1]['quotes'], draft['quotes'])
        self.assertEqual(review.status(review.read_queue(self.queue)['drafts'][0]), 'published')

    def test_changed_source_rejects_publication_and_requires_new_review(self):
        draft = self.ready()
        self.publish(draft)
        before = self.catalog.read_bytes()
        changed = self.raw.replace('31'.encode(), '30'.encode())
        with self.assertRaisesRegex(ValueError, 'SHA'):
            self.publish(draft, changed)
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(review.status(review.read_queue(self.queue)['drafts'][0]), 'source_changed')

    def test_failed_fetch_cannot_reuse_old_success_as_current(self):
        draft = self.ready()
        self.publish(draft)
        before = self.catalog.read_bytes()
        with self.assertRaisesRegex(ValueError, '获取失败'):
            review.publish(self.queue, draft['id'], self.root, self.configs, acknowledged_hash=draft['fetch']['sha256'],
                           reviewer='维护者', note='核验', fetcher=lambda _: (_ for _ in ()).throw(requests.Timeout()))
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(review.status(review.read_queue(self.queue)['drafts'][0]), 'source_error')

    def test_invalid_schema_or_nonmatching_quote_does_not_create_catalog(self):
        draft = self.ready()
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['item']['deadline'] = 'not-a-date'
        review.atomic_json(self.queue, queue)
        with self.assertRaises(ValueError):
            self.publish(draft)
        self.assertFalse(self.catalog.exists())
        queue['drafts'][0]['item']['deadline'] = ''
        queue['drafts'][0]['quotes'] = ['未在原文出现的条件']
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, '摘录'):
            self.publish(draft)
        self.assertFalse(self.catalog.exists())

    def test_source_registry_and_identity_are_enforced(self):
        draft = self.ready()
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['item']['source_url'] = 'https://cs.example.edu.cn/unrelated.htm'
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, '地址不一致'):
            self.publish(draft)
        self.assertFalse(self.catalog.exists())
        for url in ('https://evil.example/notice', 'javascript:alert(1)', 'https://other.edu.cn/notice'):
            with self.assertRaises(ValueError):
                review.check_source(dict(draft, source_url=url), self.configs)
        with self.assertRaisesRegex(ValueError, '配置'):
            review.check_source(draft, [])

    def test_catalog_replace_failure_keeps_existing_bytes(self):
        draft = self.ready()
        self.publish(draft)
        before = self.catalog.read_bytes()
        original = review.atomic_json
        def fail_catalog(path, value):
            if Path(path) == self.catalog:
                raise OSError('disk full')
            original(path, value)
        with patch.object(review, 'atomic_json', side_effect=fail_catalog):
            with self.assertRaises(OSError):
                self.publish(draft)
        self.assertEqual(self.catalog.read_bytes(), before)

    def test_cross_institution_redirect_is_not_official_evidence(self):
        with patch.object(review.requests, 'Session') as factory:
            response = factory.return_value.__enter__.return_value.get.return_value
            response.status_code = 200
            response.url = 'https://example.com/login'
            with self.assertRaises(ValueError):
                review.fetch_source({'url': self.url})

    def test_duplicate_source_cannot_publish_under_a_second_id(self):
        draft = self.ready()
        self.publish(draft)
        before = self.catalog.read_bytes()
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['item']['id'] = 'duplicate-id'
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, '其他活动 ID'):
            self.publish(draft)
        self.assertEqual(self.catalog.read_bytes(), before)

    def test_edit_after_publication_returns_to_pending(self):
        draft = self.ready()
        self.publish(draft)
        saved = review.read_queue(self.queue)['drafts'][0]
        self.assertEqual(review.status(saved), 'published')
        saved['quotes'].append('新增待核验摘录')
        self.assertEqual(review.status(saved), 'pending_review')

    def test_sync_reuses_recent_success_and_refreshes_after_24h(self):
        now = datetime(2026, 11, 15, 0, tzinfo=timezone.utc)
        fetch = Mock(return_value=self.raw)
        first = review.sync(self.monitoring, self.queue, self.configs, fetcher=fetch, now=now)
        self.assertEqual(first['summary'], dict(total=1, new=1, fetched=1, reused=0, source_errors=0, needs_pdf_review=0))
        fetch.reset_mock()
        recent = review.sync(self.monitoring, self.queue, self.configs, fetcher=fetch, now=now + timedelta(hours=6))
        fetch.assert_not_called()
        self.assertEqual(recent['summary']['reused'], 1)
        self.assertEqual(recent['drafts'][0]['fetch']['checked_at'], first['drafts'][0]['fetch']['checked_at'])
        stale = review.sync(self.monitoring, self.queue, self.configs, fetcher=fetch, now=now + timedelta(hours=24))
        fetch.assert_called_once()
        self.assertEqual(stale['summary']['fetched'], 1)

    def test_refresh_bypasses_cache_and_failed_sources_retry_early(self):
        now = datetime(2026, 11, 15, 0, tzinfo=timezone.utc)
        review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: self.raw, now=now)
        fail = Mock(side_effect=requests.Timeout('timeout'))
        failed = review.sync(self.monitoring, self.queue, self.configs, fetcher=fail, refresh=True, now=now)
        fail.assert_called_once()
        self.assertEqual(failed['summary']['source_errors'], 1)
        retry = Mock(return_value=self.raw)
        recovered = review.sync(self.monitoring, self.queue, self.configs, fetcher=retry, now=now)
        retry.assert_called_once()
        self.assertEqual(recovered['summary']['source_errors'], 0)

    def test_column_migration_preserves_manual_item_and_first_seen(self):
        draft = self.ready()
        new_listing = 'https://cs.example.edu.cn/new-admissions.htm'
        migrated = copy.deepcopy(self.monitoring)
        migrated['candidates'][0].update(source=new_listing, first_seen='2026-11-16T00:00:00+00:00')
        queue = review.sync(migrated, self.queue, [{'url': new_listing}], fetcher=lambda _: self.raw)
        result = queue['drafts'][0]
        self.assertEqual(result['listing_url'], new_listing)
        self.assertEqual(result['first_seen'], draft['first_seen'])
        self.assertEqual(result['item'], draft['item'])
        self.assertEqual(result['quotes'], draft['quotes'])
        self.assertEqual(queue['summary']['source_errors'], 0)

    def test_sync_partial_failure_saves_successes_and_cli_returns_nonzero(self):
        candidate = copy.deepcopy(self.monitoring['candidates'][0])
        candidate['url'] = 'https://cs.example.edu.cn/unavailable.htm'
        monitoring = dict(candidates=[self.monitoring['candidates'][0], candidate])
        def fetch(config):
            if config['url'].endswith('unavailable.htm'):
                raise requests.Timeout('timeout')
            return self.raw
        queue = review.sync(monitoring, self.queue, self.configs, fetcher=fetch)
        self.assertEqual(queue['summary'], dict(total=2, new=2, fetched=2, reused=0, source_errors=1, needs_pdf_review=0))
        self.assertEqual(review.read_queue(self.queue), queue)
        self.assertEqual(queue['drafts'][0]['fetch']['status'], 'ok')
        config_path = self.root / 'config.json'
        config_path.write_text(json.dumps({'targets': self.configs}), encoding='utf-8')
        monitoring_path = self.root / 'monitoring.json'
        monitoring_path.write_text(json.dumps(monitoring), encoding='utf-8')
        with patch.object(cli.review, 'sync', return_value=queue) as run, patch('sys.stdout', new_callable=io.StringIO) as output:
            result = cli.main(['--config', str(config_path), '--monitoring', str(monitoring_path),
                               '--queue', str(self.queue), 'sync', '--refresh'])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())['summary']['source_errors'], 1)
        self.assertTrue(run.call_args.kwargs['refresh'])

    def test_suggestions_are_separate_and_accept_is_explicit(self):
        queue = self.sync()
        draft = queue['drafts'][0]
        self.assertEqual(draft['suggestions']['deadline'], '2026-12-31')
        self.assertEqual(draft['item']['deadline'], '')
        self.assertEqual(review.accept(self.queue, draft['id'], ['deadline']), ['deadline'])
        saved = review.read_queue(self.queue)['drafts'][0]
        self.assertEqual(saved['item']['deadline'], '2026-12-31')
        self.assertEqual(saved['reviewed_fields']['deadline']['source_url'], self.url)
        self.assertFalse(self.catalog.exists())
        self.assertEqual(review.accept(self.queue, draft['id'], ['deadline']), [])

    def test_unsupported_inferred_day_and_unmapped_claim_cannot_publish(self):
        draft = self.ready()
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['item']['deadline'] = '2027-01-31'
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, 'deadline.*证据'):
            self.publish(draft)
        self.assertFalse(self.catalog.exists())
        queue['drafts'][0]['item']['deadline'] = ''
        queue['drafts'][0]['item']['materials'] = ['报名时必须提交两封推荐信']
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, 'materials.*证据'):
            self.publish(draft)

    def test_error_page_cannot_be_reviewed_evidence(self):
        queue = self.sync(b'<title>Access Denied</title><p>please verify</p>')
        self.assertEqual(queue['drafts'][0]['fetch']['status'], 'error')
        self.assertFalse(self.catalog.exists())

    def test_deadline_time_cannot_be_changed_or_discarded_by_a_day_only_quote(self):
        self.raw = '<html><meta charset="utf-8"><p>本次活动面向2028届本科毕业生，报名截止2026年12月31日14:30。</p></html>'.encode()
        draft = self.ready()
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['quotes'] = ['本次活动面向2028届本科毕业生，报名截止2026年12月31日14:30。']
        for value in ('2026-12-31', '2026-12-31T15:30:00+08:00'):
            queue['drafts'][0]['item']['deadline'] = value
            review.atomic_json(self.queue, queue)
            with self.assertRaisesRegex(ValueError, 'deadline.*证据'):
                self.publish(draft)
        queue['drafts'][0]['item']['deadline'] = '2026-12-31T14:30:00+08:00'
        review.atomic_json(self.queue, queue)
        self.assertEqual(self.publish(draft)['deadline'], '2026-12-31T14:30:00+08:00')

    def test_layout_only_recheck_preserves_manual_review_and_never_publishes_new_drafts(self):
        self.raw = b'<article><p>' + '本次活动面向2028届本科毕业生，报名截止2026年12月31日。'.encode() + b'</p><span class="views">123</span></article>'
        draft = self.ready()
        self.publish(draft)
        before = opportunities.load(self.root)['opportunities'][0]
        changed = self.raw.replace(b'123', b'456')
        queue = review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: changed, refresh=True)
        self.assertEqual(review.status(queue['drafts'][0]), 'published')
        self.assertEqual(review.renew(self.queue, self.root), [before['id']])
        after = opportunities.load(self.root)['opportunities'][0]
        self.assertEqual(after['verified_at'], before['verified_at'])
        self.assertEqual(after['eligibility'], before['eligibility'])
        self.assertNotEqual(after['source_sha256'], before['source_sha256'])
        self.assertEqual(after['source_content_sha256'], before['source_content_sha256'])
        self.assertEqual(review.renew(self.queue, self.root), [])
        substantive = changed.replace(b'31', b'30')
        review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: substantive, refresh=True)
        self.assertEqual(review.renew(self.queue, self.root), [])
        self.assertEqual(opportunities.load(self.root)['opportunities'][0], after)

    def test_embedded_pdf_preserves_html_hash_and_never_passes_html_publication(self):
        from pypdf import PdfWriter
        stream = io.BytesIO();writer = PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(stream)
        pdf = stream.getvalue()
        raw = b'<article><script>showVsbpdfIframe("/camp.pdf","100%","600");</script></article>'
        queue = review.sync(self.monitoring,self.queue,self.configs,fetcher=lambda _:raw,pdf_fetcher=lambda *_:pdf)
        draft = queue['drafts'][0]
        self.assertEqual(draft['fetch']['status'],'pdf_review')
        self.assertEqual(draft['fetch']['sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(draft['fetch']['pdfs'][0]['sha256'],hashlib.sha256(pdf).hexdigest())
        self.assertEqual(draft['fetch']['pdfs'][0]['text_status'],'no_text')
        self.assertEqual(queue['summary']['needs_pdf_review'],1)
        self.assertEqual(queue['summary']['source_errors'],0)
        self.assertEqual(review.status(draft),'needs_pdf_review')
        self.assertEqual(review.renew(self.queue,self.root),[])
        with patch.object(review.requests,'Session') as session:
            response=session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.status_code=200;response.headers={};response.iter_content.return_value=[pdf]
            with self.assertRaisesRegex(ValueError,'PDF.*发布门禁'):
                review.publish(self.queue,draft['id'],self.root,self.configs,acknowledged_hash=draft['fetch']['sha256'],reviewer='核验',note='PDF',fetcher=lambda _:raw)
        self.assertFalse(self.catalog.exists())

    def test_external_pdf_is_rejected_before_request_and_size_bound_is_enforced(self):
        fetch=Mock()
        raw=b'<article><script>showVsbpdfIframe("https://other.edu.cn/a.pdf");</script></article>'
        queue=review.sync(self.monitoring,self.queue,self.configs,fetcher=lambda _:raw,pdf_fetcher=fetch)
        fetch.assert_not_called()
        self.assertEqual(queue['summary']['source_errors'],1)
        with patch.object(review.requests,'Session') as session, patch.object(review.extraction,'MAX_PDF_BYTES',8):
            response=session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.status_code=200;response.headers={};response.iter_content.return_value=[b'%PDF-1.7',b'extra']
            with self.assertRaisesRegex(ValueError,'上限'):
                review.fetch_pdf('https://cs.example.edu.cn/a.pdf',self.url)

    def test_pdf_redirect_cannot_leave_institution(self):
        with patch.object(review.requests,'Session') as session:
            response=session.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            response.status_code=302;response.headers={'Location':'https://evil.example/a.pdf'}
            with self.assertRaises(ValueError):
                review.fetch_pdf('https://cs.example.edu.cn/a.pdf',self.url)
            self.assertEqual(session.return_value.__enter__.return_value.get.call_count,1)

    def pdf_ready(self):
        self.pdf_raw = b'%PDF-1.7 reviewed version'
        self.pdf_url = 'https://cs.example.edu.cn/camp.pdf'
        self.raw = b'<article><script>showVsbpdfIframe("/camp.pdf");</script><span class="views">1</span></article>'
        self.pdf_text = '本次活动面向2028届本科毕业生，报名截止2026年12月31日。'
        parsed = dict(pages=[dict(page=1, text=self.pdf_text), dict(page=2, text='申请材料：本科成绩单。')],
                      page_count=2, text_status='readable', suggestions={}, field_evidence={}, warnings=[])
        patcher = patch.object(review.extraction, 'pdf_document', return_value=parsed)
        patcher.start(); self.addCleanup(patcher.stop)
        queue = review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: self.raw,
                            pdf_fetcher=lambda *_: self.pdf_raw)
        draft = queue['drafts'][0]
        draft['item'].update(kind='winter_camp', cycle='current', school_name='示例大学', deadline='2026-12-31',
                             eligibility=['面向2028届本科毕业生'], materials=['本科成绩单'], evidence=['PDF第1、2页逐项核验'])
        draft['quotes'] = [self.pdf_text, '申请材料：本科成绩单。']
        draft['reviewed_fields'] = {field:dict(quote=quote, source_url=self.pdf_url, pages=[page]) for field,quote,page in
                                   [('deadline',self.pdf_text,1),('eligibility',self.pdf_text,1),('materials','申请材料：本科成绩单。',2)]}
        review.atomic_json(self.queue, queue)
        return draft

    def publish_pdf(self, draft, **kwargs):
        return self.publish(draft, pdf_fetcher=lambda *_: self.pdf_raw,
                            acknowledged_pdf_hashes=[draft['fetch']['pdfs'][0]['sha256']], **kwargs)

    def test_pdf_publish_records_pages_versions_and_renews_only_reviewed_unchanged_facts(self):
        draft = self.pdf_ready()
        item = self.publish_pdf(draft)
        doc = item['source_documents'][0]
        self.assertEqual(doc['sha256'], hashlib.sha256(self.pdf_raw).hexdigest())
        self.assertEqual(doc['field_evidence']['materials']['pages'], [2])
        self.assertEqual(item['source_sha256'], hashlib.sha256(self.raw).hexdigest())
        self.assertNotEqual(item['source_sha256'], doc['sha256'])
        self.assertEqual(review.status(review.read_queue(self.queue)['drafts'][0]), 'published')
        self.raw = self.raw.replace(b'>1<', b'>2<')
        refreshed = review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: self.raw,
                               pdf_fetcher=lambda *_: self.pdf_raw, refresh=True)
        self.assertEqual(refreshed['summary']['needs_pdf_review'], 0)
        self.assertEqual(review.renew(self.queue, self.root), [item['id']])
        renewed = opportunities.load(self.root)['opportunities'][0]
        self.assertEqual(renewed['verified_at'], item['verified_at'])
        self.assertEqual(renewed['source_documents'], item['source_documents'])
        self.pdf_raw += b' changed deadline'
        queue = review.sync(self.monitoring, self.queue, self.configs, fetcher=lambda _: self.raw,
                            pdf_fetcher=lambda *_: self.pdf_raw, refresh=True)
        self.assertEqual(review.status(queue['drafts'][0]), 'source_changed')
        self.assertEqual(review.renew(self.queue, self.root), [])
        self.assertEqual(opportunities.load(self.root)['opportunities'][0], renewed)

    def test_pdf_stale_version_wrong_page_and_missing_mapping_cannot_publish(self):
        draft = self.pdf_ready()
        self.pdf_raw += b'changed'
        with self.assertRaisesRegex(ValueError, 'PDF.*SHA'):
            self.publish_pdf(draft)
        self.assertFalse(self.catalog.exists())
        self.pdf_raw = b'%PDF-1.7 reviewed version'
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['reviewed_fields']['materials']['pages'] = [1]
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, 'materials.*页码'):
            self.publish_pdf(draft)
        del queue['drafts'][0]['reviewed_fields']['materials']
        review.atomic_json(self.queue, queue)
        with self.assertRaisesRegex(ValueError, 'materials.*页码'):
            self.publish_pdf(draft)
        self.assertFalse(self.catalog.exists())

    def test_pdf_monitor_checks_files_even_when_html_is_identical(self):
        from crawler import opportunity_monitor as monitor
        draft = self.pdf_ready()
        item = self.publish_pdf(draft)
        def run(pdf=None, raw=None):
            return monitor.run_once([], self.root/'live.json', [item], fetcher=lambda _:raw or self.raw,
                                    pdf_fetcher=lambda *_:pdf or self.pdf_raw)['opportunity_checks'][item['id']]
        self.assertEqual(run()['status'], 'unchanged')
        self.assertEqual(run(self.pdf_raw+b'new clauses')['status'], 'changed')
        self.assertEqual(run(raw=self.raw.replace(b'camp.pdf',b'other.pdf'))['status'], 'changed')
        with patch.object(review, 'fetch_pdf', side_effect=requests.Timeout('PDF timeout')):
            result = monitor.run_once([], self.root/'live.json', [item], fetcher=lambda _:self.raw)
        self.assertEqual(result['opportunity_checks'][item['id']]['status'], 'error')
        self.assertEqual(result['summary']['opportunity_errors'], 1)

    def test_pdf_scanned_document_and_edited_review_mapping_cannot_renew(self):
        draft = self.pdf_ready()
        with patch.object(review.extraction, 'pdf_document', return_value=dict(pages=[],page_count=1,text_status='no_text')):
            with self.assertRaisesRegex(ValueError, '扫描'):
                self.publish_pdf(draft)
        self.publish_pdf(draft)
        queue = review.read_queue(self.queue)
        queue['drafts'][0]['reviewed_fields']['materials']['quote'] = 'different meaning'
        review.atomic_json(self.queue, queue)
        self.assertEqual(review.status(queue['drafts'][0]), 'pending_review')
        self.assertEqual(review.renew(self.queue, self.root), [])

    def test_pdf_failed_fresh_download_preserves_catalog_and_cannot_renew(self):
        draft = self.pdf_ready()
        self.publish_pdf(draft)
        before = self.catalog.read_bytes()
        with self.assertRaisesRegex(ValueError, '获取失败'):
            self.publish(draft, pdf_fetcher=Mock(side_effect=requests.Timeout('failed PDF')),
                         acknowledged_pdf_hashes=[draft['fetch']['pdfs'][0]['sha256']])
        self.assertEqual(self.catalog.read_bytes(), before)
        self.assertEqual(review.renew(self.queue, self.root), [])


if __name__ == '__main__':
    unittest.main()
