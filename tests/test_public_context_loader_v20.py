"""Public configuration parsing stays safe, fresh and equivalent to the prior reader."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from crawler import project_util as projects

ROOT = Path(__file__).resolve().parents[1]


def legacy_context(root):
    """Independent copy of the pre-optimization SafeLoader-only behavior."""
    units = {}
    for filename in sorted((root / 'sites').glob('*/*.yaml')):
        value = yaml.safe_load(filename.read_text(encoding='utf-8'))
        if isinstance(value, dict) and value.get('school') and value.get('dept'):
            units.setdefault(value['school'], set()).add(value['dept'])
    for school in yaml.safe_load((root / 'data/schools.yaml').read_text(encoding='utf-8'))['schools']:
        units.setdefault(school['id'], set())
    admissions = yaml.safe_load((root / 'data/admissions.yaml').read_text(encoding='utf-8'))
    return {'units': units, 'sources': admissions['sources'], 'policies': admissions['policies']}


class PublicContextLoaderTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'sites/example').mkdir(parents=True)
        (root / 'data').mkdir()
        (root / 'sites/example/cs.yaml').write_text('school: example\ndept: cs\n', encoding='utf-8')
        (root / 'data/schools.yaml').write_text('schools:\n- id: example\n', encoding='utf-8')
        (root / 'data/admissions.yaml').write_text('sources: {}\npolicies: []\n', encoding='utf-8')

    @unittest.skipUnless(hasattr(yaml, 'CSafeLoader'), 'PyYAML C safe loader unavailable')
    def test_available_c_safe_loader_is_selected(self):
        self.assertIs(getattr(projects, 'PUBLIC_YAML_LOADER', yaml.SafeLoader), yaml.CSafeLoader)

    def test_real_public_context_matches_legacy_safe_reader(self):
        expected = legacy_context(ROOT)
        self.assertEqual(projects.load_context(ROOT), expected)
        with patch.object(projects, 'PUBLIC_YAML_LOADER', yaml.SafeLoader):
            self.assertEqual(projects.load_context(ROOT), expected)

    def test_next_read_reflects_all_three_public_file_types(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.assertEqual(projects.load_context(root), legacy_context(root))
            (root / 'sites/example/cs.yaml').write_text('school: example\ndept: software\n', encoding='utf-8')
            (root / 'data/schools.yaml').write_text('schools:\n- id: example\n- id: added\n', encoding='utf-8')
            (root / 'data/admissions.yaml').write_text('sources: {new: {url: "https://example.edu/p"}}\npolicies: [{id: latest}]\n', encoding='utf-8')
            current = projects.load_context(root)
            self.assertEqual(current, legacy_context(root))
            self.assertEqual(current['units'], {'example': {'software'}, 'added': set()})
            self.assertEqual(current['policies'], [{'id': 'latest'}])

    def test_cached_public_context_isolated_from_caller_and_unit_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            first = projects.load_context(root)
            first['units']['example'].add('private-mutation')
            first['policies'].append({'id': 'must-not-leak'})
            first['checks'] = {'private': True}
            self.assertEqual(projects.load_context(root), legacy_context(root))
            added = root / 'sites/example/ai.yaml'
            added.write_text('school: example\ndept: ai\n', encoding='utf-8')
            self.assertEqual(projects.load_context(root)['units']['example'], {'cs', 'ai'})
            added.unlink()
            self.assertEqual(projects.load_context(root)['units']['example'], {'cs'})

    def test_no_c_loader_falls_back_to_python_safe_loader(self):
        spec = importlib.util.spec_from_file_location('public_context_fallback_test', projects.__file__)
        fallback = importlib.util.module_from_spec(spec)
        with patch.dict(yaml.__dict__):
            yaml.__dict__.pop('CSafeLoader', None)
            spec.loader.exec_module(fallback)
        self.assertIs(fallback.PUBLIC_YAML_LOADER, yaml.SafeLoader)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.assertEqual(fallback.load_context(root), legacy_context(root))

    def test_python_object_tags_are_rejected_without_execution(self):
        loaders = [yaml.SafeLoader]
        if hasattr(yaml, 'CSafeLoader'):
            loaders.append(yaml.CSafeLoader)
        for loader in loaders:
            for relative in ('sites/example/cs.yaml', 'data/schools.yaml', 'data/admissions.yaml'):
                with self.subTest(loader=loader.__name__, file=relative), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    self.fixture(root)
                    marker = root / 'must-not-exist'
                    malicious = '!!python/object/apply:builtins.open\n- ' + str(marker).replace('\\', '/') + '\n- w\n'
                    (root / relative).write_text(malicious, encoding='utf-8')
                    with patch.object(projects, 'PUBLIC_YAML_LOADER', loader), self.assertRaises(yaml.YAMLError):
                        projects.load_context(root)
                    self.assertFalse(marker.exists())

    def test_malformed_public_yaml_still_raises(self):
        for loader in (yaml.SafeLoader, getattr(yaml, 'CSafeLoader', yaml.SafeLoader)):
            with self.subTest(loader=loader.__name__), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root)
                (root / 'data/admissions.yaml').write_text('policies: [unterminated\n', encoding='utf-8')
                with patch.object(projects, 'PUBLIC_YAML_LOADER', loader), self.assertRaises(yaml.YAMLError):
                    projects.load_context(root)


if __name__ == '__main__':
    unittest.main()
