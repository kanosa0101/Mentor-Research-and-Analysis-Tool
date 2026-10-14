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

    def test_optional_labels_and_field_event_sources_preserve_legacy(self):
        data = fixture()
        rules.validate(data, {'test': {'cs'}})
        data['sources']['pre'] = dict(data['sources']['s'], label='预报名通知')
        p = data['policies'][0]
        p['review_hashes']['pre'] = 'b' * 64
        p['fields']['materials'] = {'text': '阶段材料', 'quote': '材料', 'locator': '预报名第二条',
                                    'source_ids': ['pre']}
        p['events'] = [{'label': '阶段截止', 'kind': 'deadline', 'at': '2026-09-12',
                        'quote': '9月12日', 'locator': '预报名第三条', 'source_ids': ['s', 'pre']}]
        rules.validate(data, {'test': {'cs'}})
        with_label = rules.fingerprint(b'<div class="body">policy</div>', data['sources']['pre'])
        without_label = rules.fingerprint(b'<div class="body">policy</div>', data['sources']['s'])
        self.assertEqual(with_label, without_label)

    def test_source_labels_reject_empty_nonstring_and_extra_keys(self):
        for label in ['', '  ', None, 7]:
            with self.subTest(label=label):
                data = fixture()
                data['sources']['s']['label'] = label
                with self.assertRaisesRegex(ValueError, '来源名称'):
                    rules.validate(data, {'test': {'cs'}})
        data = fixture()
        data['sources']['s']['name'] = '非约定字段'
        with self.assertRaises(ValueError):
            rules.validate(data, {'test': {'cs'}})

    def test_field_event_sources_reject_invalid_or_unreviewed_references(self):
        invalid = [[], ['s', 's'], ['missing'], ['pre'], [''], [7], [None], 's', None, {}]
        for event in [False, True]:
            for source_ids in invalid:
                with self.subTest(event=event, source_ids=source_ids):
                    data = fixture()
                    data['sources']['pre'] = dict(data['sources']['s'])
                    p = data['policies'][0]
                    target = p['fields']['eligibility']
                    if event:
                        target = {'label': '报名截止', 'kind': 'deadline', 'at': '2026-09-12',
                                  'quote': '9月12日', 'locator': '第三条'}
                        p['events'] = [target]
                    target['source_ids'] = source_ids
                    with self.assertRaisesRegex(ValueError, '字段/事件来源'):
                        rules.validate(data, {'test': {'cs'}})

    def test_valid_field_and_event_source_references_without_labels(self):
        for event in [False, True]:
            with self.subTest(event=event):
                data = fixture()
                p = data['policies'][0]
                target = p['fields']['eligibility']
                if event:
                    target = {'label': '报名截止', 'kind': 'deadline', 'at': '2026-09-12',
                              'quote': '9月12日', 'locator': '第三条'}
                    p['events'] = [target]
                target['source_ids'] = ['s']
                rules.validate(data, {'test': {'cs'}})

    def test_reviewed_source_must_also_be_registered(self):
        data = fixture()
        p = data['policies'][0]
        p['review_hashes']['missing'] = 'b' * 64
        p['fields']['eligibility']['source_ids'] = ['missing']
        with self.assertRaises(ValueError):
            rules.validate(data, {'test': {'cs'}})


if __name__ == '__main__':
    unittest.main()
