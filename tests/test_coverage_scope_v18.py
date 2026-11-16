import copy
import unittest

from test_maintenance import script


class CoverageScopeTests(unittest.TestCase):
    def setUp(self):
        self.report = script('report_admissions_coverage')
        self.entries = [
            dict(school='s', dept='', source_id='master', reviewed_at='2026-10-15', year=2027, degree='master', route='exam'),
            dict(school='s', dept='', source_id='unknown', reviewed_at='2026-10-15'),
            dict(school='s', dept='cs', source_id='phd', reviewed_at='2026-10-15', year=2027, degree='phd', route='assessment'),
        ]

    def rows(self, entries=None, **scope):
        return self.report.build_report(
            [{'id': 's', 'name': '学校'}], {'s': {'cs'}}, {'sources': {}, 'policies': []},
            self.entries if entries is None else entries, {},
            degree='phd', route='assessment', today='2026-10-15', **scope)['rows']

    def test_other_degree_and_unknown_navigation_do_not_hide_scope_gap(self):
        before = copy.deepcopy(self.entries)
        school, dept = self.rows()
        self.assertEqual(school['entry_scope_counts'], {'matching': 0, 'unknown': 1, 'other': 1})
        self.assertIn('本层年度、学位与渠道明确匹配的招生入口未登记', school['gaps'])
        self.assertEqual([e['scope'] for e in school['entries']], ['other', 'unknown'])
        self.assertEqual(dept['entry_scope_counts'], {'matching': 1, 'unknown': 0, 'other': 0})
        self.assertNotIn('本层年度、学位与渠道明确匹配的招生入口未登记', dept['gaps'])
        self.assertEqual(dept['entries'][0]['status']['state'], 'unknown')
        self.assertEqual(self.entries, before)

    def test_empty_layer_keeps_absent_navigation_distinct(self):
        school, dept = self.rows(entries=[])
        for row in (school, dept):
            self.assertIn('本层官方招生入口未登记', row['gaps'])
            self.assertIn('本层年度、学位与渠道明确匹配的招生入口未登记', row['gaps'])
            self.assertEqual(row['entry_scope_counts'], {'matching': 0, 'unknown': 0, 'other': 0})

    def test_known_mismatch_on_any_axis_wins_over_missing_scope(self):
        entries = [dict(self.entries[0], degree='phd', year=2026),
                   dict(self.entries[0], degree='phd', route='recommend'),
                   {k: v for k, v in dict(self.entries[0], degree='phd').items() if k != 'route'}]
        row = self.rows(entries=entries)[0]
        self.assertEqual(row['entry_scope_counts'], {'matching': 0, 'unknown': 1, 'other': 2})

    def test_conditional_reporting_point_is_not_unconditional_school_coverage(self):
        policy = dict(id='point', school='s', dept='', level='school', year=2027,
                      degree='master', route='exam', track='ordinary', program='', program_code='',
                      reviewed_at='2026-10-15', review_hashes={}, fields={'materials': {'text': '报考点材料'}},
                      applies_if={'text': '仅6112报考点', 'quote': '6112', 'locator': '二'})
        rows = self.report.build_report([{'id': 's', 'name': '学校'}], {'s': {'cs'}},
                                        {'sources': {}, 'policies': [policy]}, [], {}, today='2026-10-15')['rows']
        for row in rows:
            self.assertEqual(row['school_policy_ids'], [])
            self.assertEqual(row['fields_by_layer']['school'], [])
            self.assertEqual(row['conditional_policy_ids'], ['point'])
            self.assertIn('学校规则未整理', row['gaps'])

    def test_material_actions_keep_conditional_and_program_scope_visible(self):
        policy = dict(id='school', school='s', dept='', level='school', year=2027,
                      degree='master', route='exam', track='ordinary', program='', program_code='',
                      reviewed_at='2026-10-15', review_hashes={}, fields={'materials': {'text': '材料'}},
                      material_actions=[{'id': 'upload', 'stage': 'application'},
                                        {'id': 'check', 'stage': 'enrollment', 'applies_if': {'text': '应届生'}}])
        specific = dict(policy, id='specific', dept='cs', level='program', program='计算机技术', program_code='085404')
        rows = self.report.build_report([{'id': 's', 'name': '学校'}], {'s': {'cs'}},
                                        {'sources': {}, 'policies': [policy, specific]}, [], {}, today='2026-10-15')['rows']
        self.assertEqual(rows[1]['material_actions'], [
            {'policy_id': 'school', 'action_id': 'upload', 'stage': 'application', 'conditional': False},
            {'policy_id': 'school', 'action_id': 'check', 'stage': 'enrollment', 'conditional': True}])
        self.assertNotIn('分阶段材料动作未整理', rows[1]['gaps'])


if __name__ == '__main__':
    unittest.main()
