import unittest

from sites.bit.bit_cs import extract_research_direction, parse_contact, parse_detail
from scripts.fill_bit_research import planned_record, updated_yaml
import copy
import yaml


class BitResearchTests(unittest.TestCase):
    def test_exact_section_preserves_text_and_stops_at_next_heading(self):
        bio = '个人信息\n长期研究。\n科研方向\n图学习、AI 芯片\n1. 多模态感知\n代表性学术成果\n论文标题'
        self.assertEqual(extract_research_direction(bio), '图学习、AI 芯片\n1. 多模态感知')

    def test_empty_missing_unbounded_or_ambiguous_sections_stay_unknown(self):
        for bio in ('简介中的科研方向是视觉', '科研方向\n代表性学术成果\n论文',
                    '科研方向\n视觉', '科研方向\n视觉\n科研方向\n语言\n代表性学术成果',
                    '科研方向\n暂无\n代表性学术成果'):
            self.assertIsNone(extract_research_direction(bio), bio)

    def test_hook_keeps_complete_bio_and_extracts_only_section(self):
        html = '<div class="article"><h2>个人信息</h2><p>' + '官方简介。'*20 + '</p><h2>科研方向</h2><p>计算机视觉、大模型</p><h2>代表性学术成果</h2><p>标题</p></div>'
        parsed = parse_detail({}, html, 'https://cs.bit.edu.cn/test.htm')
        self.assertIn('代表性学术成果', parsed['bio_raw'])
        self.assertEqual(parsed['research_direction_raw'], '计算机视觉、大模型')

    def test_current_profile_reads_labeled_email_title_and_explicit_homepage(self):
        html = ('<title>甲老师-博士生导师-北京理工大学计算机学院</title>'
                '<div class="left"><div class="title">甲老师</div><div class="summary">'
                '<p>职称：</p><p><b>E-mail：</b><a>jia@bit.edu.cn</a>（alt@example.org）</p></div></div>'
                '<div class="article"><h2>个人信息</h2><p>甲老师，副教授，博士生导师。'
                '曾任其他大学教授。本人开展多模态感知研究。该介绍由计算机学院教师目录提供。</p>'
                '<p>个人主页：<a href="https://teacher.bit.edu.cn/jia/">教师主页</a></p></div>')
        cfg = {'_expected_name': '甲老师'}
        url = 'https://cs.bit.edu.cn/example.htm'
        parsed = parse_detail(cfg, html, url)
        self.assertEqual({field: parsed[field] for field in ('name', 'title', 'supervisor', 'email', 'homepage')},
                         {'name': '甲老师', 'title': '副教授', 'supervisor': '博导', 'email': 'jia@bit.edu.cn',
                          'homepage': 'https://teacher.bit.edu.cn/jia/'})
        with self.assertRaises(ValueError):
            parse_detail({'_expected_name': '乙老师'}, html, url)

    def test_missing_title_does_not_reuse_past_or_others_appointments(self):
        html = ('<div class="left"><div class="title">甲老师</div></div><div class="article"><h2>个人信息</h2>'
                '<p>甲老师，曾任外校副教授、硕士生导师，在乙教授团队参与项目。'
                '该页另列若干会议和论文，同行评审工作，以及其他学术活动与以往研究经历。</p></div>')
        parsed = parse_detail({'_expected_name': '甲老师'}, html, 'https://cs.bit.edu.cn/example.htm')
        self.assertNotIn('title', parsed)
        self.assertNotIn('supervisor', parsed)

    def test_official_institute_email_requires_unique_exact_name_and_address(self):
        original = {'school': 'bit', 'dept': 'cs', 'name': '甲老师'}
        url = 'https://cs.bit.edu.cn/jgsz/jsjxy1/example/index.htm'
        def read(rows, person=original):
            html = ('<div class="article"><table><tr><th>姓名</th><th>导师类型</th><th>研究领域</th><th>邮箱</th></tr>'
                    + ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)
                    + '</table></div>')
            return parse_contact({'profile_contact_roster': url, '_read_source': lambda target: (b'', html)}, person)
        row = ('甲老师', '硕导', '机器学习', 'jia@bit.edu.cn')
        value = read([row])
        self.assertEqual(value['email'], 'jia@bit.edu.cn')
        self.assertEqual(value['_field_sources']['email'], url)
        self.assertIn('机器学习', value['_contact_locator']['email']['table_row'])
        self.assertFalse(read([row], dict(original, email='old@bit.edu.cn')))
        self.assertFalse(read([row, ('乙老师', '硕导', '算法', 'jia@bit.edu.cn')]))
        self.assertFalse(read([row, ('甲老师', '博导', '视觉', 'jia2@bit.edu.cn')]))
        self.assertFalse(read([('甲老师', '硕导', '算法', 'office@bit.edu.cn')]))

    def record(self):
        return dict(school='bit', dept='cs', name='测试', bio_raw='科研方向\n图学习\n代表性学术成果\n论文',
                    last_fetched='2026-09-05', provenance={'bio_raw': dict(origin='crawled',
                    source='https://cs.bit.edu.cn/profile.htm', fetched_at='2026-09-05')})

    def test_only_missing_research_and_original_provenance_are_added(self):
        original = self.record()
        before = copy.deepcopy(original)
        updated, reason = planned_record(original)
        self.assertIsNone(reason)
        self.assertEqual(original, before)
        self.assertEqual(updated['provenance']['research_direction_raw'], original['provenance']['bio_raw'])
        self.assertEqual(updated['bio_raw'], original['bio_raw'])
        self.assertEqual(updated['last_fetched'], original['last_fetched'])
        for newline in ('\n', '\r\n'):
            text = yaml.safe_dump(original, allow_unicode=True, sort_keys=False).replace('\n', newline)
            result = updated_yaml(text, updated)
            self.assertEqual(yaml.safe_load(result), updated)
            if newline == '\r\n':
                self.assertNotIn('\n', result.replace('\r\n', ''))

    def test_existing_and_manual_research_or_untrusted_bio_are_not_overwritten(self):
        for change in ('value', 'manual', 'missing_date', 'unofficial'):
            original = self.record()
            if change == 'value': original['research_direction_raw'] = '已整理'
            if change == 'manual': original['provenance']['research_direction_raw'] = {'origin': 'manual'}
            if change == 'missing_date': original['provenance']['bio_raw'].pop('fetched_at')
            if change == 'unofficial': original['provenance']['bio_raw']['source'] = 'https://example.com'
            self.assertIsNone(planned_record(original)[0])


if __name__ == '__main__':
    unittest.main()
