import json
import tempfile
import unittest
from pathlib import Path

from crawler.public_discovery import candidates, random_key


class PublicDiscoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'site').mkdir()
        self.rows = [dict(page=f'demo-cs-{i}', name=f'导师{i}', school='demo', dept='cs',
                          school_name='示例大学', dept_name='计算机', unit_groups=['cs'],
                          detail_url='https://demo.edu.cn/' + str(i), bio_excerpt='研究简介',
                          email='mentor@demo.edu.cn', email_source='https://demo.edu.cn/profile', title='教授', supervisor='博导', research_direction_raw='计算机视觉')
                     for i in range(45)]
        self.rows.append(dict(page='other-ai-unknown', name='未知资料', school='other', dept='ai'))
        self.write('discovery-data.js', self.rows)
        self.write('search.js', {p['page']: 'chain theory and AI research' for p in self.rows[:-1]})

    def write(self, name, value):
        (self.root / 'site' / name).write_text('window.DATA=' + json.dumps(value) + ';', encoding='utf8')

    def test_pagination_is_stable_filtered_and_bounded(self):
        query = {'seed': ['same'], 'school': ['demo']}
        first = candidates(self.root, query)
        second = candidates(self.root, dict(query, offset=['20']))
        self.assertEqual(first['total'], 45)
        self.assertEqual(len(first['rows']), 20)
        first_ids = {r['p']['page'] for r in first['rows']}
        self.assertFalse(first_ids & {r['p']['page'] for r in second['rows']})
        self.assertEqual(candidates(self.root, query), first)
        self.assertEqual(candidates(self.root, dict(query, name=['导师44']))['total'], 1)

    def test_unknown_data_and_english_boundaries_keep_original_meaning(self):
        query = {'topics': ['["AI"]'], 'keep_unknown': ['0']}
        self.assertEqual(candidates(self.root, query)['total'], 45)
        self.assertEqual(candidates(self.root, dict(query, topics=['["ain"]']))['total'], 0)
        self.assertEqual(candidates(self.root, dict(query, topics=['["missing"]'], keep_unknown=['1']))['total'], 0)
        self.assertEqual(candidates(self.root, {'mode_opportunity': ['hard'], 'keep_unknown': ['0']})['total'], 45)

    def test_scope_and_complete_profiles_precede_unknowns(self):
        first = candidates(self.root, {'seed': ['one']})
        self.assertTrue(all(r['p']['school'] == 'demo' for r in first['rows']))
        self.assertEqual(candidates(self.root, {'context_school': ['demo'], 'dept': ['missing']})['total'], 0)
        self.assertEqual(candidates(self.root, {'group': ['missing']})['total'], 0)

    def test_private_parameters_and_unbounded_queries_rejected(self):
        for query in ({'reviews': ['{}']}, {'project': ['private']}, {'limit': ['999']},
                      {'offset': ['-1']}, {'topics': ['{}']}, {'seed': ['x' * 101]},
                      {'topics': [json.dumps(['x' + str(i) for i in range(21)])]},
                      {'school': ['missing']}, {'name': ['a', 'b']}, {'qualifications': ['unknown']}, {'titles': ['invalid']}, {'include_missing_email': ['2']}):
            with self.subTest(query=query), self.assertRaises((ValueError, TypeError)):
                candidates(self.root, query)

    def test_rebuild_changes_revision(self):
        first = candidates(self.root, {})
        self.rows.pop()
        self.write('discovery-data.js', self.rows)
        second = candidates(self.root, {})
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(second['total'], 45)

    def test_seed_mixing_has_unsigned_32bit_result(self):
        self.assertTrue(0 <= random_key('demo-cs-导师', 'seed😀') < 2 ** 32)
