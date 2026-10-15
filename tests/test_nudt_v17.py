import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]

def hook():
    spec = importlib.util.spec_from_file_location('nudt_roster', ROOT / 'sites/nudt/roster.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_complete_official_pages(monkeypatch):
    m = hook()
    cfg = {'dept_name': '计算机学院', 'list': {'url': 'https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/teacherlist.view'}}
    rows = [{'keyId': i + 1, 'unit': '计算机学院', 'tchNo': '教师' + str(i), 'title': '博导', 'headship': '研究方向为计算机。' + ('chuzy@nudt.edu.cn' if i == 0 else f'teacher{i}@nudt.edu.cn')} for i in range(51)]
    pages = [{'pager.totalRows': 51, 'rows': rows[:50]}, {'pager.totalRows': 51, 'rows': rows[50:]}]
    def fake(method, url, data):
        assert method == 'POST' and data['unit'] == cfg['dept_name']
        return json.dumps(pages[data['pager.pageNo'] - 1]), {'fetched_at': '2026-10-15'}, True
    monkeypatch.setattr(m.fetch, 'fetch_text', fake)
    rows, meta = m.iter_roster(cfg)
    assert len(rows) == meta['roster_total'] == 51
    assert len({r['url'] for r in rows}) == 51
    assert rows[0]['supervisor'] == '博导'
    assert rows[0]['email'] == 'chuzy@nudt.edu.cn'
    assert all(r['roster_fetched_at'] == '2026-10-15' for r in rows)
    bad = copy.deepcopy(pages)
    bad[1]['rows'] = [bad[0]['rows'][0]]
    pages[:] = bad
    with pytest.raises(ValueError, match='重复'):
        m.iter_roster(cfg)

def test_mismatched_unit_rejected():
    m = hook()
    row = {'keyId': 1, 'unit': '气象海洋学院', 'tchNo': '测试', 'title': '硕导'}
    with pytest.raises(ValueError, match='归属'):
        m.record(row, '计算机学院', '2026-10-15')

def test_cross_unit_membership_is_explicit():
    m = hook()
    row = {'keyId': 1, 'unit': '理学院、智能科学学院', 'tchNo': '测试', 'title': '博导', 'headship': '研究方向为机器学习。a@nudt.edu.cn'}
    r = m.record(row, '智能科学学院', '2026-10-15')
    assert r['institutes'] == ['官方导师登记归属：理学院、智能科学学院']
    assert r['research_direction_raw'] == '研究方向为机器学习。'

@pytest.mark.parametrize('payload', [
    {'pager.totalRows': 51, 'rows': [{'keyId': 1, 'unit': '计算机学院', 'tchNo': '测试'}]},
    {'pager.totalRows': 0, 'rows': []},
])
def test_incomplete_or_empty_roster_stops(monkeypatch, payload):
    m = hook()
    monkeypatch.setattr(m.fetch, 'fetch_text', lambda *args: (json.dumps(payload), {'fetched_at': '2026-10-15'}, False))
    with pytest.raises(ValueError, match='数量异常'):
        m.iter_roster({'dept_name': '计算机学院'})


def test_committed_records_validate_and_do_not_infer_titles():
    import yaml
    from crawler.model import Professor
    for path in (ROOT / 'data/professors/nudt').rglob('*.yaml'):
        person = Professor.model_validate(yaml.safe_load(path.read_text(encoding='utf-8')))
        assert person.title is None
        assert person.supervisor in ('博导', '硕导')
        assert person.detail_url.startswith('https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/getView.view?keyId=')
        assert person.provenance['name'].fetched_at

@pytest.mark.parametrize('existing_bio,manual', [(None, False), ('保留的非空简介', False), ('人工简介', True), ('', True)])
def test_roster_bio_preserves_existing_and_provenance(monkeypatch, tmp_path, existing_bio, manual):
    from types import SimpleNamespace
    from crawler import store
    from crawler.model import Professor, Provenance
    from scripts import crawl
    monkeypatch.setattr(store, 'DATA', tmp_path)
    row = hook().record({'keyId': 1, 'unit': '计算机学院', 'tchNo': '测试', 'headship': '<p>本人原文简介</p><p>研究方向为机器人。</p>'}, '计算机学院', '2026-10-14')
    assert row['bio_raw'] == '本人原文简介 研究方向为机器人。'
    if existing_bio is not None:
        person = Professor(slug='ceshi', name='测试', school='nudt', dept='cs', detail_url=row['url'], bio_raw=existing_bio,
                           provenance={'bio_raw': Provenance(source='https://example.org/manual', fetched_at='2026-10-13', origin='manual' if manual else 'crawled')})
        store.save_professor(person)
    fake = SimpleNamespace(iter_roster=lambda cfg: ([row], {'fetched_at': '2026-10-14'}))
    crawl.phase_roster({'school':'nudt', 'dept':'cs', 'list':{'url':'https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/teacherlist.view'}}, fake, False)
    result = next(iter(store.load_all('nudt', 'cs').values()))
    assert result.bio_raw == (existing_bio if existing_bio is not None else row['bio_raw'])
    assert result.provenance['bio_raw'].fetched_at == ('2026-10-13' if existing_bio is not None else '2026-10-14')
    assert result.provenance['bio_raw'].source == ('https://example.org/manual' if existing_bio is not None else row['url'])


def test_shared_contact_different_names_is_not_individual_email(monkeypatch):
    m = hook()
    payload = {'pager.totalRows': 2, 'rows': [
        {'keyId': 1, 'unit': '计算机学院', 'tchNo': '甲老师', 'headship': '本人简介。shared@nudt.edu.cn'},
        {'keyId': 2, 'unit': '计算机学院', 'tchNo': '乙老师', 'headship': '本人简介。shared@nudt.edu.cn'},
    ]}
    monkeypatch.setattr(m.fetch, 'fetch_text', lambda *args: (json.dumps(payload), {'fetched_at': '2026-10-15'}, False))
    rows, _ = m.iter_roster({'dept_name': '计算机学院'})
    assert all(not row.get('email') for row in rows)
    assert all('shared@nudt.edu.cn' in row['bio_raw'] for row in rows)
