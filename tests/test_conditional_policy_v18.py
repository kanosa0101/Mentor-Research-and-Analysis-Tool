import copy
import unittest
from crawler import admissions_util
from test_admissions import fixture


class ConditionalPolicyTests(unittest.TestCase):
    def conditional(self):
        data = fixture()
        data['policies'][0]['applies_if'] = {'text': '仅适用于6112报考点考生', 'quote': '考点接收考生范围', 'locator': '二（二）', 'source_ids': ['s']}
        return data

    def test_optional_condition_accepts_evidence_and_legacy(self):
        admissions_util.validate(fixture(), {'test': {'cs'}})
        admissions_util.validate(self.conditional(), {'test': {'cs'}})
        data = self.conditional()
        del data['policies'][0]['applies_if']['source_ids']
        admissions_util.validate(data, {'test': {'cs'}})

    def test_condition_requires_nonempty_field_evidence(self):
        for value in (None, {}, '', {'text': 'x', 'quote': 'q'}, {'text': 'x', 'quote': 'q', 'locator': 'l', 'extra': 1}):
            data = self.conditional()
            data['policies'][0]['applies_if'] = value
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})
        for key in ('text', 'quote', 'locator'):
            data = self.conditional()
            data['policies'][0]['applies_if'][key] = ' '
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})

    def test_condition_references_must_be_reviewed(self):
        for refs in ([], ['missing'], ['s', 's'], 's'):
            data = self.conditional()
            data['policies'][0]['applies_if']['source_ids'] = refs
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})
        data = self.conditional()
        data['sources']['other'] = copy.deepcopy(data['sources']['s'])
        data['policies'][0]['applies_if']['source_ids'] = ['other']
        with self.assertRaises(ValueError):
            admissions_util.validate(data, {'test': {'cs'}})
