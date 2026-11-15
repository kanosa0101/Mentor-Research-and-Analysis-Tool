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
        # v1.5 reviewed these exact documents; only their review dates changed.
        reviewed_v15 = {'hit_school_entry_v15b', 'uestc_cs_directory_v15b',
                        'hust_school_exam_page_v7', 'v14_units_csu_school',
                        'v14_units_seu_school', 'v14_units_seu_special',
                        'nudt_pdf_3_v15extra', 'nwpu_2027_master_charter_v18',
                        'nwpu_2027_master_registration_v18'}
        if entry['source_id'] in reviewed_v15:
            assert entry['reviewed_at'] == '2026-11-15'
            entry['reviewed_at'] = '2026-10-15'
        # v1.4 reviewed these ten official entry documents against fresh originals.
        # Normalize only their explicit date/note changes for the v17 scope snapshot.
        reviewed_v14 = {'sustech_api3579_v15c', 'school_page', 'exam_page',
                        'buaa_cyber_exam', 'ustc_2027_registration_v14',
                        'sjtu_2027_charter_v14', 'ucas_2027_charter_v14',
                        'v14_units_whu_school', 'v14_units_whu_cyber_quota',
                        'v14_units_whu_cyber_dir'}
        if entry['source_id'] in reviewed_v14:
            assert entry['reviewed_at'] == '2026-11-15'
            expected = '2026-11-15已回源复核对应2027硕士统考章程、目录或报名细则；报名期已过，现用于备考及资格材料核对，不代表2028推免政策或完整院系覆盖。'
            if entry['source_id'] == 'buaa_cyber_exam':
                expected = '2026-11-15核实官网迁移后的2027硕士408考试科目公告；仅确认考试科目，不是招生报名入口。'
            assert entry['note'] == expected
            entry['reviewed_at'] = '2026-10-14' if entry['source_id'] in {'school_page', 'exam_page', 'buaa_cyber_exam'} else '2026-10-15'
            entry['note'] = ('当前学校2027硕士招生章程；院系及专业要求仍需核对。' if entry['source_id'] == 'sustech_api3579_v15c'
                             else '2027入学年度master/exam章程或细则原文发布入口；沿用原政策核对日，不代表最新招生栏目或全部年度政策覆盖。')
        # v1.3 rechecked these two migrated official columns; preserve the old
        # scope-regression fingerprint for all other records.
        old_notes = {'buaa_cs_entry_v15a': '当前栏目含2027推免；统考附加科目及复试材料仍须2027目录/后续细则',
                     'buaa_cyber_entry_v15a': '当前学院招生栏目；2027第四单元408公告另已实时核对'}
        if entry['source_id'] in old_notes:
            assert entry['reviewed_at'] == '2026-11-15'
            assert entry['note'] == '官网栏目已迁移，本次已核对新入口；具体年度、资格、材料与日期以对应官方公告为准。'
            entry.update(reviewed_at='2026-10-15', note=old_notes[entry['source_id']])
        if entry['source_id'] == 'nankai_entry_v15extra' and entry.get('note') == '已核验学校硕士栏目；学校规则不能替代院系附加要求。':
            entry['note'] = '已核验学校硕士栏目；暂无接入院系师资，不虚构院系。'
    assert hashlib.sha256(json.dumps(baseline, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == '2fdd01c2af1b79b896d13d261ef2855ed00ad3fbd1e667c62fcca8b3fec55f10'


def test_added_unit_entry_scopes_and_unique_keys():
    root = Path(__file__).resolve().parents[1]
    entries = yaml.safe_load((root/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    keys = [(e['school'], e['dept'], e['source_id']) for e in entries]
    assert len(keys) == len(set(keys))
    # Scope assertions belong to the original v17 batch; later batches may append entries.
    additions = entries[76:85]
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


def test_v15_rechecked_material_deadlines_keep_identity_scope():
    root = Path(__file__).resolve().parents[1]
    policies = {p['id']: p for p in yaml.safe_load((root/'data/admissions.yaml').read_text(encoding='utf-8'))['policies']}
    neu = policies['neu-webreg-2027-exam-v15b']
    for action in neu['material_actions'][:3]:
        event = neu['events'][action['event_indexes'][0]]
        assert event['at'] == '2026-10-24'  # The platform notice gives no time of day.
        assert '10月16日更新' in event['quote']
        assert 'https://yjszs.neu.edu.cn/' in action['instruction']['text']
        assert action['applies_if']['text']
    dlut = policies['dlut-school-2027-exam-v15b']
    actions = {a['id']: a for a in dlut['material_actions']}
    indexes = []
    for key in ['current-student-status-report', 'postgraduate-consent-proof', 'parttime-employment-proof']:
        action = actions[key]
        index = action['event_indexes'][0]
        indexes.append(index)
        event = dlut['events'][index]
        assert event['at'] == '2026-12-18T17:00:00+08:00'
        assert event['quote'] == action['instruction']['quote']
        assert action['applies_if']['text']
    assert len(set(indexes)) == 3 and 0 not in indexes
    assert '045101' in actions['parttime-employment-proof']['applies_if']['text']


def test_v15_withdrawn_nankai_attachment_is_not_active_evidence():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root/'data/admissions.yaml').read_text(encoding='utf-8'))
    policy = next(p for p in data['policies'] if p['id'] == 'nankai-2027-master-exam-v15extra')
    assert 'nankai_pdf_1_v15extra' in policy['review_hashes']
    assert 'nankai_pdf_2_v15extra' not in policy['review_hashes']
    assert 'nankai_pdf_2_v15extra' not in policy['fields']['contact']['source_ids']
    assert 'nankai_pdf_2_v15extra' in data['sources']  # Preserve the historical source record.
