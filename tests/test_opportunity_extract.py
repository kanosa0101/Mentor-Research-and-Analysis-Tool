import unittest
from datetime import date
from unittest.mock import Mock, patch

from crawler import opportunity_extract as extract


class ExtractionTests(unittest.TestCase):
    url = 'https://cs.example.edu.cn/info/camp.htm'

    def parse(self, paragraphs, title='2027年计算机冬令营'):
        html = '<html><meta charset="utf-8"><article>' + ''.join('<p>'+p+'</p>' for p in paragraphs) + '</article></html>'
        return extract.extract(html, self.url, title, date(2026, 11, 15))

    def test_publication_date_is_not_deadline_and_years_stay_separate(self):
        result = self.parse(['发布时间：2026年11月10日', '本次活动面向2028届本科毕业生，欢迎报名。'])
        self.assertNotIn('deadline', result['suggestions'])
        self.assertNotIn('registration_start', result['suggestions'])
        self.assertEqual(result['suggestions']['graduation_year'], 2028)
        self.assertEqual(result['suggestions']['camp_year'], 2027)
        self.assertNotIn('admission_year', result['suggestions'])

    def test_month_only_preserves_precision_and_does_not_invent_end_of_month(self):
        result = self.parse(['本计划面向相关专业本科生。', '三、报名与受理', '即日起至2 027 年1月。'])
        self.assertEqual(result['suggestions']['registration_deadline_month'], '2027-01')
        self.assertNotIn('deadline', result['suggestions'])
        self.assertNotIn('registration_start', result['suggestions'])
        self.assertEqual(result['field_evidence']['registration_deadline_month']['precision'], 'month')
        self.assertEqual(result['classification'], 'current_pending_review')

    def test_explicit_deadline_keeps_time_and_timezone(self):
        result = self.parse(['本次报名截止2026年12月31日14:30，请提交申请材料。'])
        self.assertEqual(result['suggestions']['deadline'], '2026-12-31T14:30:00+08:00')
        self.assertEqual(result['field_evidence']['deadline']['precision'], 'minute')

    def test_multiple_batch_dates_are_not_silently_selected(self):
        result = self.parse(['第一批报名截止2026年11月20日。', '第二批报名截止2026年12月20日。'])
        self.assertNotIn('deadline', result['suggestions'])
        self.assertTrue(result['warnings'])

    def test_post_selection_material_date_does_not_become_registration_deadline(self):
        result = self.parse(['入选后申请材料邮寄截止2026年12月31日，请按要求报到。'])
        self.assertNotIn('deadline', result['suggestions'])

    def test_material_stages_and_optional_items_survive(self):
        result = self.parse(['一、申请条件', '大二、大三本科生，专业排名前20%。', '二、申请材料',
                             '报名时提交简历，科研证明自愿提交。', '入选后再交签章申请表。', '三、活动时间',
                             '活动时间为2026年12月20日至2026年12月22日。'])
        self.assertEqual(len(result['suggestions']['eligibility']), 1)
        self.assertEqual(result['suggestions']['materials'], ['报名时提交简历，科研证明自愿提交。', '入选后再交签章申请表。'])
        self.assertEqual(result['suggestions']['event_start'], '2026-12-20')
        self.assertEqual(result['suggestions']['event_end'], '2026-12-22')

    def test_contact_and_attachment_are_source_linked(self):
        result = self.parse(['本科生报名咨询邮箱：mentor@example.edu.cn。', '<a href="files/a.xlsx">方向与联系人</a>'])
        self.assertEqual(result['suggestions']['contact'], 'mentor@example.edu.cn')
        self.assertEqual(result['suggestions']['attachments'][0]['url'], 'https://cs.example.edu.cn/info/files/a.xlsx')
        self.assertEqual(result['field_evidence']['contact']['source_url'], self.url)

    def test_material_mentions_after_section_do_not_reopen_material_requirements(self):
        result = self.parse(['一、申请材料', '报名时提交成绩单。', '二、申请流程',
                             '请登录报名系统提交申请。', '5.申请人必须保证提交的全部申请材料真实。',
                             '6.有关联合培养计划请关注后续通知。'])
        self.assertEqual(result['suggestions']['materials'], ['报名时提交成绩单。'])

    def test_blocked_empty_or_navigation_pages_are_rejected(self):
        for raw in ('<title>Access Denied</title><p>申请材料和本科生报名说明</p>', '<p>页面不存在</p>',
                    '<body><a href="/a">本科招生研究生招生报名申请材料招生计划</a></body>'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                extract.document(raw, self.url)

    def test_counter_and_script_changes_do_not_hide_substantive_or_link_changes(self):
        raw = '<article><p>本次申请面向相关专业本科生，排名要求为前20%。</p><span class="views"><b>浏览次数：123</b></span><a href="a.xlsx">附件</a></article>'
        digest = extract.document(raw, self.url)['content_sha256']
        same = raw.replace('123', '456') + '<script>console.log(99)</script>'
        self.assertEqual(extract.document(same, self.url)['content_sha256'], digest)
        for changed in (raw.replace('20%', '30%'), raw.replace('a.xlsx', 'b.xlsx')):
            self.assertNotEqual(extract.document(changed, self.url)['content_sha256'], digest)
        self.assertNotEqual(extract.document('<title>2027年冬令营</title>'+raw, self.url)['content_sha256'],
                            extract.document('<title>2028年冬令营</title>'+raw, self.url)['content_sha256'])

    def test_expired_deadline_is_historical(self):
        result = self.parse(['本次本科生报名截止2026年7月10日，请提交相关材料。'])
        self.assertEqual(result['classification'], 'historical')

    def test_known_pdf_embeds_are_literal_links_not_script_execution(self):
        raw='<script>showVsbpdfIframe("/a.pdf","100%"); dangerous();</script><span class="wp_pdf_player" pdfsrc="/b.pdf"></span>'
        self.assertEqual(set(extract.embedded_pdf_urls(raw,self.url)),{'https://cs.example.edu.cn/a.pdf','https://cs.example.edu.cn/b.pdf'})
        self.assertEqual(extract.embedded_pdf_urls('<script>showVsbpdfIframe(getUrl());</script>',self.url),[])

    def test_pdf_suggestions_have_page_provenance(self):
        pages=[Mock(),Mock()]
        pages[0].extract_text.return_value='一、申请条件\n本次活动面向2028届本科毕业生，欢迎提交申请。'
        pages[1].extract_text.return_value='二、报名时间\n报名截止2026年12月31日。\n咨询邮箱：mentor@example.edu.cn'
        with patch('pypdf.PdfReader') as reader:
            reader.return_value.is_encrypted=False;reader.return_value.pages=pages
            result=extract.pdf_document(b'%PDF-test',self.url,'2027冬令营',date(2026,11,15))
        self.assertEqual(result['suggestions']['deadline'],'2026-12-31')
        self.assertEqual(result['field_evidence']['deadline']['pages'],[2])
        self.assertEqual(result['field_evidence']['deadline']['source_url'],self.url)
        self.assertEqual(result['page_count'],2)

    def test_pdf_magic_and_size_limits(self):
        for raw in (b'<html>not pdf</html>',b'%PDF-'+b'x'*extract.MAX_PDF_BYTES):
            with self.assertRaises(ValueError):extract.pdf_document(raw,self.url)
        with patch('pypdf.PdfReader') as reader:
            reader.return_value.is_encrypted=True
            result=extract.pdf_document(b'%PDF-test',self.url)
            self.assertEqual(result['text_status'],'encrypted')
            self.assertFalse(result['suggestions'])


if __name__ == '__main__':
    unittest.main()
