import copy
import json
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

from crawler.notice_util import annotate_notices, classify_notice


DAY = date(2026, 11, 15)


class NoticeClassificationTests(unittest.TestCase):
    def classify(self, title, **fields):
        return classify_notice(dict(title=title, **fields), day=DAY)

    def test_recommendation_for_2027_is_past_in_november(self):
        result = self.classify('计算机学院2027年接收推荐免试研究生实施细则')
        self.assertEqual(result['admission_year'], 2027)
        self.assertIsNone(result['graduation_year'])
        self.assertEqual(result['cycle'], 'historical')

    def test_exam_2027_is_current_cycle_not_registration_claim(self):
        result = self.classify('2027年硕士研究生统考招生专业目录')
        self.assertEqual(result['admission_year'], 2027)
        self.assertEqual(result['cycle'], 'current')
        self.assertIn('不表示报名中', result['tracks'][0]['note'])

    def test_publication_and_generic_title_year_never_supply_cohort(self):
        result = self.classify('2027招生通知', publication_date='2026-11-15', title_years=[2027],
                               fetched_at='2026-11-15', seen_in_latest_list=True)
        self.assertIsNone(result['admission_year'])
        self.assertIsNone(result['graduation_year'])
        self.assertIsNone(result['activity_year'])
        self.assertEqual(result['cycle'], 'unknown')

    def test_activity_year_is_not_graduation_or_admission_year(self):
        result = self.classify('2027年计算机学院优秀大学生冬令营报名通知')
        self.assertEqual(result['activity_year'], 2027)
        self.assertIsNone(result['admission_year'])
        self.assertIsNone(result['graduation_year'])
        self.assertEqual(result['cycle'], 'unknown')

    def test_explicit_cohort_and_activity_year_are_independent(self):
        result = self.classify('面向2028届本科生的2027年冬令营报名通知')
        self.assertEqual(result['graduation_year'], 2028)
        self.assertEqual(result['activity_year'], 2027)
        self.assertIsNone(result['admission_year'])
        self.assertEqual(result['cycle'], 'preparation')

    def test_explicit_undergraduate_year_does_not_fill_admission_year(self):
        result = self.classify('接收2027年优秀应届本科毕业生免试攻读研究生实施细则')
        self.assertEqual(result['graduation_year'], 2027)
        self.assertIsNone(result['admission_year'])
        self.assertEqual(result['cycle'], 'historical')

    def test_doctoral_cohort_is_not_undergraduate_cohort(self):
        self.assertIsNone(self.classify('2028届博士毕业生就业通知')['graduation_year'])

    def test_mixed_recommendation_results_and_exam_plan_keep_both_routes(self):
        result = self.classify('学院2027年推荐免试研究生拟录取结果及统考计划公告')
        tracks = {track['route']: track for track in result['tracks']}
        self.assertEqual(result['cycle'], 'current')
        self.assertEqual(tracks['recommend']['cycle'], 'historical')
        self.assertEqual(tracks['exam']['cycle'], 'current')
        self.assertEqual(tracks['exam']['stage'], 'policy')
        self.assertEqual(result['stage'], 'mixed')
        registration = self.classify('2027年硕士研究生推免拟录取结果及统考网上报名公告')
        exam = next(track for track in registration['tracks'] if track['route'] == 'exam')
        self.assertEqual(exam['stage'], 'exam_registration')
        self.assertEqual(exam['cycle'], 'current')

    def test_general_admissions_guide_does_not_become_exam_only(self):
        result = self.classify('2027年硕士研究生招生简章')
        self.assertEqual(result['admission_year'], 2027)
        self.assertEqual(result['routes'], ['unknown'])
        self.assertEqual(result['cycle'], 'current')
        self.assertIn('不表示报名开放', result['tracks'][0]['note'])
        self.assertEqual(self.classify('2026年硕士研究生招生简章')['cycle'], 'historical')

    def test_masters_exam_procedures_do_not_require_word_unified_exam(self):
        for text, stage in (('初试安排', 'exam_arrangement'), ('网上确认通知', 'confirmation'),
                            ('网报公告', 'exam_registration'), ('准考证打印通知', 'exam_arrangement')):
            with self.subTest(text=text):
                result = self.classify('2027年硕士研究生招生' + text)
                self.assertEqual(result['routes'], ['exam'])
                self.assertEqual(result['stage'], stage)
                self.assertEqual(result['cycle'], 'current')

    def test_doctoral_exam_is_not_national_masters_exam(self):
        result = self.classify('2027年博士研究生招生初试安排')
        self.assertEqual(result['routes'], ['unknown'])

    def test_result_notice_is_never_shown_as_application(self):
        for title in ('2027年冬令营入营名单', '2027年硕士研究生统考拟录取名单',
                      '2028年接收推免生复试成绩公示'):
            with self.subTest(title=title):
                result = self.classify(title)
                self.assertEqual(result['stage'], 'results')
                self.assertTrue(all('不能作为仍接受新申请' in track['note'] for track in result['tracks']))
        self.assertEqual(self.classify('冬令营入营名单')['cycle'], 'unknown')

    def test_current_exam_results_and_qualification_remain_visible(self):
        for title, stage in (('2027年硕士研究生统考复试成绩公示', 'results'),
                             ('2027年硕士研究生统考资格审核通知', 'qualification'),
                             ('2027年硕士研究生网报不符合报考条件名单', 'qualification')):
            with self.subTest(title=title):
                result = self.classify(title)
                self.assertEqual(result['cycle'], 'current')
                self.assertEqual(result['stage'], stage)

    def test_historical_event_does_not_move_forward_on_recrawl(self):
        result = self.classify('2025年优秀大学生夏令营', fetched_at='2026-11-15', seen_in_latest_list=True)
        self.assertEqual(result['cycle'], 'historical')

    def test_only_reviewed_structured_years_are_trusted(self):
        self.assertIsNone(self.classify('冬令营通知', graduation_year=2028)['graduation_year'])
        result = self.classify('冬令营通知', graduation_year=2028, reviewed=True)
        self.assertEqual(result['graduation_year'], 2028)
        self.assertEqual(result['cycle'], 'preparation')

    def test_verified_same_url_activity_can_supply_independent_years(self):
        notice = dict(title='2027年冬令营通知', url='https://example.edu/camp', reviewed=False)
        event = dict(id='camp', source_url=notice['url'], source_state='verified', graduation_year=2028,
                     admission_year=None, camp_year=2027, verified_at='2026-11-15')
        original = copy.deepcopy(notice)
        result = classify_notice(notice, day=DAY, opportunities={'opportunities': [event]})
        self.assertEqual(result['graduation_year'], 2028)
        self.assertEqual(result['activity_year'], 2027)
        self.assertIsNone(result['admission_year'])
        self.assertEqual(result['cycle'], 'preparation')
        self.assertTrue(any('同一官方网址' in reason for reason in result['basis']))
        self.assertEqual(notice, original)
        for invalid in (dict(event, source_state='unavailable'), dict(event, source_url='https://other.edu/camp')):
            self.assertIsNone(classify_notice(notice, day=DAY, opportunities=[invalid])['graduation_year'])

    def test_conflicting_event_and_title_year_is_unknown(self):
        result = classify_notice(dict(title='2028届本科生冬令营', url='https://example.edu/camp'), day=DAY,
            opportunities=[dict(source_url='https://example.edu/camp', source_state='verified', graduation_year=2029)])
        self.assertIsNone(result['graduation_year'])
        self.assertEqual(result['cycle'], 'unknown')

    def test_multi_year_conflict_is_not_arbitrarily_resolved(self):
        result = self.classify('面向2027届本科生、2028届本科生的冬令营')
        self.assertIsNone(result['graduation_year'])
        self.assertEqual(result['cycle'], 'unknown')

    def test_annotation_preserves_original_links_and_review_status(self):
        rows = [dict(id='notice', title='2027年硕士研究生统考招生简章', school='test', dept='cs',
                     url='https://example.edu/notice', source='https://example.edu/list', reviewed=False)]
        original = copy.deepcopy(rows)
        annotated = annotate_notices(rows, day='2026-11-15')
        self.assertEqual(rows, original)
        self.assertEqual({k: v for k, v in annotated[0].items() if k != 'classification'}, original[0])

    @unittest.skipUnless(shutil.which('node'), 'Node is required for browser-rule parity')
    def test_ui_filters_do_not_mix_channels_or_unknown_cohorts(self):
        mixed = dict(classification=self.classify('2027年推荐免试研究生拟录取结果及统考计划公告'))
        unknown = dict(classification=self.classify('2027年大学生冬令营报名'))
        prepared = dict(classification=self.classify('2028届本科生2027年冬令营报名'))
        cases = [
            (mixed, dict(cycle='current', route='exam'), True),
            (mixed, dict(cycle='current', route='recommend'), False),
            (mixed, dict(cycle='historical', route='recommend'), True),
            (unknown, dict(cycle='current'), False),
            (unknown, dict(cycle='unknown'), True),
            (prepared, dict(cycle='current', graduation_year='2028'), True),
            (prepared, dict(cycle='current', admission_year='2028'), False),
            (prepared, dict(cycle='current', admission_year='unknown'), True),
        ]
        script = "const rules=require('./site/notices-core.js');const fs=require('fs');const rows=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(rows.map(([r,f])=>rules.matches(r,f))));"
        result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parent.parent,
                                input=json.dumps(cases, ensure_ascii=False), text=True, encoding='utf-8',
                                capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [case[2] for case in cases])


if __name__ == '__main__':
    unittest.main()
