import hashlib
import json
from pathlib import Path
import pytest
import yaml
from crawler.admissions_entries import validate_entries

BASE = dict(school='s', dept='d', source_id='official', reviewed_at='2026-10-01')

def validate(entry):
    validate_entries({'version': 1, 'entries': [entry]}, {'s': {'d'}}, {'official': {}})

def test_optional_scope_and_legacy():
    validate(BASE)
    validate(dict(BASE, year=2027, degree='phd', route='assessment'))

@pytest.mark.parametrize('field,value', [('year', True), ('year', '2027'), ('year', 1999), ('year', 2101), ('degree', 'any'), ('degree', None), ('route', 'unknown'), ('route', [])])
def test_invalid_scope(field, value):
    with pytest.raises(ValueError):
        validate(dict(BASE, **{field: value}))

def test_scope_changes_preserve_existing_content():
    root = Path(__file__).resolve().parents[1]
    entries = yaml.safe_load((root/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    assert len(entries) >= 76
    baseline = [{k: v for k, v in e.items() if k not in {'year', 'degree', 'route'}} for e in entries[:76]]
    # Authorized v17 product correction changes only this obsolete integration-status note.
    for entry in baseline:
        if entry['source_id'] == 'nankai_entry_v15extra' and entry.get('note') == '已核验学校硕士栏目；学校规则不能替代院系附加要求。':
            entry['note'] = '已核验学校硕士栏目；暂无接入院系师资，不虚构院系。'
    assert hashlib.sha256(json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == '2fdd01c2af1b79b896d13d261ef2855ed00ad3fbd1e667c62fcca8b3fec55f10'


def test_added_unit_entry_scopes_and_unique_keys():
    root = Path(__file__).resolve().parents[1]
    entries = yaml.safe_load((root/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    keys = [(e['school'], e['dept'], e['source_id']) for e in entries]
    assert len(keys) == len(set(keys))
    additions = entries[76:]
    assert len(additions) == 9
    for entry in additions:
        if entry['school'] == 'nankai':
            assert not {'year', 'degree', 'route'} & entry.keys()
            continue
        assert entry['school'] == 'nudt' and entry['year'] == 2027
        if entry['source_id'] == 'nudt_pdf_3_v15extra':
            assert entry['degree'] == 'master' and 'route' not in entry
        elif entry['source_id'] == 'nudt_phd_2027_v17':
            assert entry['degree'] == 'phd' and 'route' not in entry
        else:
            assert entry['source_id'] == 'nudt_phd_syllabus_2027_v17'
            assert entry['degree'] == 'phd' and entry['route'] == 'assessment'

def test_document_scope_is_not_policy_clause_scope():
    root = Path(__file__).resolve().parents[1]
    entries = {e['source_id']: e for e in yaml.safe_load((root/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']}
    assert 'year' not in entries['hit_school_entry_v15b'] and 'route' not in entries['hit_school_entry_v15b']
    assert 'route' not in entries['uestc_cs_directory_v15b']
    assert 'degree' not in entries['seu_auto_recommend']
    assert 'degree' not in entries['v14_units_whu_cyber_quota']
    for key in ['school_page','hust_school_exam_page_v7','bit_2027_master_charter_v14','sjtu_2027_charter_v14','ucas_2027_charter_v14','v14_units_csu_school','v14_units_seu_school','v14_units_whu_school']:
        assert 'route' not in entries[key], key

def test_nankai_public_notes_follow_connected_units():
    root = Path(__file__).resolve().parents[1]
    entries = yaml.safe_load((root/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    entry = next(e for e in entries if e['source_id'] == 'nankai_entry_v15extra')
    assert entry['note'] == '已核验学校硕士栏目；学校规则不能替代院系附加要求。'
    policies = yaml.safe_load((root/'data/admissions.yaml').read_text(encoding='utf-8'))['policies']
    contact = next(p['fields']['contact'] for p in policies if p['school'] == 'nankai' and p['level'] == 'school' and p['degree'] == 'master' and p['route'] == 'exam')
    assert '尚未接入' not in contact['text']
    assert '学校政策不能当作院系条件已齐' in contact['text']
    assert '022-23505940' in contact['text'] and contact['quote'] == 'nkuyzb@163.com'
