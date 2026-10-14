import copy
import unittest
from unittest.mock import patch

from crawler import admissions_util as rules


def fixture():
    return {'version': 1, 'sources': {'s': {'url': 'https://example.edu/policy', 'selector': '.body', 'format': 'html'}},
            'policies': [{'id': 'test-2027', 'school': 'test', 'dept': '', 'level': 'school', 'title': '招生规则',
                          'year': 2027, 'degree': 'master', 'route': 'exam', 'program': '', 'program_code': '',
                          'published_at': '2026-10-08', 'reviewed_at': '2026-10-14',
                          'review_hashes': {'s': 'a' * 64}, 'source_id': 's',
                          'fields': {'eligibility': {'text': '条件摘要', 'quote': '条件', 'locator': '第三条'}}}]}


class AdmissionsTests(unittest.TestCase):
    def test_validated_scope_and_references(self):
        rules.validate(fixture(), {'test': {'cs'}})
        for key, value in [('year', True), ('route', 'summer'), ('dept', 'wrong'), ('level', 'program'), ('source_id', 'bad')]:
            bad = fixture()
            bad['policies'][0][key] = value
            with self.assertRaises(ValueError):
                rules.validate(bad, {'test': {'cs'}})

    def test_evidence_and_http_sources_required(self):
        for part in ['quote', 'locator', 'text']:
            bad = fixture()
            bad['policies'][0]['fields']['eligibility'][part] = ''
            with self.assertRaises(ValueError):
                rules.validate(bad, {'test': {'cs'}})
        bad = fixture()
        bad['sources']['s']['url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            rules.validate(bad, {'test': {'cs'}})

    def test_fingerprint_uses_content_and_attachment_links(self):
        source = fixture()['sources']['s']
        a = b'<nav>old</nav><div class="body">policy<a href="a.pdf">pdf</a></div>'
        b = b'<nav>new</nav><div class="body">policy<a href="a.pdf">pdf</a></div>'
        self.assertEqual(rules.fingerprint(a, source), rules.fingerprint(b, source))
        self.assertNotEqual(rules.fingerprint(a, source), rules.fingerprint(b.replace(b'a.pdf', b'b.pdf'), source))
        with self.assertRaises(ValueError):
            rules.fingerprint(b'<html>login</html>', source)

    def test_cache_does_not_advance_success_date(self):
        source = fixture()['sources']['s']
        with patch.object(rules.fetch, 'fetch', return_value=(b'<div class="body">policy</div>', {'fetched_at': '2026-09-01'}, True)):
            result = rules.check_source(source, {}, False, '2026-10-14')
        self.assertEqual(result['last_success'], '2026-09-01')
        self.assertTrue(result['cached'])

    def test_cache_cannot_clear_a_failed_live_check(self):
        old = {'status': 'error', 'error': 'network failed', 'last_success': '2026-10-13', 'hash': 'a' * 64}
        with patch.object(rules.fetch, 'fetch', return_value=(b'<div class="body">policy</div>', {'fetched_at': '2026-10-13'}, True)):
            result = rules.check_source(fixture()['sources']['s'], old, False, '2026-10-14')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], old['error'])

    def test_failure_preserves_last_success_and_hash(self):
        old = {'last_success': '2026-10-01', 'hash': 'a' * 64, 'status': 'ok'}
        with patch.object(rules.fetch, 'fetch', side_effect=ValueError('offline')):
            result = rules.check_source(fixture()['sources']['s'], old, True, '2026-10-14')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['last_success'], old['last_success'])
        self.assertEqual(result['hash'], old['hash'])

    def test_changed_source_never_modifies_human_record(self):
        data = fixture()
        before = copy.deepcopy(data)
        with patch.object(rules.fetch, 'fetch', return_value=(b'<div class="body">new policy</div>', {'fetched_at': '2026-10-14'}, False)):
            result = rules.check_source(data['sources']['s'], {}, True, '2026-10-14')
        self.assertNotEqual(result['hash'], data['policies'][0]['review_hashes']['s'])
        self.assertEqual(data, before)

    def test_checks_validate_without_inventing_success(self):
        rules.validate_checks({'s': {'status': 'error', 'last_attempt': '2026-10-14', 'error': 'offline'}}, fixture()['sources'])
        for value in [{'status': 'ok', 'last_attempt': '2026-10-14'},
                      {'status': 'fake', 'last_attempt': '2026-10-14'},
                      {'status': 'ok', 'hash': 'a' * 64, 'last_success': '2099-01-01', 'last_attempt': '2026-10-14'}]:
            with self.assertRaises(ValueError):
                rules.validate_checks({'s': value}, fixture()['sources'])

    def test_special_track_and_timed_events_are_explicit(self):
        data = fixture()
        p = data['policies'][0]
        p['track'] = 'special'
        p['events'] = [{'label': '报名截止', 'kind': 'deadline', 'at': '2026-09-12T09:00:00+08:00', 'quote': '9月12日', 'locator': '第三节'}]
        rules.validate(data, {'test': {'cs'}})
        p['events'][0]['at'] = '2026-09-12T09:00:00'
        with self.assertRaises(ValueError):
            rules.validate(data, {'test': {'cs'}})


if __name__ == '__main__':
    unittest.main()
