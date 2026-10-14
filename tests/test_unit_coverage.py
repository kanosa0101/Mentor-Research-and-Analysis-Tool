import unittest
from scripts.build_site import unit_coverage


class UnitCoverageTests(unittest.TestCase):
    def test_empty_roster_is_not_zero_information_claim(self):
        result = unit_coverage([])
        self.assertEqual(result['email'], 0)
        self.assertEqual(result['source_dates'], {'known': 0, 'unknown': 0, 'earliest': '', 'latest': ''})

    def test_explicit_fields_and_dates_no_direction_inference(self):
        result = unit_coverage([
            {'email': 'a@example.edu', 'bio_raw': '研究机器学习', 'source_date': '2026-10-14'},
            {'supervisor': '硕导', 'research_direction_raw': '控制', 'source_date': '2026-09-05'},
            {'email': '', 'source_date': ''},
        ])
        self.assertEqual([result[k] for k in ['email', 'research_direction_raw', 'bio_raw', 'supervisor']], [1, 1, 1, 1])
        self.assertEqual(result['source_dates'], {'known': 2, 'unknown': 1, 'earliest': '2026-09-05', 'latest': '2026-10-14'})


if __name__ == '__main__':
    unittest.main()
