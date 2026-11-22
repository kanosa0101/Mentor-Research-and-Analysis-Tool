import copy
import unittest
import json
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from crawler import notice_util
from scripts.build_site import template_environment
from test_maintenance import script


class NoticeTests(unittest.TestCase):
    def test_static_row_navigation_rejects_executable_or_external_links(self):
        monitor = script('monitor_notices')
        cfg = dict(school='nankai', dept='cs', url='https://cc.nankai.edu.cn/list',
                   selector='tr[onclick]', link_attr='onclick',
                   title_selector='.text-align-title', date_selector='td:nth-child(4)')
        rows = []
        for action in ("window.location.href='/2026/page.htm';", "window.location.href='https://evil.example/a'",
                       "window.location.href='/x'; alert(1)", "go('/x')", "window.location.href='javascript:alert(1)'"):
            html = '<tr onclick="' + action + '"><td></td><td class="text-align-title">2027年硕士招生通知</td><td></td><td>2026-11-12</td></tr>'
            rows.extend(monitor.parse_list(html, cfg))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://cc.nankai.edu.cn/2026/page.htm')
        self.assertEqual(rows[0]['publication_date'], '2026-11-12')

    def test_refresh_preserves_failed_source_and_invalidates_changed_title_review(self):
        monitor = script('monitor_notices')
        configs = [dict(school=s, dept='cs', url=f'https://{s}.edu.cn/list',
                        selector='a', title_selector='self') for s in ('ok', 'failed')]
        old = {'notices': [dict(url=f'https://{s}.edu.cn/info', title='2027年推免通知',
                    school=s, dept='cs', reviewed=True, admission_year=2027,
                    deadline='2026-09-20', seen_in_latest_list=True) for s in ('ok', 'failed')],
               'sources': {'failed/cs': {'url':configs[1]['url'], 'fetched_at':'2026-10-01'}}}
        def source(cfg):
            if cfg['school'] == 'failed':
                raise ValueError('source offline')
            return '<a href="/info">2027年统考初试安排</a>', {'fetched_at':'2026-11-15'}, False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'notices.json'
            path.write_text(json.dumps(old), encoding='utf-8')
            result = monitor.collect(configs, path, refresh=True, fetcher=source)
            rows = {r['school']: r for r in result['notices']}
            self.assertFalse(rows['ok']['reviewed'])
            self.assertIsNone(rows['ok']['admission_year'])
            self.assertIsNone(rows['ok']['deadline'])
            self.assertEqual(rows['failed'], old['notices'][1])
            self.assertEqual(result['sources']['failed/cs']['fetched_at'], '2026-10-01')
            self.assertEqual(result['summary']['sources_error'], 1)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), result)

    def test_confirmation_and_exam_notices_are_collected(self):
        monitor = script('monitor_notices')
        cfg = dict(school='a',dept='cs',url='https://a.edu.cn/list',selector='a',title_selector='self')
        rows = monitor.parse_list('<a href="/confirm">2027年硕士网上确认</a><a href="/exam">2027年初试科目调整</a>',cfg)
        self.assertEqual(len(rows),2)

    def test_winter_doctoral_guide_is_a_current_admissions_notice(self):
        monitor = script('monitor_notices')
        listing = 'https://yz.tsinghua.edu.cn/zsxx/bszs/ptzk.htm'
        cfg = dict(school='tsinghua', dept='', url=listing, selector='a[href]')
        title = '清华大学2027年普通招考博士研究生冬季报考须知'
        html = (f'<a href="../../info/1012/3296.htm" title="{title}">'
                '<div class="time"><em>29</em><span>2026.10</span></div></a>'
                '<a href="/unrelated" title="旧公务员报考须知">历史新闻</a>')
        rows = monitor.parse_list(html, cfg)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['url'], 'https://yz.tsinghua.edu.cn/info/1012/3296.htm')
        self.assertEqual(row['source'], listing)
        self.assertEqual(row['publication_date'], '2026-10-29')
        self.assertFalse(row['reviewed'])
        cycle = notice_util.classify_notice(row, day='2026-11-23')
        self.assertEqual(cycle['admission_year'], 2027)
        self.assertIsNone(cycle['graduation_year'])
        self.assertIsNone(cycle['activity_year'])
        self.assertNotIn('winter_camp', cycle['routes'])

    def test_same_unit_distinct_sources_keep_separate_current_list_state(self):
        monitor = script('monitor_notices')
        configs = [dict(school='tsinghua', dept='', source_id=name, selector='a', title_selector='self',
                        url=f'https://yz.tsinghua.edu.cn/{name}/') for name in ('doctoral', 'general')]

        def fetcher(cfg):
            return f'<a href="notice.htm">{cfg["source_id"]}招生</a>', {'fetched_at': '2026-11-22'}, False

        with tempfile.TemporaryDirectory() as directory:
            result = monitor.collect(configs, Path(directory) / 'notices.json', fetcher=fetcher)
        self.assertEqual(set(result['sources']), {'doctoral', 'general'})
        self.assertEqual(len(result['notices']), 2)
        self.assertTrue(all(source['scope'] == 'tsinghua/' for source in result['sources'].values()))
        self.assertTrue(all(row['seen_in_latest_list'] for row in result['notices']))

    def test_render_selects_real_unit_without_losing_separate_source_ids(self):
        sources = {'doctoral': {'url': 'https://yz.tsinghua.edu.cn/doctoral/', 'scope': 'tsinghua/', 'name': '普通博士'},
                   'general': {'url': 'https://yz.tsinghua.edu.cn/general/', 'scope': 'tsinghua/', 'name': '校级公告'},
                   'tsinghua/cs': {'url': 'https://cs.tsinghua.edu.cn/'},
                   'xidian-ai-notices': {'url': 'https://sai.xidian.edu.cn/tzgg.htm', 'scope': 'xidian/ai',
                                         'name': '西安电子科技大学 · 人工智能学院'}}
        html = template_environment().get_template('notices.html.j2').render(notices=[], sources=sources)
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual([option['value'] for option in soup.select('#school option')],
                         ['', 'tsinghua/', 'tsinghua/cs', 'xidian/ai'])
        self.assertEqual([entry['data-source'] for entry in soup.select('[data-source-scope="tsinghua/"]')],
                         ['doctoral', 'general'])
        self.assertEqual(soup.select_one('[data-source="doctoral"] a').get_text(strip=True), '普通博士 官方栏目')
        self.assertEqual(soup.select_one('[data-source-scope="xidian/ai"]')['data-source-name'],
                         '西安电子科技大学 · 人工智能学院')

    def test_default_order_prioritizes_current_list_then_publication_date(self):
        monitor = script('monitor_notices')
        rows = [
            {'school': 'a', 'url': '/history', 'publication_date': '2026-10-15', 'seen_in_latest_list': False, 'fetched_at': '2026-10-14'},
            {'school': 'a', 'url': '/unknown', 'publication_date': None, 'seen_in_latest_list': True},
            {'school': 'z', 'url': '/new', 'publication_date': '2026-10-15', 'seen_in_latest_list': True},
            {'school': 'a', 'url': '/old', 'publication_date': '2026-09-01', 'seen_in_latest_list': True},
            {'school': 'a', 'url': '/history-unknown', 'seen_in_latest_list': False},
        ]
        original = copy.deepcopy(rows)
        ordered = monitor.sort_notices(rows)
        self.assertEqual([r['url'] for r in ordered], ['/new', '/old', '/unknown', '/history', '/history-unknown'])
        self.assertEqual(rows, original)
        self.assertEqual(len(ordered), len(rows))
        self.assertTrue(all(any(r is old for old in rows) for r in ordered))

    def test_notice_order_has_stable_school_and_url_ties(self):
        monitor = script('monitor_notices')
        rows = [{'school': school, 'url': url, 'publication_date': '2026-10-08', 'seen_in_latest_list': True}
                for school, url in [('z', '/a'), ('a', '/z'), ('a', '/a')]]
        expected = [('a', '/a'), ('a', '/z'), ('z', '/a')]
        self.assertEqual([(r['school'], r['url']) for r in monitor.sort_notices(rows)], expected)
        self.assertEqual([(r['school'], r['url']) for r in monitor.sort_notices(reversed(rows))], expected)

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
