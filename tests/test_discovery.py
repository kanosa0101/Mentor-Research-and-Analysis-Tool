import unittest
from urllib.error import HTTPError
from urllib.request import Request

import test_workflow


class DiscoveryTests(unittest.TestCase):
    setUp = test_workflow.WorkflowTests.setUp
    close_server = test_workflow.WorkflowTests.close_server
    request = test_workflow.WorkflowTests.request

    def review(self, year=2027):
        return {'mentor_id': self.pid, 'year': year, 'degree': 'master', 'route': 'recommend',
                'opportunity': 'pass', 'eligibility': 'unknown', 'source_url': 'https://example.edu/notice',
                'quote': '该年度接收推免硕士，具体条件见简章', 'confirmed': True}

    def test_read_does_not_create_private_file(self):
        code, data = self.request('/api/discovery')
        self.assertEqual(code, 200)
        self.assertEqual(data['reviews'], {})
        self.assertFalse(self.outreach.with_name('discovery.yaml').exists())

    def test_preferences_save_and_invalid_inputs_do_not_write(self):
        prefs = self.request('/api/discovery')[1]['preferences']
        prefs.update(year=2027, degree='master', route='recommend', topics=['时空预测'], schools=['test'])
        self.assertEqual(self.request('/api/discovery', prefs, 'POST')[0], 200)
        path = self.outreach.with_name('discovery.yaml')
        before = path.read_bytes()
        for key, value in [('year', True), ('degree', 'fake'), ('schools', ['unknown']), ('topics', 'x'), ('keep_unknown', 1)]:
            bad = dict(prefs, **{key: value})
            self.assertEqual(self.request('/api/discovery', bad, 'POST')[0], 400)
            self.assertEqual(before, path.read_bytes())

    def test_review_requires_explicit_confirmation_and_evidence(self):
        for body in [dict(self.review(), confirmed=False), dict(self.review(), quote=''),
                     dict(self.review(), source_url='javascript:alert(1)'), dict(self.review(), mentor_id='unknown')]:
            self.assertEqual(self.request('/api/discovery/reviews', body, 'POST')[0], 400)
        self.assertFalse(self.outreach.with_name('discovery.yaml').exists())

    def test_reviews_are_scoped_by_year_route_and_degree(self):
        code, a = self.request('/api/discovery/reviews', self.review(), 'POST')
        self.assertEqual(code, 200, a)
        code, b = self.request('/api/discovery/reviews', self.review(2028), 'POST')
        self.assertEqual(code, 200, b)
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(len(self.request('/api/discovery')[1]['reviews']), 2)
        self.assertEqual(self.request('/api/discovery/reviews', self.review(), 'POST')[1]['id'], a['id'])

    def test_backup_restore_and_corrupt_file_recovery(self):
        self.request('/api/discovery/reviews', self.review(), 'POST')
        backup = self.request('/api/discovery/backup')[1]
        path = self.outreach.with_name('discovery.yaml')
        old = path.read_bytes()
        path.write_bytes(b'broken: [')
        self.assertEqual(self.request('/api/discovery/restore', backup, 'POST')[0], 200)
        self.assertEqual(path.read_bytes(), old)
        backup['discovery']['reviews'][next(iter(backup['discovery']['reviews']))]['mentor_id'] = 'unknown'
        self.assertEqual(self.request('/api/discovery/restore', backup, 'POST')[0], 400)
        self.assertEqual(path.read_bytes(), old)

    def test_cross_site_reads_and_writes_rejected(self):
        for method in ['GET', 'POST']:
            req = Request(self.base + '/api/discovery', method=method, data=b'{}' if method == 'POST' else None,
                          headers={'Sec-Fetch-Site': 'cross-site', 'Content-Type': 'application/json'})
            with self.assertRaises(HTTPError) as error:
                self.http.open(req)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()


if __name__ == '__main__':
    unittest.main()
