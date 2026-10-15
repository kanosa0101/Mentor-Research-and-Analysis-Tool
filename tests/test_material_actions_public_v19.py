import copy
import unittest

from crawler import admissions_util
from test_admissions import fixture


class MaterialActionsPublicTests(unittest.TestCase):
    def data(self):
        data = fixture()
        data['policies'][0]['events'] = [{'label': '材料截止', 'kind': 'deadline', 'at': '2026-10-10', 'quote': '十日', 'locator': '第一条'}]
        data['policies'][0]['material_actions'] = [{
            'id': 'upload-application', 'label': '上传申请材料', 'stage': 'application',
            'instruction': {'text': '申请人向学院系统上传申请PDF', 'quote': '上传申请PDF', 'locator': '第二条'},
            'applies_if': {'text': '应届生', 'quote': '应届生', 'locator': '第二条', 'source_ids': ['s']},
            'event_indexes': [0]}]
        return data

    def test_optional_actions_and_all_stages(self):
        admissions_util.validate(fixture(), {'test': {'cs'}})
        for stage in ('application', 'screening', 'interview', 'admission', 'enrollment', 'other'):
            data = self.data()
            data['policies'][0]['material_actions'][0]['stage'] = stage
            admissions_util.validate(data, {'test': {'cs'}})
        data['policies'][0]['material_actions'] = []
        admissions_util.validate(data, {'test': {'cs'}})

    def test_action_structure_and_unique_stable_slug(self):
        invalid = [None, {}, 'x', [None], [{}]]
        for actions in invalid:
            data = self.data()
            data['policies'][0]['material_actions'] = actions
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})
        for key, value in [('id', ''), ('id', 'A B'), ('id', 1), ('label', ' '), ('label', None), ('stage', 'initial'), ('extra', 1)]:
            data = self.data()
            data['policies'][0]['material_actions'][0][key] = value
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})
        data = self.data()
        data['policies'][0]['material_actions'] *= 2
        with self.assertRaises(ValueError):
            admissions_util.validate(data, {'test': {'cs'}})

    def test_action_evidence_uses_existing_field_and_reviewed_source_rules(self):
        for part in ('instruction', 'applies_if'):
            for value in (None, {}, {'text': 'x', 'quote': 'q', 'locator': ''}, {'text': 'x', 'quote': 'q', 'locator': 'l', 'extra': 1}):
                data = self.data()
                data['policies'][0]['material_actions'][0][part] = value
                with self.assertRaises(ValueError):
                    admissions_util.validate(data, {'test': {'cs'}})
            for refs in ([], ['s', 's'], ['other'], 's', [True]):
                data = self.data()
                data['sources']['other'] = copy.deepcopy(data['sources']['s'])
                data['policies'][0]['material_actions'][0][part]['source_ids'] = refs
                with self.assertRaises(ValueError):
                    admissions_util.validate(data, {'test': {'cs'}})

    def test_event_indexes_are_optional_valid_unique_strict_integers(self):
        for indexes in (None, '', {}, [True], [False], [0.0], ['0'], [-1], [1], [0, 0]):
            data = self.data()
            data['policies'][0]['material_actions'][0]['event_indexes'] = indexes
            with self.assertRaises(ValueError):
                admissions_util.validate(data, {'test': {'cs'}})
        for indexes in ([], [0]):
            data = self.data()
            data['policies'][0]['material_actions'][0]['event_indexes'] = indexes
            admissions_util.validate(data, {'test': {'cs'}})
        del data['policies'][0]['material_actions'][0]['event_indexes']
        admissions_util.validate(data, {'test': {'cs'}})
