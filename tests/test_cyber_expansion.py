import unittest
from unittest.mock import patch

from test_maintenance import script


class CyberExpansionTests(unittest.TestCase):
    def setUp(self):
        self.hook = script('..\\sites\\cyber_expansion')

    def test_whu_only_regular_units_and_explicit_rank(self):
        cfg = {'school': 'whu', 'base_url': 'https://cse.whu.edu.cn', 'list': {'person_hosts': ['cse.whu.edu.cn', 'jszy.whu.edu.cn']}}
        html = '<div class="wlaq-sz-box"><h3 class="name">信息安全系</h3><div class="wlaq-sz-list"><li><h3 class="zc">副教授</h3><div class="sz-list"><a href="/info/1/2.htm">张三</a><a href="https://evil.test/1">李四</a></div></li></div><h3 class="name">兼职教授</h3><div class="wlaq-sz-list"><li><h3 class="zc">教授</h3><div class="sz-list"><a href="/info/3/4.htm">王五</a></div></li></div></div>'
        rows = self.hook.collect(cfg, 'https://cse.whu.edu.cn/teachers', html, '2026-10-14')
        self.assertEqual([r['name'] for r in rows], ['张三'])
        self.assertEqual(rows[0]['title'], '副教授')
        self.assertEqual(rows[0]['institutes'], ['信息安全系'])
        self.assertEqual(rows[0]['roster_fetched_at'], '2026-10-14')

    def test_hust_mixed_rank_does_not_guess_professor(self):
        cfg = {'school': 'hust', 'base_url': 'https://cse.hust.edu.cn', 'list': {'person_hosts': ['faculty.hust.edu.cn', 'cse.hust.edu.cn']}}
        rows = self.hook.collect(cfg, 'https://cse.hust.edu.cn/szdw/wlkjaqx.htm', '<dl><dt>教授/研究员</dt><dd><li><a href="https://faculty.hust.edu.cn/zhang">张三</a></li></dd></dl>', '2026-10-14')
        self.assertEqual(len(rows), 1)
        self.assertNotIn('title', rows[0])

    def test_whu_scoped_direction_not_nav_and_no_footer_email(self):
        html = '<footer>cse@whu.edu.cn</footer><div class="v_news_content"><div class="teacher-tab">研究方向</div><div class="teacher-cont"><h3>个人简介</h3><p>张三，博士生导师，研究可信计算。</p></div><div class="teacher-cont"><h3>研究方向</h3><p>系统安全与机器学习</p></div></div>'
        parsed = self.hook.parse_detail({'school': 'whu'}, html, 'https://cse.whu.edu.cn/info/1/2.htm')
        self.assertEqual(parsed['research_directions'], ['系统安全与机器学习'])
        self.assertNotIn('email', parsed)
        self.assertNotIn('teacher-tab', parsed['bio_raw'])

    def test_portal_uses_explicit_title_and_skips_hidden_cipher(self):
        html = '<nav>同专业博导</nav><div class="infoblock"><p>职称：副教授</p><p>硕士生导师</p><p>电子邮箱：<span style="display:none" _tsites_encrypt_field="x">deadbeef</span></p></div><div class="research"><h2>研究方向</h2><ul><li>软件安全</li></ul></div><footer>webmaster@example.edu</footer>'
        parsed = self.hook.parse_detail({'school': 'hust'}, html, 'https://faculty.hust.edu.cn/zhang')
        self.assertEqual(parsed['title'], '副教授')
        self.assertEqual(parsed['supervisor'], '硕导')
        self.assertNotIn('email', parsed)
        self.assertEqual(parsed['research_directions'], ['软件安全'])

    def test_roster_fails_closed_when_a_registered_page_is_empty(self):
        cfg = {'school': 'hust', 'base_url': 'https://cse.hust.edu.cn', 'list': {'urls': ['https://cse.hust.edu.cn/roster'], 'person_hosts': ['faculty.hust.edu.cn']}}
        with patch.object(self.hook.fetch, 'fetch_text', return_value=('<html>missing</html>', {'fetched_at': '2026-10-14'}, False)):
            with self.assertRaises(ValueError):
                self.hook.iter_roster(cfg)

    def test_portal_variant_reuses_header_parser_without_decryption(self):
        html = '<div class="dft-side"><div class="Psl-info"><h2>个人信息</h2><div class="cont"><p>教授</p><p>博士生导师</p><p>所在单位：网络空间安全学院</p><p>学历：博士</p></div></div></div><div class="dft-midcont"><div class="Psl-info"><div class="title"><h2>个人简介</h2></div><div class="cont">长期研究网络与软件安全，在相关领域发表多篇论文并建设研究团队。</div></div></div>'
        parsed = self.hook.parse_detail({'school': 'hust'}, html, 'https://faculty.hust.edu.cn/fucai/zh_CN/index.htm')
        self.assertEqual(parsed['title'], '教授')
        self.assertEqual(parsed['supervisor'], '博导')
        self.assertIn('长期研究网络', parsed['bio_raw'])

    def test_unrecognized_detail_is_not_reported_as_enriched(self):
        with self.assertRaises(ValueError):
            self.hook.parse_detail({'school': 'hust'}, '<html><body>入口页</body></html>', 'https://faculty.hust.edu.cn/empty')

    def test_portal_research_label_in_navigation_cannot_be_direction(self):
        html = '<nav><h2>研究领域</h2><li>· 研究领域</li></nav><div class="infoblock"><p>职称：教授</p><p>所在单位：网络空间安全学院</p></div><div class="Rsh-focus"><div class="title"><h2>研究方向</h2></div><div class="cont"><li>系统与软件安全</li></div></div>'
        parsed = self.hook.parse_detail({'school': 'hust'}, html, 'https://faculty.hust.edu.cn/person')
        self.assertEqual(parsed['research_directions'], ['系统与软件安全'])

    def test_portal_history_and_other_supervisors_are_not_current_identity(self):
        html = '<div class="infoblock"><p>职称：讲师</p><p>所在单位：网络空间安全学院</p><p>曾任博士生导师</p><p>导师王五为硕士生导师</p><p>导师类型：硕士生导师</p></div>'
        parsed = self.hook.parse_detail({'school': 'hust'}, html, 'https://faculty.hust.edu.cn/person')
        self.assertEqual(parsed['title'], '讲师')
        self.assertEqual(parsed['supervisor'], '硕导')
        parsed = self.hook.parse_detail({'school': 'hust'}, html.replace('<p>导师类型：硕士生导师</p>', ''), 'https://faculty.hust.edu.cn/person')
        self.assertNotIn('supervisor', parsed)

    def test_portal_unlabelled_paper_email_is_not_contact(self):
        html = '<div class="infoblock"><p>职称：教授</p><p>所在单位：网络空间安全学院</p></div><div class="publications">联系论文作者 paper@hust.edu.cn</div><div><p>邮箱：prof@hust.edu.cn</p></div>'
        parsed = self.hook.parse_detail({'school': 'hust'}, html, 'https://faculty.hust.edu.cn/person')
        self.assertEqual(parsed['email'], 'prof@hust.edu.cn')
        parsed = self.hook.parse_detail({'school': 'hust'}, html.replace('<p>邮箱：prof@hust.edu.cn</p>', ''), 'https://faculty.hust.edu.cn/person')
        self.assertNotIn('email', parsed)

    def test_whu_current_self_intro_only_not_history_or_other_person(self):
        prefix = '<meta name="pageTitle" content="张三"><div class="v_news_content"><div class="teacher-cont"><h3>个人简介</h3><p>'
        suffix = '</p></div></div>'
        parsed = self.hook.parse_detail({'school': 'whu'}, prefix+'张三，教授、博士生导师，研究软件安全。'+suffix, 'https://cse.whu.edu.cn/info/1/2.htm')
        self.assertEqual(parsed['supervisor'], '博导')
        for biography in ['王五教授、博士生导师曾指导张三。', '张三曾任教授、博士生导师。']:
            parsed = self.hook.parse_detail({'school': 'whu'}, prefix+biography+suffix, 'https://cse.whu.edu.cn/info/1/2.htm')
            self.assertNotIn('supervisor', parsed)


if __name__ == '__main__':
    unittest.main()
