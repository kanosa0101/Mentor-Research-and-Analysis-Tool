"""Fast safe YAML storage preserves account records and rejects executable tags."""
from datetime import date
from unittest.mock import patch

import pytest
import yaml

from scripts import serve


def test_workflow_storage_round_trip_and_fallback(tmp_path):
    data = {'projects': {'id': {'name': '申请：计算机', 'notes': '第一行\n第二行',
                              'year': 2028, 'unknown': None, 'done': False}},
            'date': date(2026, 11, 16), 'materials': {}}
    path = tmp_path / 'workflow.yaml'
    serve.save_outreach(data, path)
    assert serve.load_outreach(path) == data
    assert yaml.safe_load(path.read_text(encoding='utf-8')) == data
    with patch.object(serve, 'WORKFLOW_YAML_LOADER', yaml.SafeLoader), patch.object(
            serve, 'WORKFLOW_YAML_DUMPER', yaml.SafeDumper):
        serve.save_outreach(data, path)
        assert serve.load_outreach(path) == data


def test_workflow_storage_rejects_python_tags(tmp_path):
    path, marker = tmp_path / 'workflow.yaml', tmp_path / 'must-not-exist'
    path.write_text('!!python/object/apply:builtins.open\n- ' + marker.as_posix() + '\n- w\n', encoding='utf-8')
    with pytest.raises(yaml.YAMLError):
        serve.load_outreach(path)
    assert not marker.exists()
