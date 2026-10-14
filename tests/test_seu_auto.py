import json
import unittest
from unittest.mock import patch

from test_maintenance import script


class SeuAutoTests(unittest.TestCase):
    def setUp(self):
        self.hook = script('..\\sites\\seu_auto')
        self.cfg = {'base_url': 'https://automation.seu.edu.cn', 'list': {'urls': ['https://automation.seu.edu.cn/32668/list.htm']}}

    def row(self, name='张三', post='教授', category='全体教师,博士生导师', url='/zs/list.htm'):
        return {'title': name, 'post': post, 'exField1': category, 'cnUrl': url}

    def test_list_fields_are_academic_and_not_degree_or_admin(self):
        rows = [self.row(), self.row('李四', '院办主任', '全体教师', '/ls/list.htm'),
                self.row('王五', '', '硕士生导师', '/ww/list.htm'),
                self.row('杨超群Chaoqun Yang', '副教授', '全体教师', '/ycq/list.htm')]
        result = self.hook.collect(self.cfg, rows, '2026-10-14')
        self.assertEqual([r['name'] for r in result], ['张三', '王五', '杨超群'])
        self.assertEqual(result[0]['supervisor'], '博导')
        self.assertNotIn('title', result[1])
        self.assertEqual(result[0]['roster_source'], self.cfg['list']['urls'][0])

    def test_pagination_follows_actual_page_count_not_requested_rows(self):
        a = {'total': 2, 'pageCount': 2, 'data': [self.row()]}
        b = {'total': 2, 'pageCount': 2, 'data': [self.row('李四', url='/ls/list.htm')]}
        with patch.object(self.hook.fetch, 'fetch_text', side_effect=[(json.dumps(a), {'fetched_at': '2026-10-14'}, False), (json.dumps(b), {'fetched_at': '2026-10-14'}, False)]) as get:
            rows, meta = self.hook.iter_roster(self.cfg)
        self.assertEqual(len(rows), 2)
        self.assertEqual(meta['raw_total'], 2)
        self.assertEqual(get.call_args_list[1].args[2]['pageIndex'], 2)

    def test_partial_or_untrusted_list_fails_before_store(self):
        for value in [{'total': 2, 'pageCount': 1, 'data': [self.row()]},
                      {'total': 1, 'pageCount': 1, 'data': [self.row(url='https://evil.example/person')]}]:
            with patch.object(self.hook.fetch, 'fetch_text', return_value=(json.dumps(value), {'fetched_at': '2026-10-14'}, False)):
                with self.assertRaises(ValueError):
                    self.hook.iter_roster(self.cfg)

    def test_detail_uses_header_and_scoped_content(self):
        h = '<nav>教授 博士生导师 webmaster@seu.edu.cn</nav><div class="carrer"><div class="title"><span class="xing">王五</span><span>博士</span><span>副教授</span><span>硕士生导师</span></div><div class="text">邮箱:ww@seu.edu.cn</div></div><div class="tearchContainer"><div class="news_box"><div class="tit">基本信息</div><div class="con">王五，副教授。曾任助教。</div></div><div class="news_box"><div class="tit">研究兴趣</div><div class="con">机器学习、机器人</div></div></div>'
        d = self.hook.parse_detail(self.cfg, h, 'https://automation.seu.edu.cn/ww/list.htm')
        self.assertEqual(d['title'], '副教授')
        self.assertEqual(d['supervisor'], '硕导')
        self.assertEqual(d['email'], 'ww@seu.edu.cn')
        self.assertEqual(d['research_directions'], ['机器学习、机器人'])
        self.assertNotIn('webmaster', d['bio_raw'])
        with self.assertRaises(ValueError):
            self.hook.parse_detail(self.cfg, '<html>blocked</html>', 'https://automation.seu.edu.cn/ww/list.htm')

    def test_known_source_count_gap_is_explicit_partial(self):
        self.cfg['list']['verified_counts'] = {'reported': 2, 'returned': 1, 'pages': 1}
        value = {'total': 2, 'pageCount': 1, 'data': [self.row()]}
        with patch.object(self.hook.fetch, 'fetch_text', return_value=(json.dumps(value), {'fetched_at': '2026-10-14'}, False)):
            rows, meta = self.hook.iter_roster(self.cfg)
        self.assertEqual(len(rows), 1)
        self.assertTrue(meta['partial'])
        self.assertEqual(meta['raw_total'], 2)
        self.assertEqual(meta['returned_total'], 1)

    def test_real_pilot_rejects_unknown_count_shrinkage(self):
        from pathlib import Path
        import yaml
        cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / 'sites/seu/auto.yaml').read_text(encoding='utf-8'))
        value = {'total': 114, 'pageCount': 1, 'data': [self.row()]}
        with patch.object(self.hook.fetch, 'fetch_text', return_value=(json.dumps(value), {'fetched_at': '2026-10-14'}, False)):
            with self.assertRaises(ValueError):
                self.hook.iter_roster(cfg)

    def test_verified_gap_rejects_unverified_return_count_or_page_count(self):
        self.cfg['list']['verified_counts'] = {'reported': 4, 'returned': 2, 'pages': 2}
        for responses in [
            [{'total': 4, 'pageCount': 1, 'data': [self.row(), self.row('李四', url='/ls/list.htm')]}],
            [{'total': 4, 'pageCount': 2, 'data': [self.row()]},
             {'total': 4, 'pageCount': 2, 'data': [self.row('李四', url='/ls/list.htm'), self.row('王五', url='/ww/list.htm')]}],
        ]:
            with patch.object(self.hook.fetch, 'fetch_text', side_effect=[(json.dumps(r), {'fetched_at': '2026-10-14'}, False) for r in responses]):
                with self.assertRaises(ValueError):
                    self.hook.iter_roster(self.cfg)


if __name__ == '__main__':
    unittest.main()
