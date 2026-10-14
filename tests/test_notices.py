import unittest

from test_maintenance import script


class NoticeTests(unittest.TestCase):
    def test_list_ignores_navigation_and_keeps_official_source(self):
        monitor = script('monitor_notices')
        cfg = {'school': 'pku', 'dept': 'cs', 'url': 'https://cs.pku.edu.cn/zsxx/yjszs.htm',
               'selector': 'a[href*="/info/"]', 'title_selector': 'h4'}
        html = '<a href="/nav">招生工作</a><a href="../info/1051/5510.htm"><div>2026.05.08</div><h4>北京大学计算机学院2027年研究生招生指南</h4></a><a href="https://evil.example/info/x"><h4>2027年招生通知</h4></a>'
        rows = monitor.parse_list(html, cfg)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://cs.pku.edu.cn/info/1051/5510.htm')
        self.assertEqual(rows[0]['title'], '北京大学计算机学院2027年研究生招生指南')

    def test_years_and_deadline_are_not_guessed(self):
        monitor = script('monitor_notices')
        hint = monitor.notice_hints('2026年优秀大学生夏令营报名通知')
        self.assertEqual(hint['title_years'], [2026])
        self.assertIsNone(hint['admission_year'])
        self.assertIsNone(hint['deadline'])
        self.assertFalse(hint['reviewed'])

    def test_signature_ignores_navigation_and_order(self):
        monitor = script('monitor_notices')
        rows = [{'title': '2027年招生指南', 'url': 'https://example.org/a'},
                {'title': '2027年推免通知', 'url': 'https://example.org/b'}]
        self.assertEqual(monitor.signature(rows), monitor.signature(list(reversed(rows))))
        self.assertNotEqual(monitor.signature(rows), monitor.signature(rows[:1]))

    def test_flat_title_and_source_specific_date(self):
        monitor = script('monitor_notices')
        cfg = {'school': 'test', 'dept': 'auto', 'url': 'https://example.edu/list', 'selector': 'li a[href]', 'title_selector': 'self', 'date_selector': '.date'}
        rows = monitor.parse_list('<li><a href="/policy">2027年接收推免报名通知</a><span class="date">2026-07-07</span></li>', cfg)
        self.assertEqual(rows[0]['title'], '2027年接收推免报名通知')
        self.assertEqual(rows[0]['publication_date'], '2026-07-07')
