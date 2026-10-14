import unittest
from unittest.mock import patch

from test_maintenance import script


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.hook = script('..\\sites\\related_roster')
        self.cfg = {'base_url': 'https://example.edu', 'list': {'urls': ['https://example.edu/teachers'],
                    'card_selector': '.person', 'name_selector': '.name', 'link_selector': 'a[href]',
                    'person_href': r'/info/people/\d+\.htm$', 'next_selector': 'a.next'}}

    def test_cards_have_field_and_page_provenance(self):
        html = '<nav><a href="/info/people/9.htm">行政办公室</a></nav><div class="person"><a href="/info/people/1.htm"><h3 class="name">张三</h3><p>电子邮件：zhang@example.edu</p></a></div><div class="person"><a href="https://evil.example/info/people/2.htm"><h3 class="name">李四</h3></a></div>'
        rows = self.hook.collect(self.cfg, 'https://example.edu/teachers', html, '2026-10-01')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['email'], 'zhang@example.edu')
        self.assertEqual(rows[0]['roster_source'], 'https://example.edu/teachers')
        self.assertEqual(rows[0]['roster_fetched_at'], '2026-10-01')

    def test_next_pages_keep_dates_and_deduplicate_urls(self):
        a = '<div class="person"><a href="/info/people/1.htm"><h3 class="name">张三</h3></a></div><a class="next" href="/teachers/2">next</a>'
        b = '<div class="person"><a href="/info/people/2.htm"><h3 class="name">李四</h3></a></div>'
        with patch.object(self.hook.fetch, 'fetch_text', side_effect=[(a, {'fetched_at': '2026-10-01'}, True), (b, {'fetched_at': '2026-10-14'}, False)]):
            rows, meta = self.hook.iter_roster(self.cfg)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['roster_fetched_at'], '2026-10-01')
        self.assertEqual(meta['fetched_at'], '2026-10-01')

    def test_shared_link_does_not_merge_different_names(self):
        html = '<div class="person"><a href="/info/people/1.htm"><h3 class="name">张三</h3></a></div><div class="person"><a href="/info/people/1.htm"><h3 class="name">李四</h3></a></div>'
        self.assertEqual(len(self.hook.collect(self.cfg, 'https://example.edu/teachers', html, '2026-10-14')), 2)

    def test_missing_or_failed_page_cannot_be_complete_roster(self):
        with patch.object(self.hook.fetch, 'fetch_text', return_value=('<html>login</html>', {'fetched_at': '2026-10-14'}, False)):
            with self.assertRaises(ValueError):
                self.hook.iter_roster(self.cfg)

    def test_navigation_groups_are_not_admission_conclusions(self):
        from crawler.unit_util import groups
        self.assertEqual(groups('网络空间安全学院'), ['cyber'])
        self.assertEqual(groups('自动化与感知学院'), ['control'])
        self.assertEqual(groups('计算机与软件学院'), ['computer', 'software'])
        self.assertEqual(groups('未知学院'), ['other'])

    def test_scoped_detail_fields_exclude_navigation_email(self):
        cfg = {'detail_fields': {'email': '.profile .email', 'title': '.profile h5'}}
        html = '<footer>webmaster@example.edu</footer><div class="profile"><h5>教授</h5><a class="email">prof@example.edu</a></div>'
        result = self.hook.parse_detail(cfg, html, 'https://example.edu/a')
        self.assertEqual(result['email'], 'prof@example.edu')
        self.assertEqual(result['title'], '教授')
        cfg['bio_selector'] = '.bio'
        result = self.hook.parse_detail(cfg, '<nav>不是研究内容</nav><div class="bio">机器人与具身智能研究</div>', 'https://example.edu/a')
        self.assertEqual(result['bio_raw'], '机器人与具身智能研究')
        result = self.hook.parse_detail(cfg, '<div class="profile"><h5>上海交通大学博士、浙江大学博士后</h5></div>', 'https://example.edu/a')
        self.assertNotIn('title', result)
        cfg['detail_fields']['title'] = '.profile h5, .profile h6'
        result = self.hook.parse_detail(cfg, '<div class="profile"><h5>博士</h5><h6>研究员</h6></div>', 'https://example.edu/a')
        self.assertEqual(result['title'], '研究员')
        result = self.hook.parse_detail(cfg, '<div class="profile"><h5>博士</h5><h6>曾任北京理工大学副研究员</h6><h6>目前任清华大学教授（双聘）</h6></div>', 'https://example.edu/a')
        self.assertEqual(result['title'], '教授')


if __name__ == '__main__':
    unittest.main()
