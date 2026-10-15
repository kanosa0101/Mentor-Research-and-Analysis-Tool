import unittest

from test_maintenance import script


class NoticeDateV16Tests(unittest.TestCase):
    def parse(self, stamp):
        cfg = {'school': 'test', 'dept': 'cs', 'url': 'https://example.edu/list',
               'selector': 'li a', 'title_selector': 'self', 'date_selector': '.date'}
        html = f'<li><a href="/notice">2027招生通知</a><span class="date">{stamp}</span></li>'
        return script('monitor_notices').parse_list(html, cfg)[0]

    def test_visible_year_month_then_day(self):
        for stamp in ('2026-09 08', '2026-09 8', '2026-09\n08'):
            with self.subTest(stamp=stamp):
                row = self.parse(stamp)
                self.assertEqual(row['publication_date'], '2026-09-08')
                self.assertIsNone(row['admission_year'])
                self.assertIsNone(row['deadline'])
                self.assertFalse(row['reviewed'])

    def test_old_formats_remain_supported(self):
        for stamp in ('2026-09-08', '2026.09.08', '2026/09/08', '8 2026-09'):
            with self.subTest(stamp=stamp):
                self.assertEqual(self.parse(stamp)['publication_date'], '2026-09-08')
        self.assertEqual(self.parse('2024-02 29')['publication_date'], '2024-02-29')

    def test_invalid_calendar_dates_remain_unknown(self):
        for stamp in ('2026-02 29', '2026-04 31', '2026-13 01', '2026-09 00',
                      '2026-02-30', '31 2026-04', '未标日期'):
            with self.subTest(stamp=stamp):
                self.assertIsNone(self.parse(stamp)['publication_date'])
