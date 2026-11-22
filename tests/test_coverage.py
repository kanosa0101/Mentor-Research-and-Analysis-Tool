import json
import shutil
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import yaml

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


def test_coverage_rebuild_updates_mentor_counts_with_policy_dates_preserved(tmp_path, monkeypatch):
    from scripts import build_site

    class BuildTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 22, 20, tzinfo=timezone.utc).astimezone(tz)

    original_site = build_site.ROOT / 'site'
    env = build_site.template_environment()
    data = tmp_path / 'data'
    profiles = data / 'professors' / 'fixture' / 'cs'
    profiles.mkdir(parents=True)
    config = tmp_path / 'sites' / 'fixture'
    config.mkdir(parents=True)
    site = tmp_path / 'site'
    site.mkdir()
    for name in ('ui.css', 'account-session.js', 'cloud-library.js', 'opportunities-core.js',
                 'opportunities.js', 'opportunity-push.js', 'browser-library-core.js', 'browser-library.js',
                 'start.js', 'plan-transfer.js', 'discovery-core.js', 'discovery.js', 'admissions-core.js',
                 'material-actions.js', 'workflow.js', 'admissions.js'):
        shutil.copyfile(original_site / name, site / name)
    (config / 'cs.yaml').write_text('school: fixture\ndept: cs\ndept_name: 计算机学院\n', encoding='utf-8')
    (data / 'schools.yaml').write_text('schools:\n- id: fixture\n  name: 测试大学\n', encoding='utf-8')
    coverage = data / 'coverage.json'
    coverage.write_text(json.dumps({
        'checked_at': '2026-11-15', 'scope': '测试范围', 'units': [
            {'school': 'fixture', 'dept': 'cs', 'name': '计算机学院',
             'gaps': ['保留原盘点缺口'], 'mentors': {'count': 100, 'with_research': 99, 'with_contact': 96},
             'policies': [{'url': 'https://example.edu/policy', 'title': '政策示例', 'reviewed_at': '2026-11-13'}],
             'columns': [{'url': 'https://example.edu/notice', 'label': '栏目示例', 'checked_at': '2026-11-12'}]},
        ],
    }, ensure_ascii=False), encoding='utf-8')
    old_coverage = coverage.read_bytes()
    person = {'slug': 'teacher', 'name': '测试教师', 'school': 'fixture', 'dept': 'cs',
              'detail_url': 'https://example.edu/teacher', 'last_verified': '2026-10-01', 'last_fetched': '2026-10-05'}
    mentor_path = profiles / 'teacher.yaml'
    mentor_path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    monkeypatch.setattr(build_site, 'ROOT', tmp_path)
    monkeypatch.setattr(build_site, 'SITE', site)
    monkeypatch.setattr(build_site, 'datetime', BuildTime)
    monkeypatch.setattr(build_site, 'template_environment', lambda: env)
    monkeypatch.setattr(build_site.store, 'DATA', data)

    build_site.main()
    page = site / 'coverage.html'
    assert '导师资料：1 位，其中 0 位有研究方向、0 位登记公开邮箱。' in page.read_text(encoding='utf-8')
    person.update(email='teacher@example.edu', research_direction_raw='计算机视觉', last_fetched='2026-11-22')
    mentor_path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    build_site.main()

    html = page.read_text(encoding='utf-8')
    assert '导师资料：1 位，其中 1 位有研究方向、1 位登记公开邮箱。' in html
    assert '导师统计随网站构建更新，最近统计于 2026-11-23' in html
    assert '导师记录原核对日期 2026-10-01 至 2026-10-01' in html
    assert '来源抓取日期 2026-11-22 至 2026-11-22' in html
    assert '政策与官方来源盘点：2026-11-15' in html
    assert '摘要核对 2026-11-13' in html and '检查 2026-11-12' in html
    assert '保留原盘点缺口' in html and coverage.read_bytes() == old_coverage
    payload = (site / 'admissions-data.js').read_text(encoding='utf-8').split('=', 1)[1].strip().removesuffix(';')
    unit = json.loads(payload)['units'][0]
    assert unit['count'] == unit['coverage']['email'] == unit['coverage']['research_direction_raw'] == 1


if __name__ == '__main__':
    unittest.main()
