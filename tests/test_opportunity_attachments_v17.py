import copy
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from crawler import opportunity_attachments as attachments
from crawler import opportunity_extract as extract
from crawler import opportunity_monitor as monitor
from crawler import opportunity_review as review
from scripts.monitor_notices import parse_list


def docx(text='申请人独立完成，不得由AI协助。', xml=None):
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', xml or '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return target.getvalue()


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://cs.example.edu.cn/camp'
        self.raw = docx()
        self.records = [dict(url='https://cs.example.edu.cn/form.docx', sha256=hashlib.sha256(self.raw).hexdigest(), checked_at='2026-11-15', field_evidence={'materials': dict(quote='申请人独立完成，不得由AI协助。', locator='申请说明')})]
        self.html = '<html><meta charset="utf-8"><p>本科生冬令营报名。申请要求由申请人独立完成，请准备报名材料与成绩单。</p><a href="/form.docx">申请表</a></html>'.encode()

    def test_actual_docx_quote_and_version_are_verified(self):
        result = attachments.verify(self.records, self.url, lambda *_: self.raw)
        self.assertEqual(result[0]['text'], '申请人独立完成，不得由AI协助。')
        attachments.validate_links(self.records, self.html, self.url)
        self.assertNotEqual(attachments.source_version('a' * 64, self.records), 'a' * 64)
        self.assertEqual(attachments.source_version('a' * 64, []), 'a' * 64)

    def test_changed_docx_or_missing_quote_rejected(self):
        with self.assertRaises(attachments.AttachmentChanged):
            attachments.verify(self.records, self.url, lambda *_: docx('材料有变动'))
        self.records[0]['field_evidence']['materials']['quote'] = '不存在的要求'
        with self.assertRaisesRegex(ValueError, '摘录'):
            attachments.verify(self.records, self.url, lambda *_: self.raw)

    def test_metadata_rejects_foreign_http_duplicate_and_bad_date(self):
        for changes in [dict(url='https://evil.edu.cn/form.docx'), dict(url='http://cs.example.edu.cn/form.docx'), dict(checked_at='bad'), dict(sha256='abc'), dict(field_evidence={})]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                attachments.validate_metadata([dict(self.records[0], **changes)], self.url)
        with self.assertRaises(ValueError):
            attachments.validate_metadata(self.records * 2, self.url)

    def test_zip_xml_and_size_boundaries(self):
        dtd = '<!DOCTYPE x [<!ENTITY value "bad">]><x>&value;</x>'
        for raw in [b'', b'PKbad', docx(xml=dtd), docx(xml=dtd.encode('utf16')), docx(xml='<broken>')]:
            with self.subTest(raw=raw[:10]), self.assertRaises(ValueError):
                attachments.parse_docx(raw)
        with patch.object(attachments, 'MAX_BYTES', 10), self.assertRaises(ValueError):
            attachments.parse_docx(self.raw)
        with patch.object(attachments, 'MAX_EXPANDED', 10), self.assertRaises(ValueError):
            attachments.parse_docx(self.raw)

    def test_attachment_link_removal_or_replacement_requires_review(self):
        for html in [self.html.replace(b'/form.docx', b'/new.docx'), b'<html>removed</html>']:
            with self.assertRaises(attachments.AttachmentChanged):
                attachments.validate_links(self.records, html, self.url)

    def test_network_redirect_cannot_leave_official_institution(self):
        response = Mock(status_code=302, headers={'Location': 'https://other.edu.cn/form.docx'})
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = response
        with patch.object(attachments.requests, 'Session', return_value=session), self.assertRaises(ValueError):
            attachments.fetch_docx(self.records[0]['url'], self.url)
        self.assertEqual(session.get.call_count, 1)

    def test_cibr_nuxt_download_references_are_bound_to_notice(self):
        ident = '1' * 32
        records = copy.deepcopy(self.records)
        records[0]['url'] = 'https://cibr.ac.cn/file/common/download/' + ident
        raw = '<script id="__NUXT_DATA__">[{"name":1,"id":2},"申请表.docx","' + ident + '"]</script>'
        attachments.validate_links(records, raw, 'https://cibr.ac.cn/detail/a')
        with self.assertRaises(attachments.AttachmentChanged):
            attachments.validate_links(records, raw.replace(ident, '2' * 32), 'https://cibr.ac.cn/detail/a')

    def test_monitor_checks_attachments_even_when_html_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'live.json'
            item = dict(id='camp', source_state='verified', source_url=self.url, source_sha256=hashlib.sha256(self.html).hexdigest(), source_attachments=self.records)
            for status, raw in [('unchanged', self.raw), ('changed', docx('申请材料变更'))]:
                result = monitor.run_once([], output, [item], fetcher=lambda _: self.html, docx_fetcher=lambda *_: raw)
                self.assertEqual(result['opportunity_checks']['camp']['status'], status)
            def fail(*_):
                raise requests.Timeout('attachment timeout')
            result = monitor.run_once([], output, [item], fetcher=lambda _: self.html, docx_fetcher=fail)
            self.assertEqual(result['opportunity_checks']['camp']['status'], 'error')
            self.assertEqual(result['summary']['opportunity_errors'], 1)

    def test_publish_fetch_records_docx_and_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue = root / 'cache/review.json'
            listing = 'https://cs.example.edu.cn/list'
            configs = [dict(url=listing)]
            data = review.sync({'candidates': [dict(url=self.url, source=listing, school='example', dept='cs', unit='计算机学院', title='本科生冬令营', first_seen='2026-11-15T00:00:00+00:00', last_seen='2026-11-15T00:00:00+00:00')]}, queue, configs, fetcher=lambda _: self.html)
            draft = data['drafts'][0]
            draft['item'].update(school_name='示例大学', kind='winter_camp', cycle='current', evidence=['官方公告'], source_attachments=self.records, materials=['须独立完成，不得由AI协助'])
            draft['quotes'] = ['本科生冬令营报名。']
            draft['reviewed_fields'] = {'materials': dict(self.records[0]['field_evidence']['materials'], source_url=self.records[0]['url'])}
            review.atomic_json(queue, data)
            kwargs = dict(acknowledged_hash=draft['fetch']['sha256'], reviewer='维护者', note='逐条核对官方附件', fetcher=lambda _: self.html)
            published = review.publish(queue, draft['id'], root, configs, docx_fetcher=lambda *_: self.raw, **kwargs)
            self.assertEqual(published['source_attachments'], self.records)
            before = (root / 'data/opportunities.json').read_bytes()
            content_hash = review.read_queue(queue)['drafts'][0]['fetch']['content_sha256']
            with self.assertRaisesRegex(ValueError, '获取失败'):
                review.publish(queue, draft['id'], root, configs, docx_fetcher=lambda *_: docx('新版'), acknowledged_content_hash=content_hash, **kwargs)
            self.assertEqual((root / 'data/opportunities.json').read_bytes(), before)


class WindowAndSourceTests(unittest.TestCase):
    def test_rolling_and_month_quotes_must_be_actual_application_text(self):
        for quote in ['全年接受本科生科研申请', '招聘启事在岗位招满前长期有效。']:
            review.validate_field_evidence({}, {'application_window': dict(mode='rolling', end_month='', quote=quote)}, quote)
        for window, text in [(dict(mode='rolling', quote='长期研究人工智能'), '长期研究人工智能'), (dict(mode='rolling', quote='长期招收'), '不存在'), (dict(mode='month', quote='报名至2027年2月', end_month='2027-01'), '报名至2027年2月')]:
            with self.subTest(window=window), self.assertRaises(ValueError):
                review.validate_field_evidence({}, {'application_window': window}, text)

    def test_publication_date_plus_immediate_start_requires_explicit_mapping(self):
        item = dict(published_at='2026-11-02', registration_start='2026-11-02')
        draft = {'reviewed_fields': {'registration_start': dict(quote='2026-11-02', locator='发布日期结合即日起')}}
        review.validate_field_evidence(draft, item, '2026-11-02 报名即日起开始')
        with self.assertRaises(ValueError):
            review.validate_field_evidence(draft, item, '2026-11-02 通知')
        draft['reviewed_fields']['registration_start']['locator'] = '发布日期'
        with self.assertRaises(ValueError):
            review.validate_field_evidence(draft, item, '2026-11-02 报名即日起开始')

    def test_date_range_retains_shared_year_month_without_inventing_end(self):
        self.assertEqual(extract.explicit_date_values('2027年1月10日-14日'), {'2027-01-10', '2027-01-14'})
        self.assertNotIn('2027-01-05', extract.explicit_date_values('2027年1月10日-5日'))
        self.assertNotIn('2027-02-31', extract.explicit_date_values('2027年2月10日-31日'))

    def test_direct_page_retraction_and_captcha_are_errors_and_preserve_rows(self):
        config = dict(mode='direct_page', source_id='lab', school='example', dept='cs', url='https://cs.example.edu.cn/lab', title='本科生科研实习', required_text='长期招收本科生科研实习')
        raw = '<meta charset="utf-8"><p>实验室研究人工智能与软件工程，长期招收本科生科研实习。欢迎联系导师，确认实习安排与具体条件。</p>'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'live.json'
            first = monitor.run_once([config], output, fetcher=lambda _: raw)
            self.assertEqual(len(first['candidates']), 1)
            self.assertIsNone(first['candidates'][0]['admission_year'])
            self.assertFalse(first['candidates'][0]['reviewed'])
            for invalid in ['', '<title>验证码</title>', raw.replace('长期招收本科生科研实习', '已停止接收实习申请')]:
                result = monitor.run_once([config], output, fetcher=lambda _: invalid)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(len(result['candidates']), 1)

    def test_cibr_api_uses_actual_titles_not_internal_type(self):
        raw = monitor.cibr_list(dict(code='success', retMap={'articleList': [dict(id='1' * 32, title='2027年冬季培训班招募', createTime='2026-11-02T00:00:00')]}))
        rows = parse_list(raw, dict(school='cibr', dept='', url='https://cibr.ac.cn/cibrPersonnel/admissions', selector='li a', title_selector='self', date_selector='.date'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['publication_date'], '2026-11-02')
        self.assertTrue(monitor.activity_title(rows[0]['title']))
        for payload in [None, {'code': 'success', 'retMap': None}, {'code': 'failed'}, {'code': 'success', 'retMap': {'articleList': [{}]}}]:
            with self.assertRaises(ValueError):
                monitor.cibr_list(payload)
