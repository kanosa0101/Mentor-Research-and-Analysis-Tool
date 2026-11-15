import copy
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import requests
import yaml

from crawler import legacy_refresh as refresh


class LegacyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        self.original = dict(slug='teacher', name='张老师', school='test', dept='cs', status='enriched',
                             detail_url='https://test.edu.cn/teacher', email='manual@test.edu.cn',
                             research_direction_raw='旧方向', last_fetched='2026-10-01', last_verified='2026-10-01',
                             provenance={'email': {'origin': 'manual', 'source': 'https://test.edu.cn/teacher', 'fetched_at': '2026-10-01'}})

    def test_real_parse_preserves_manual_fields_and_human_review_date(self):
        original = copy.deepcopy(self.original)
        result, changed, checked = refresh.merge_profile(original, {'email': 'new@test.edu.cn', 'research_direction_raw': '机器学习'},
                                                        '<p>张老师，机器学习</p>', '2026-11-15')
        self.assertEqual(result['email'], original['email'])
        self.assertEqual(result['last_verified'], '2026-10-01')
        self.assertEqual(result['last_fetched'], '2026-11-15')
        self.assertEqual(result['research_direction_raw'], '机器学习')
        self.assertEqual(changed, ['research_direction_raw'])
        self.assertEqual(checked, ['research_direction_raw'])
        self.assertEqual(original, self.original)

    def test_identity_and_empty_parse_never_advance_freshness(self):
        for parsed, body in (({'bio_raw': '别人信息'}, '<p>其他教师</p>'), ({}, '<p>张老师</p>')):
            with self.assertRaises(ValueError):
                refresh.merge_profile(self.original, parsed, body, '2026-11-15')
        self.assertEqual(self.original['last_fetched'], '2026-10-01')

    def test_policy_refresh_is_resumable_and_keeps_reviewed_summary(self):
        sources = {key: {'url': f'https://test.edu.cn/{key}', 'format': 'html', 'selector': 'article'} for key in ('a', 'b')}
        path = self.root / 'data/admissions.yaml'
        path.write_text(yaml.safe_dump({'version': 1, 'sources': sources, 'policies': []}), encoding='utf-8')
        before = path.read_bytes()
        first = refresh.run(self.root, kind='policies', limit=1, fetcher=lambda _: b'<article>Policy text</article>')
        second = refresh.run(self.root, kind='policies', limit=1, fetcher=lambda _: b'<article>Policy text</article>')
        third = refresh.run(self.root, kind='policies', limit=1, fetcher=lambda _: self.fail('should not refetch'))
        self.assertEqual(first['results'][0]['id'], 'policy/a')
        self.assertEqual(second['results'][0]['id'], 'policy/b')
        self.assertEqual(third['attempted'], 0)
        self.assertEqual(path.read_bytes(), before)
        checks = json.loads((self.root / 'data/admissions_checks.json').read_text())
        old = copy.deepcopy(checks['a'])
        refresh.run(self.root, kind='policies', limit=2, retry=True, fetcher=lambda _: (_ for _ in ()).throw(requests.Timeout('test')))
        check = json.loads((self.root / 'data/admissions_checks.json').read_text())['a']
        self.assertEqual(check['status'], 'error')
        self.assertEqual(check['hash'], old['hash'])
        self.assertEqual(check['last_success'], old['last_success'])

    def test_failed_profile_does_not_write_record(self):
        folder = self.root / 'data/professors/test/cs'
        folder.mkdir(parents=True)
        path = folder / 'teacher.yaml'
        path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        before = path.read_bytes()
        # Missing parser configuration is a recorded failure, not a fresh profile.
        report = refresh.run(self.root, kind='professors', limit=1)
        self.assertEqual(report['error'], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_retry_prioritizes_failed_source_over_untouched_source(self):
        sources = {key: {'url': f'https://test.edu.cn/{key}', 'format': 'html', 'selector': 'article'} for key in ('a', 'b')}
        (self.root / 'data/admissions.yaml').write_text(yaml.safe_dump({'version': 1, 'sources': sources, 'policies': []}), encoding='utf-8')
        refresh.run(self.root, kind='policies', limit=1,
                    fetcher=lambda _: (_ for _ in ()).throw(requests.Timeout('test')))
        result = refresh.run(self.root, kind='policies', limit=1, retry=True,
                             fetcher=lambda _: b'<article>Policy text</article>')
        self.assertEqual(result['results'][0]['id'], 'policy/a')
        self.assertEqual(result['ok'], 1)

    def test_profile_parser_receives_decoded_text_and_records_evidence(self):
        folder = self.root / 'data/professors/test/cs'
        folder.mkdir(parents=True)
        path = folder / 'teacher.yaml'
        path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        site = self.root / 'sites/test'
        site.mkdir(parents=True)
        (site / 'cs.yaml').write_text('school: test\ndept: cs\nhook: demo\n', encoding='utf-8')
        (site / 'demo.py').write_text("def parse_detail(cfg, html, url):\n    assert isinstance(html,str)\n    return {'research_direction_raw':'机器学习'}\n", encoding='utf-8')
        result = refresh.run(self.root, kind='professors', limit=1,
                             fetcher=lambda _: '<html><meta charset="utf-8"><p>张老师</p></html>'.encode())
        self.assertEqual(result['ok'], 1)
        self.assertEqual(yaml.safe_load(path.read_text(encoding='utf-8'))['research_direction_raw'], '机器学习')
        self.assertTrue(list((self.root / 'cache/legacy_refresh/evidence').glob('*.body')))

    def test_unsupported_details_require_manual_work_without_network_or_recurring_retry(self):
        folder = self.root / 'data/professors/test/cs'
        folder.mkdir(parents=True)
        path = folder / 'teacher.yaml'
        path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        before = path.read_bytes()
        site = self.root / 'sites/test'
        site.mkdir(parents=True)
        config = site / 'cs.yaml'
        # roster_only is authoritative even when its separate roster hook is absent.
        config.write_text('school: test\ndept: cs\nhook: absent\nroster_only: true\n', encoding='utf-8')
        now = datetime.now(timezone.utc)
        no_network = lambda _: self.fail('unsupported detail must not be fetched')
        first = refresh.run(self.root, kind='professors', fetcher=no_network, now=now)
        self.assertEqual((first['ok'], first['error'], first['manual_required']), (0, 0, 1))
        later = refresh.run(self.root, kind='professors', fetcher=no_network, now=now+timedelta(days=2))
        self.assertEqual(later['attempted'], 0)
        self.assertEqual(path.read_bytes(), before)
        # A hook with only iter_roster is also explicitly unsupported, not a network failure.
        config.write_text('school: test\ndept: cs\nhook: demo\n', encoding='utf-8')
        (site / 'demo.py').write_text('def iter_roster(cfg):\n    return []\n', encoding='utf-8')
        missing_method = refresh.run(self.root, kind='professors', retry=True, fetcher=no_network)
        self.assertEqual(missing_method['results'][0]['status'], 'manual_required')
        # Explicit retry after adding a supported parser can recover the record.
        (site / 'demo.py').write_text("def parse_detail(cfg, html, url):\n    return {'research_direction_raw':'机器学习'}\n", encoding='utf-8')
        repaired = refresh.run(self.root, kind='professors', retry=True,
                               fetcher=lambda _: '<html><meta charset="utf-8"><p>张老师</p></html>'.encode())
        self.assertEqual(repaired['ok'], 1)
        self.assertIsNone(repaired['results'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
