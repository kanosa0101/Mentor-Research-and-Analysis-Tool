import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fill_related_fields', ROOT / 'scripts/fill_related_fields.py')
fill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fill)


class FillFieldsTests(unittest.TestCase):
    def test_explicit_sjtu_section_excludes_bio_and_nav(self):
        html = '''<nav>研究方向：错误</nav><div class="js-item"><div class="tit">个人简介</div><div class="detail">研究人工智能</div></div><div class="js-item"><div class="tit">研究方向</div><div class="detail"><p>组合导航</p><p>数据融合</p></div></div>'''
        got = fill.extract('sjtu', html)
        self.assertEqual(got['research_direction_raw']['value'], '组合导航\n数据融合')
        self.assertNotIn('email', got)

    def test_tsinghua_section_stops_at_next_heading(self):
        html = '<div class="leader_d"><div class="fl02"><div class="t-tag">研究领域</div><p>故障诊断</p><div class="t-tag">研究概况</div><p>项目20项</p></div><div class="fl01"><a href="mailto:user@tsinghua.edu.cn">邮箱</a></div></div>'
        got = fill.extract('tsinghua', html)
        self.assertEqual(got['research_direction_raw']['value'], '故障诊断')
        self.assertEqual(got['email']['value'], 'user@tsinghua.edu.cn')

    def test_bio_mentions_are_not_directions(self):
        self.assertEqual(fill.extract('tsinghua', '<div class="leader_d"><div class="fl02"><p>从事研究方向包括机器学习</p></div></div>'), {})
        self.assertEqual(fill.extract('sjtu', '<div class="js-item"><div class="tit">工作经历</div><div class="detail">研究领域很多</div></div>'), {})

    def test_embedded_personal_heading_ends_direction_section(self):
        html = '<div class="js-item"><div class="tit">研究方向</div><div class="detail"><p>工业物联网</p><p><strong>个人简介</strong></p><p>博导，优秀青年</p><p>招生及招聘</p><p>欢迎加入</p></div></div>'
        self.assertEqual(fill.extract('sjtu', html)['research_direction_raw']['value'], '工业物联网')

    def test_patch_only_empty_fields_preserves_manual_and_other_bytes(self):
        raw = 'slug: example\nname: 示例\nschool: sjtu\ndept: auto\ndetail_url: https://sais.sjtu.edu.cn/faculty/example.html\nemail: existing@sjtu.edu.cn\nprovenance:\n  research_direction_raw:\n    origin: manual\n    source: https://sais.sjtu.edu.cn/faculty/example.html\n    fetched_at: "2026-10-01"\n    confidence: human\n'
        evidence = {'research_direction_raw': {'value': '导航', 'locator': '研究方向'}, 'email': {'value': 'other@sjtu.edu.cn', 'locator': '电子邮件'}}
        self.assertEqual(fill.patch(raw, evidence, 'https://sais.sjtu.edu.cn/faculty/example.html', '2026-10-14'), (raw, []))
        raw2 = raw.replace('  research_direction_raw:\n    origin: manual\n    source: https://sais.sjtu.edu.cn/faculty/example.html\n    fetched_at: "2026-10-01"\n    confidence: human\n', '  email:\n    origin: crawled\n    source: https://sais.sjtu.edu.cn/faculty/example.html\n    fetched_at: "2026-10-01"\n    confidence: auto\n')
        changed, fields = fill.patch(raw2, evidence, 'https://sais.sjtu.edu.cn/faculty/example.html', '2026-10-14')
        self.assertEqual([c['field'] for c in fields], ['research_direction_raw'])
        self.assertIn('email: existing@sjtu.edu.cn', changed)
        self.assertIn('    fetched_at: "2026-10-01"', changed)
        self.assertTrue(changed.startswith('slug: example\nname: 示例\n'))

    def test_allowed_url_and_path_bounds(self):
        self.assertTrue(fill.allowed_url('sjtu', 'https://sais.sjtu.edu.cn/faculty/example.html'))
        self.assertFalse(fill.allowed_url('sjtu', 'https://evil.test/faculty/example.html'))
        self.assertFalse(fill.allowed_url('tsinghua', 'https://www.au.tsinghua.edu.cn/notice.html'))
        with self.assertRaises(ValueError):
            fill.record_path('sjtu', '../other')

    def test_profile_identity_must_match(self):
        self.assertTrue(fill.matches_name('sjtu', '<div class="js-info"><div class="tit"><p>陈 新</p></div></div>', '陈新'))
        self.assertFalse(fill.matches_name('sjtu', '<div class="js-info"><div class="tit"><p>另一人</p></div></div>', '陈新'))
        self.assertFalse(fill.matches_name('tsinghua', '<p>陈新</p>', '陈新'))


if __name__ == '__main__':
    unittest.main()
