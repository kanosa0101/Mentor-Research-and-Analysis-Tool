import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from crawler.admissions_entries import load_catalog, load_entries, source_status, validate_entries
from test_maintenance import script


class AdmissionEntryTests(unittest.TestCase):
    def setUp(self):
        self.units = {'known': {'cs'}, 'no_unit': set()}
        self.sources = {'school': {'url': 'https://example.edu/admissions'},
                        'dept': {'url': 'https://example.edu/cs/admissions'}}
        self.entry = {'school': 'known', 'dept': '', 'source_id': 'school', 'reviewed_at': '2026-10-15'}

    def test_strict_contract_and_multiple_verified_sources_for_one_scope(self):
        data = {'version': 1, 'entries': [self.entry, dict(self.entry, source_id='dept')]}
        before = copy.deepcopy(data)
        validate_entries(data, self.units, self.sources)
        self.assertEqual(data, before)
        for bad in [dict(data, version=True), dict(data, extra=True), {'version': 1, 'entries': None},
                    {'version': 1, 'entries': [self.entry, self.entry]}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_entries(bad, self.units, self.sources)

    def test_rejects_wrong_scope_reference_and_review_dates(self):
        for key, value in [('school', 'missing'), ('dept', 'wrong'), ('source_id', 'missing'),
                           ('reviewed_at', '2099-01-01'), ('reviewed_at', '2026-02-30'),
                           ('reviewed_at', None), ('note', ''), ('note', 4), ('extra', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_entries({'version': 1, 'entries': [dict(self.entry, **{key: value})]}, self.units, self.sources)
        validate_entries({'version': 1, 'entries': [dict(self.entry, school='no_unit')]}, self.units, self.sources)

    def test_catalog_keeps_configured_schools_without_inventing_departments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'sites/known').mkdir(parents=True)
            (root / 'data/schools.yaml').write_text(yaml.safe_dump({'schools': [
                {'id': 'known', 'name': '已接入学校'}, {'id': 'no_unit', 'name': '待接入学校'}]}, allow_unicode=True), encoding='utf-8')
            (root / 'sites/known/cs.yaml').write_text('school: known\ndept: cs\ndept_name: 计算机\n', encoding='utf-8')
            schools, units = load_catalog(root)
            self.assertEqual(schools, [{'id': 'known', 'name': '已接入学校'}, {'id': 'no_unit', 'name': '待接入学校'}])
            self.assertEqual(units, self.units)
            self.assertEqual(load_entries(root, units, self.sources), [])
            (root / 'data/admissions_entries.yaml').write_text('version: 1\nentries: []\n', encoding='utf-8')
            self.assertEqual(load_entries(root, units, self.sources), [])

    def test_failed_or_unchecked_sources_do_not_claim_success(self):
        failed = {'status': 'error', 'last_success': '2026-10-14', 'last_attempt': '2026-10-15', 'hash': 'a' * 64}
        self.assertEqual(source_status(self.entry, failed, '2026-10-15')['state'], 'error')
        self.assertEqual(source_status(self.entry, failed, '2026-10-15')['last_success'], '2026-10-14')
        self.assertEqual(source_status(self.entry, {}, '2026-10-15')['state'], 'unknown')
        ok = dict(failed, status='ok')
        self.assertEqual(source_status(self.entry, ok, '2026-10-15')['state'], 'checked')
        self.assertEqual(source_status(self.entry, dict(ok, last_success='2026-10-01'), '2026-10-15')['state'], 'stale')
        self.assertEqual(source_status(dict(self.entry, reviewed_at='2026-09-01'), ok, '2026-10-15')['state'], 'review')

    def test_coverage_denominators_and_unselected_program_remain_distinct(self):
        report = script('report_admissions_coverage')
        source = {'url': 'https://example.edu/policy', 'format': 'html', 'selector': '.body'}
        policy = {'id': 'school', 'school': 'known', 'dept': '', 'level': 'school', 'year': 2027,
                  'degree': 'master', 'route': 'exam', 'track': 'general', 'program': '', 'program_code': '',
                  'reviewed_at': '2026-10-15', 'source_id': 'school', 'review_hashes': {'school': 'a' * 64},
                  'fields': {'materials': {'text': '学校材料'}}}
        program = dict(policy, id='program', dept='cs', level='program', program='计算机技术', program_code='085404')
        special = dict(policy, id='special', dept='cs', level='dept', track='special')
        data = {'sources': {'school': source}, 'policies': [policy, program, special]}
        schools = [{'id': 'known', 'name': '已接入'}, {'id': 'no_unit', 'name': '待接入'}]
        result = report.build_report(schools, self.units, data, [self.entry], {}, today='2026-10-15')
        self.assertEqual(result['denominators'], {'schools': 2, 'schools_with_units': 1, 'units': 1})
        unit = next(r for r in result['rows'] if r['dept'] == 'cs')
        self.assertEqual(unit['school_policy_ids'], ['school'])
        self.assertEqual(unit['dept_policy_ids'], [])
        self.assertEqual(unit['program_policy_ids'], [])
        self.assertEqual(unit['available_program_policy_ids'], ['program'])
        self.assertIn('院系附加要求未整理', unit['gaps'])
        self.assertIn('专业未指定，专属条款不计覆盖', unit['gaps'])
        self.assertNotIn('special', unit['dept_policy_ids'])
        pending = next(r for r in result['rows'] if r['school'] == 'no_unit')
        self.assertIn('院系目录待接入', pending['gaps'])

    def test_shared_source_does_not_hide_old_summary_review_date(self):
        report = script('report_admissions_coverage')
        base = {'id': 'old', 'school': 'known', 'dept': '', 'level': 'school', 'year': 2027,
                'degree': 'master', 'route': 'exam', 'track': 'general', 'program': '', 'program_code': '',
                'reviewed_at': '2026-09-01', 'review_hashes': {'school': 'a' * 64}, 'fields': {}}
        data = {'policies': [base, dict(base, id='new', reviewed_at='2026-10-15')]}
        checks = {'school': {'status': 'ok', 'hash': 'a' * 64, 'last_attempt': '2026-10-15', 'last_success': '2026-10-15'}}
        result = report.build_report([{'id': 'known', 'name': '学校'}], self.units, data, [], checks, today='2026-10-15')
        row = result['rows'][0]
        self.assertEqual(row['source_states'], {'school': 'checked'})
        self.assertEqual(row['summary_review_due'], ['old'])

    def test_named_special_at_any_level_is_program_specific(self):
        report = script('report_admissions_coverage')
        for level, dept in [('school', ''), ('dept', 'cs'), ('program', 'cs')]:
            policy = {'id': 'named', 'school': 'known', 'dept': dept, 'level': level, 'year': 2027,
                      'degree': 'master', 'route': 'exam', 'track': 'special', 'program': '特定专项', 'program_code': '085400',
                      'reviewed_at': '2026-10-15', 'review_hashes': {}, 'fields': {}}
            for program, covered in [('', False), ('085400|另一专项', False), ('085400|特定专项', True)]:
                with self.subTest(level=level, program=program):
                    rows = report.build_report([{'id': 'known', 'name': '学校'}], self.units, {'policies': [policy]}, [], {},
                                               track='special', program=program, today='2026-10-15')['rows']
                    row = next(r for r in rows if r['dept'] == 'cs')
                    self.assertEqual(row['school_policy_ids'], [])
                    self.assertEqual(row['dept_policy_ids'], [])
                    self.assertEqual(row['program_policy_ids'], ['named'] if covered else [])


if __name__ == '__main__':
    unittest.main()
