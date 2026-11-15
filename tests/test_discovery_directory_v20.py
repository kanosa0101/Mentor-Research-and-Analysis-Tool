"""The public and fallback mentor directories implement the same user filters."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from crawler.public_discovery import candidates, contactable, directory_match, title_group


ROOT = Path(__file__).resolve().parents[1]


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'site').mkdir()
        base = dict(name='导师', school='demo', dept='cs', email='a@demo.edu.cn',
                    email_source='https://demo.edu.cn/faculty', research_direction_raw='AI',
                    bio_excerpt='简介', detail_url='https://demo.edu.cn/faculty')
        self.rows = [dict(base, page=str(i), supervisor=qualification, title=title) for i, (qualification, title) in enumerate([
            ('博导', '教授'), ('硕导', '副教授'), ('博导、硕导', '助理教授'),
            ('', '教授级高级工程师'), ('硕导、博导', '特聘副研究员'), ('', '院士'),
        ])]
        self.rows += [dict(base, page='missing', email=''), dict(base, page='bad', email='a@demo.edu.cn123'),
                      dict(base, page='no-source', email_source=''), dict(base, page='unsafe-source', email_source='javascript:alert(1)')]
        self.write()

    def write(self):
        for file, value in [('discovery-data.js', self.rows), ('search.js', {})]:
            (self.root / 'site' / file).write_text('window.DATA=' + json.dumps(value) + ';', encoding='utf8')

    def test_contact_sources_not_just_nonempty_email(self):
        self.assertEqual(candidates(self.root, {})['total'], 6)
        self.assertEqual(candidates(self.root, {})['missing_email'], 4)
        self.assertEqual(candidates(self.root, {'include_missing_email': ['1']})['total'], 10)
        self.assertFalse(contactable(self.rows[-1]))

    def test_selected_qualifications_are_strict_union_without_degree_inference(self):
        for values, expected in [(['phd'], 3), (['master'], 3), (['phd', 'master'], 4)]:
            self.assertEqual(candidates(self.root, {'qualifications': values})['total'], expected)
        self.assertEqual(candidates(self.root, {'qualifications': ['master'], 'titles': ['professor']})['total'], 0)

    def test_title_map_keeps_associate_assistant_engineering_and_honors_distinct(self):
        expected = {'教授': 'professor', '副教授': 'associate_professor', '助理教授': 'assistant_professor',
                    '教授级高级工程师': 'other', '特聘副研究员': 'associate_researcher', '院士': 'unknown',
                    '博士后学历学位：博士': 'unknown', '实验室主任': 'unknown'}
        for value, category in expected.items():
            self.assertEqual(title_group(value), category)

    def test_legacy_preferences_do_not_affect_new_directory(self):
        old = {'degree': ['phd'], 'year': ['2030'], 'route': ['recommend'], 'keep_unknown': ['0'],
               'mode_qualification': ['hard'], 'mode_email': ['off'], 'mode_opportunity': ['hard']}
        self.assertEqual(candidates(self.root, old), candidates(self.root, {}))

    def test_javascript_fallback_and_python_filter_and_order_agree(self):
        cases = [{}, {'qualifications': ['phd']}, {'qualifications': ['master']},
                 {'qualifications': ['phd', 'master']}, {'titles': ['professor', 'other']},
                 {'titles': ['unknown'], 'include_missing_email': True}, {'topics': ['AI']}, {'topics': ['A']}]
        payload = {'rows': self.rows, 'cases': cases}
        script = "const fs=require('fs'),R=require('./site/discovery-core.js'),d=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(d.cases.map(c=>R.directoryRank(d.rows.filter(p=>R.directoryMatch(p,c)),'same').map(p=>p.page))));"
        actual = json.loads(subprocess.check_output(['node', '-e', script], input=json.dumps(payload).encode(), cwd=ROOT))
        for case, ids in zip(cases, actual):
            query = {'seed': ['same']}
            for key, value in case.items():
                query[key] = [json.dumps(value)] if key == 'topics' else [('1' if value else '0')] if key == 'include_missing_email' else value
            expected = [row['p']['page'] for row in candidates(self.root, query)['rows']]
            self.assertEqual(ids, expected, case)

    def test_email_filter_is_before_count_and_pagination(self):
        self.rows = [dict(self.rows[0], page=str(i), email='' if i % 2 else 'a@demo.edu.cn') for i in range(82)]
        self.write()
        first = candidates(self.root, {'seed': ['same']})
        second = candidates(self.root, {'seed': ['same'], 'offset': ['20']})
        self.assertEqual(first['total'], 41)
        self.assertEqual(len(first['rows']), 20)
        self.assertEqual(len(second['rows']), 20)
        self.assertFalse({r['p']['page'] for r in first['rows']} & {r['p']['page'] for r in second['rows']})


if __name__ == '__main__':
    unittest.main()
