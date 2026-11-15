import copy
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch
from pathlib import Path

from crawler.opportunity_util import state, validate


class ApplicationWindowTests(unittest.TestCase):
    def setUp(self):
        catalog = json.loads((Path(__file__).resolve().parents[1] / 'data/opportunities.json').read_text(encoding='utf8'))
        self.item = copy.deepcopy(next(o for o in catalog['opportunities'] if o['id'] == 'iscas-research-2026'))
        self.item.update(deadline='', event_end='', registration_start='2026-10-28',
                         source_state='verified', checked_at='2026-11-15', verified_at='2026-11-15', cycle='current')
        self.item.pop('application_window', None)

    def test_unknown_deadline_does_not_become_open_without_evidence(self):
        self.assertEqual(state(self.item, date(2026, 11, 15)), 'unknown')

    def test_precise_deadline_compares_timezone_aware_instants(self):
        self.item['deadline'] = '2026-11-15T17:00:00+08:00'
        with patch('crawler.opportunity_util.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat('2026-11-15T08:59:00+00:00')
            self.assertEqual(state(self.item, date(2026, 11, 15)), 'open')
            clock.now.return_value = datetime.fromisoformat('2026-11-15T09:01:00+00:00')
            self.assertEqual(state(self.item, date(2026, 11, 15)), 'closed')

    def test_rolling_is_distinct_from_dated_registration_and_expires_with_review(self):
        self.item['application_window'] = dict(mode='rolling', end_month='', quote='长期招收本科科研实习生')
        validate(self.item)
        self.assertEqual(state(self.item, date(2026, 11, 15)), 'rolling')
        self.assertEqual(state(self.item, date(2026, 11, 23)), 'review')
        self.item['source_state'] = 'unavailable'
        self.assertEqual(state(self.item, date(2026, 11, 15)), 'review')

    def test_month_precision_never_invents_the_last_day(self):
        self.item['application_window'] = dict(mode='month', end_month='2027-01', quote='报名时间即日起至2027年1月。')
        validate(self.item)
        self.assertEqual(state(self.item, date(2026, 11, 15)), 'open_month')
        self.item.update(checked_at='2027-01-01', verified_at='2027-01-01')
        self.assertEqual(state(self.item, date(2027, 1, 1)), 'unknown')
        self.item.update(checked_at='2027-02-01', verified_at='2027-02-01')
        self.assertEqual(state(self.item, date(2027, 2, 1)), 'closed')

    def test_ended_event_is_closed_even_if_its_record_has_a_later_deadline(self):
        self.item.update(event_end='2026-11-14', deadline='2026-12-01')
        self.assertEqual(state(self.item, date(2026, 11, 15)), 'closed')

    def test_conflicting_or_unbound_precision_rejected(self):
        for window in (dict(mode='rolling', end_month='2027-01', quote='长期招收'),
                       dict(mode='month', end_month='2027-13', quote='明年截止'),
                       dict(mode='month', end_month='2026-01', quote='2026年1月'),
                       dict(mode='rolling', end_month='', quote='')):
            with self.subTest(window=window), self.assertRaises(ValueError):
                validate(dict(self.item, application_window=window))
        with self.assertRaises(ValueError):
            validate(dict(self.item, deadline='2027-01-31',
                          application_window=dict(mode='month', end_month='2027-01', quote='2027年1月')))
