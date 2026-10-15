import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from test_maintenance import script


class PolicyOnlyUnitTests(unittest.TestCase):
    def test_pending_roster_does_not_pretend_to_have_a_crawler(self):
        crawl = script('crawl')
        cfg = {'school': 'tju', 'dept': 'software', 'dept_name': '软件学院',
               'roster_pending': '已接入招生政策，导师名册尚未采集'}
        with patch.object(sys, 'argv', ['crawl.py', '--school', 'tju', '--dept', 'software']), \
                patch.object(crawl, 'load_cfg', return_value=cfg), \
                patch.object(crawl, 'load_hook') as hook, \
                patch.object(crawl.fetch, 'set_direct') as direct:
            with self.assertRaisesRegex(SystemExit, '师资采集尚未接入'):
                crawl.main()
            hook.assert_not_called()
            direct.assert_not_called()

    def test_policy_only_units_have_real_navigation_and_pending_rosters(self):
        root = Path(__file__).resolve().parents[1]
        for dept, code in [('software', '218'), ('cyber', '257'), ('ai', '258')]:
            cfg = yaml.safe_load((root / f'sites/tju/{dept}.yaml').read_text(encoding='utf8'))
            self.assertEqual((cfg['school'], cfg['dept'], cfg['official_admission_code']), ('tju', dept, code))
            self.assertIsInstance(cfg['roster_pending'], str)
            self.assertIn('尚未采集', cfg['roster_pending'])
            self.assertNotIn('hook', cfg)
            self.assertTrue(cfg['list']['public_url'].startswith('https://'))

    def test_academic_programs_are_not_generic_professional_doctoral_rules(self):
        root = Path(__file__).resolve().parents[1]
        data = yaml.safe_load((root / 'data/admissions.yaml').read_text(encoding='utf8'))
        policies = {p['id']: p for p in data['policies']}
        for dept, code, name in [('cs', '081200', '计算机科学与技术'), ('software', '083500', '软件工程'),
                                 ('cyber', '083900', '网络空间安全'), ('ai', '140500', '智能科学与技术')]:
            p = policies[f'tju-{dept}-2027-phd-assessment-v18']
            self.assertEqual((p['level'], p['program_code'], p['program']), ('program', code, name))
        self.assertIn('学术', policies['tju-school-2027-phd-assessment-v18']['applies_if']['text'])

    def test_new_entry_scopes_do_not_infer_channels_from_general_navigation(self):
        root = Path(__file__).resolve().parents[1]
        entries = yaml.safe_load((root / 'data/admissions_entries.yaml').read_text(encoding='utf8'))['entries']
        sources = {e['source_id']: e for e in entries}
        for sid in ['tju_cs_home_v18', 'dlut_cs_announcements_v18', 'dlut_ss_notice_list_v18']:
            self.assertFalse({'year', 'degree', 'route'} & sources[sid].keys())
        for dept in ['software', 'cyber', 'ai']:
            entry = sources[f'tju_{dept}_phd_pdf_v18']
            self.assertEqual((entry['year'], entry['degree'], entry['route']), (2027, 'phd', 'assessment'))
        for sid in ['nwpu_2027_master_charter_v18', 'nwpu_2027_master_registration_v18']:
            self.assertEqual((sources[sid]['year'], sources[sid]['degree']), (2027, 'master'))
            self.assertNotIn('route', sources[sid])


if __name__ == '__main__':
    unittest.main()
