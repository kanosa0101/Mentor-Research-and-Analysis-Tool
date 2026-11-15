import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from crawler import opportunity_monitor as monitor
from scripts import monitor_opportunities as cli


class OpportunityMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'live.json'
        self.now = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
        self.config = dict(school='test', dept='cs', name='测试计算机学院',
                           url='https://test.edu.cn/list', selector='li a',
                           title_selector='self', date_selector='.date')

    def html(self, title='2027冬令营报名通知', href='/camp', date='2026-11-01'):
        return f'<li><a href="{href}">{title}</a><span class="date">{date}</span></li>'

    def run_monitor(self, html=None, **kwargs):
        return monitor.run_once([self.config], self.output, fetcher=lambda _: html or self.html(), now=self.now, **kwargs)

    def test_initial_snapshot_is_not_newly_published_and_never_guesses_eligibility_dates(self):
        result = self.run_monitor()
        row = result['candidates'][0]
        self.assertEqual(result['summary']['new_count'], 0)
        self.assertEqual(result['summary']['baseline_count'], 1)
        self.assertEqual(row['discovery_status'], 'initial_snapshot')
        self.assertEqual(row['publication_date'], '2026-11-01')
        self.assertEqual(row['first_seen'], self.now.isoformat(timespec='seconds'))
        self.assertIsNone(row['admission_year'])
        self.assertIsNone(row['deadline'])
        self.assertFalse(row['reviewed'])
        self.assertNotIn('graduation_year', row)
        self.assertEqual(result['next_check_at'], (self.now + timedelta(hours=6)).isoformat(timespec='seconds'))

    def test_later_discovery_preserves_first_seen_and_old_publication_date(self):
        first = self.run_monitor()
        self.now += timedelta(hours=6)
        second = self.run_monitor(self.html() + self.html('本科生科研实践招募', '/research', '2026-03-01'))
        self.assertEqual(second['summary']['new_count'], 1)
        old = next(row for row in second['candidates'] if row['url'].endswith('/camp'))
        new = next(row for row in second['candidates'] if row['url'].endswith('/research'))
        self.assertEqual(old['first_seen'], first['candidates'][0]['first_seen'])
        self.assertNotEqual(old['last_seen'], old['first_seen'])
        self.assertEqual(new['publication_date'], '2026-03-01')
        self.assertEqual(new['discovery_status'], 'discovered_later')

    def test_research_program_discovery_and_source_move_are_not_new_publication(self):
        self.run_monitor()
        self.config['url'] = 'https://test.edu.cn/new-list'
        result = self.run_monitor(self.html('大学生创新实践训练计划（科创计划）报名公告', '/research'))
        self.assertEqual(result['summary']['new_count'], 0)
        self.assertEqual(result['summary']['baseline_count'], 1)
        self.assertEqual(result['sources']['test/cs']['unit'], '测试计算机学院')
        old = next(row for row in result['candidates'] if row['url'].endswith('/camp'))
        self.assertEqual(old['source_state'], 'removed')
        self.assertEqual(result['sources']['test/cs']['count'], 1)

    def test_official_title_markup_and_split_publication_date(self):
        result = self.run_monitor('<li><a href="/research" title="大学生&lt;br/&gt;科创计划报名公告">科创计划</a><span class="date">2026 09.15</span></li>')
        row = result['candidates'][0]
        self.assertEqual(row['title'], '大学生 科创计划报名公告')
        self.assertEqual(row['publication_date'], '2026-09-15')
        self.assertIsNone(row['deadline'])

    def test_error_retains_candidates_and_success_time(self):
        first = self.run_monitor()
        self.now += timedelta(hours=6)
        def fail(_):
            raise requests.Timeout('fixture timeout')
        second = monitor.run_once([self.config], self.output, fetcher=fail, now=self.now)
        self.assertEqual(second['status'], 'error')
        self.assertEqual(second['summary']['candidate_count'], 1)
        self.assertEqual(second['candidates'][0]['source_state'], 'error')
        self.assertEqual(second['candidates'][0]['last_seen'], first['candidates'][0]['last_seen'])
        self.assertEqual(second['sources']['test/cs']['last_success'], first['sources']['test/cs']['last_success'])
        self.assertIn('timeout', second['sources']['test/cs']['error'])

    def test_first_success_after_failure_still_establishes_baseline(self):
        monitor.run_once([self.config], self.output, fetcher=lambda _: '', now=self.now)
        result = self.run_monitor()
        self.assertEqual(result['summary']['new_count'], 0)
        self.assertEqual(result['summary']['baseline_count'], 1)

    def test_valid_list_without_relevant_activities_does_not_claim_parser_failure(self):
        self.run_monitor()
        result = self.run_monitor(self.html('2027硕士统考公告', '/exam'))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['sources']['test/cs']['count'], 0)
        self.assertFalse(result['candidates'][0]['seen_in_latest_list'])

    def test_irrelevant_and_external_links_are_excluded(self):
        content = ''.join(self.html(title, '/' + str(index)) for index, title in enumerate([
            '大学生冬令营报名', '预推免报名', '2027夏令营录取名单', '中学生冬令营', '海外访学夏令营']))
        content += self.html('大学生冬令营', 'https://other.example/camp')
        result = self.run_monitor(content)
        self.assertEqual(len(result['candidates']), 2)

    def test_removed_source_retains_history_with_removed_status(self):
        self.run_monitor()
        result = monitor.run_once([], self.output, now=self.now)
        self.assertEqual(result['candidates'][0]['source_state'], 'removed')
        self.assertEqual(result['summary']['source_count'], 0)

    def test_source_hash_changes_never_rewrite_public_summary(self):
        opportunity = dict(id='camp', source_state='verified', source_url='https://test.edu.cn/original',
                           source_sha256=hashlib.sha256(b'original').hexdigest(), eligibility=['keep original'])
        original = copy.deepcopy(opportunity)
        result = monitor.run_once([], self.output, [opportunity], fetcher=lambda _: b'changed', now=self.now)
        self.assertEqual(result['opportunity_checks']['camp']['status'], 'changed')
        self.assertEqual(result['summary']['changed_count'], 1)
        self.assertEqual(opportunity, original)
        self.assertNotIn('eligibility', result['opportunity_checks']['camp'])
        result = monitor.run_once([], self.output, [dict(opportunity, source_sha256='')], fetcher=lambda _: b'changed', now=self.now)
        self.assertEqual(result['opportunity_checks']['camp']['status'], 'unbased')

    def test_successful_unchanged_hash_and_failed_recheck_are_distinct(self):
        opportunity = dict(id='camp', source_state='verified', source_url='https://test.edu.cn/original',
                           source_sha256=hashlib.sha256(b'original').hexdigest())
        first = monitor.run_once([], self.output, [opportunity], fetcher=lambda _: b'original', now=self.now)
        self.assertEqual(first['opportunity_checks']['camp']['status'], 'unchanged')
        def fail(_):
            raise requests.ConnectionError('offline')
        result = monitor.run_once([], self.output, [opportunity], fetcher=fail, now=self.now + timedelta(hours=6))
        self.assertEqual(result['opportunity_checks']['camp']['status'], 'error')
        self.assertEqual(result['opportunity_checks']['camp']['last_success'], first['checked_at'])
        self.assertEqual(result['status'], 'partial')

    def test_lock_blocks_duplicate_monitor_and_releases_after_exit(self):
        with monitor.output_lock(self.output):
            with self.assertRaisesRegex(RuntimeError, '重复启动'):
                self.run_monitor()
        self.assertEqual(self.run_monitor()['status'], 'ok')

    def test_corrupt_previous_file_is_preserved(self):
        self.output.write_text('{broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.run_monitor()
        self.assertEqual(self.output.read_text(encoding='utf-8'), '{broken')

    def test_failed_atomic_replace_preserves_previous_file(self):
        self.run_monitor()
        before = self.output.read_bytes()
        with patch.object(monitor.os, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                self.run_monitor(self.html('新冬令营', '/new'))
        self.assertEqual(self.output.read_bytes(), before)
        self.assertFalse(list(self.output.parent.glob('*.tmp')))

    def test_cli_single_run_and_watch_keyboard_exit_do_not_install_scheduler(self):
        config = self.output.with_suffix('.yaml')
        config.write_text('targets: []\n', encoding='utf-8')
        argv = ['--config', str(config), '--output', str(self.output), '--opportunities', str(self.output.parent / 'missing.json')]
        with patch('builtins.print'):
            self.assertEqual(cli.main(argv), 0)
            with patch.object(cli.threading.Event, 'wait', side_effect=KeyboardInterrupt):
                self.assertEqual(cli.main([*argv, '--watch']), 0)
        with monitor.output_lock(self.output):
            pass

    def test_fetch_honors_timeout_and_keeps_tls_verification(self):
        with patch.object(monitor.requests, 'Session') as factory:
            session = factory.return_value.__enter__.return_value
            session.request.return_value.status_code = 200
            session.request.return_value.content = b'content'
            self.assertEqual(monitor.fetch_source(self.config, 9), b'content')
            self.assertEqual(session.request.call_args.kwargs['timeout'], 9)
            self.assertNotIn('verify', session.request.call_args.kwargs)
            self.assertFalse(session.trust_env)


if __name__ == '__main__':
    unittest.main()
