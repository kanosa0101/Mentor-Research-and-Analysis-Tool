from pathlib import Path
from hashlib import sha256

import pytest
import yaml

from crawler.legacy_refresh import load_hook, run
from crawler import mentor_fields
from crawler.model import Professor
from scripts import crawl


ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ('https://jsj.nwpu.edu.cn/snew/szdwlist.jsp?'
             'a238672t=5&a238672p=3&a238672c=10&urltype=tree.TreeTempUrl&wbtreeid=1523')
DEPARTMENT_HOME = 'https://jsj.nwpu.edu.cn/snew/szdwlist.jsp?urltype=tree.TreeTempUrl&wbtreeid=1523'
NEW_PAGE = ('https://jsj.nwpu.edu.cn/snew/szdwlist.jsp?'
            'a238672t=2&a238672p=2&a238672c=10&urltype=tree.TreeTempUrl&wbtreeid=1523')
PERSON = 'https://teacher.nwpu.edu.cn/2017123456.html'
PEER = 'https://teacher.nwpu.edu.cn/2017654321.html'


def page(*cards, heading='计算机信息工程系-计算机学院'):
    return f'<title>{heading}</title><main>{"".join(cards)}</main>'


def card(label, href, body):
    return f'''<div class="leader-box"><div class="leader-content">
      <p class="name">{label}</p>{body}<p><a class="more" href="{href}">个人简介&gt;&gt;</a></p>
    </div></div>'''


@pytest.fixture
def context():
    cfg = yaml.safe_load((ROOT / 'sites/nwpu/cs.yaml').read_text(encoding='utf-8'))
    professor = dict(slug='chenjia', school='nwpu', dept='cs', name='陈甲',
                     detail_url=DIRECTORY, profile_url=PERSON)
    cfg.update(_expected_name=professor['name'], _original_profile=professor)
    return cfg, load_hook(ROOT, cfg), professor


def test_faculty_card_uses_both_name_and_matching_teacher_id(context):
    cfg, hook, _ = context
    html = page(card('陈乙（教授）', PEER, '研究方向：<br>他人方向'),
                card('陈甲（副教授）', 'http://teacher.nwpu.edu.cn/2017123456',
                     '研究方向：<br>图像处理。<p>学院邮箱：office@nwpu.edu.cn</p>'))
    assert hook.parse_detail(cfg, html, DIRECTORY) == {
        'name': '陈甲', '_verified_roster_name': '陈甲', 'title': '副教授',
        'research_direction_raw': '图像处理', 'research_directions': ['图像处理'],
    }


@pytest.mark.parametrize('cards', [
    (card('陈乙（教授）', PERSON, '研究方向：<br>他人方向'),),
    (card('陈甲（教授）', PEER, '研究方向：<br>同名者方向'),),
    (card('陈甲（教授）', PERSON, '研究方向：<br>图像处理'),
     card('陈甲（副教授）', PEER, '研究方向：<br>同名者方向')),
    (card('陈甲（教授）', PERSON, '研究方向：<br>图像处理'),
     card('陈乙（副教授）', PERSON, '研究方向：<br>同标识')),
    (card('陈甲（教授）', 'https://notnwpu.edu.cn/2017123456.html', '研究方向：<br>站外ID'),),
])
def test_faculty_card_fails_closed_on_conflicting_or_unbound_identity(context, cards):
    cfg, hook, _ = context
    with pytest.raises(ValueError, match='身份'):
        hook.parse_detail(cfg, page(*cards), DIRECTORY)


def test_faculty_card_requires_configured_department_and_registered_context(context):
    cfg, hook, _ = context
    cards = card('陈甲（教授）', PERSON, '研究方向：<br>图像处理')
    with pytest.raises(ValueError, match='院系'):
        hook.parse_detail(cfg, page(cards, heading='智能计算系统系-计算机学院'), DIRECTORY)
    with pytest.raises(ValueError, match='身份'):
        hook.parse_detail(dict(cfg, _expected_name=None), page(cards), DIRECTORY)


def test_faculty_card_preserves_nonempty_and_manual_fields(context):
    cfg, hook, prof = context
    prof['title'] = '教授（已退休）'
    prof['provenance'] = {'research_direction_raw': {'origin': 'manual'}}
    result = hook.parse_detail(cfg, page(card('陈甲（副教授）', PERSON, '研究方向：<br>图像处理')), DIRECTORY)
    assert result == {'name': '陈甲', '_verified_roster_name': '陈甲'}


def test_faculty_card_rechecks_prior_own_source_and_keeps_manual_direction(context):
    cfg, hook, prof = context
    prof.update(title='副教授', research_direction_raw='人工记录', supervisor='硕导')
    prof['provenance'] = {
        'title': {'origin': 'crawled', 'source': DIRECTORY},
        'research_direction_raw': {'origin': 'manual', 'source': DIRECTORY},
        'supervisor': {'origin': 'crawled', 'source': cfg['advisor_roster_url']},
    }
    advisor = f'''<title>导师风采-计算机学院</title><div id="vsb_content">
    <p>计算机学院博导硕导链接</p><p>博导：</p><table><tr><td>010计算机学院</td>
    <td><a href="{PERSON}">陈甲</a></td></tr></table></div>'''
    html = page(card('陈甲（教授）', PERSON, '研究方向：<br>官方方向'))
    result = hook.parse_detail(dict(cfg, _read_source=lambda url: (advisor.encode(), advisor)), html, DIRECTORY)
    assert result == {'name': '陈甲', '_verified_roster_name': '陈甲', 'title': '教授', 'supervisor': '博导',
                      '_field_sources': {'supervisor': cfg['advisor_roster_url']}}


def test_faculty_card_reads_plain_rank_and_leaves_missing_direction_empty(context):
    cfg, hook, _ = context
    result = hook.parse_detail(cfg, page(card('陈甲', PERSON, '副研究员')), DIRECTORY)
    assert result == {'name': '陈甲', '_verified_roster_name': '陈甲', 'title': '副研究员'}


@pytest.mark.parametrize(('target', 'expected'), [(PERSON, '硕导'), (PEER, None)])
def test_advisor_directory_requires_same_official_id_and_explicit_qualification(context, target, expected):
    cfg, hook, _ = context
    advisor_html = f'''<title>导师风采-计算机学院</title><div id="vsb_content">
    <p>计算机学院博导硕导链接</p><p>博导：</p><table><tr><td>010计算机学院</td>
    <td><a href="{PEER}">陈乙</a></td></tr></table>
    <p>硕 导：</p><table><tr><td>010计算机学院</td>
    <td><a href="{target}">陈甲</a></td></tr></table></div>'''
    reads = []

    def read_source(url):
        reads.append(url)
        return advisor_html.encode(), advisor_html

    result = hook.parse_detail(dict(cfg, _read_source=read_source),
                               page(card('陈甲', PERSON, '副研究员')), DIRECTORY)
    assert reads == ['https://jsj.nwpu.edu.cn/snew/jyjx/yjs/dsfc.htm']
    assert result.get('supervisor') == expected
    assert (result.get('_field_sources') or {}).get('supervisor') == (reads[0] if expected else None)


@pytest.mark.parametrize('outcome', ['moved', 'duplicate', 'wrong_id', 'unavailable'])
def test_legacy_maintenance_follows_current_department_pagination(context, tmp_path, outcome):
    cfg, _, original = context
    cfg = {key: value for key, value in cfg.items() if not key.startswith('_')}
    cfg.pop('advisor_roster_url')
    site = tmp_path / 'sites/nwpu'
    site.mkdir(parents=True)
    (site / 'cs.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    (site / 'nwpu_cs.py').write_bytes((ROOT / 'sites/nwpu/nwpu_cs.py').read_bytes())
    record = tmp_path / 'data/professors/nwpu/cs/chenjia.yaml'
    record.parent.mkdir(parents=True)
    record.write_text(yaml.safe_dump(original, allow_unicode=True), encoding='utf-8')
    before = record.read_bytes()
    mentor_fields.seed(tmp_path)
    old = page(card('陈乙（教授）', PEER, '研究方向：<br>他人方向'))
    home_card = card('陈甲', PEER, '') if outcome == 'duplicate' else card('陈乙', PEER, '')
    home = page(home_card, f'<div class="page-yansoft"><a href="{NEW_PAGE}">2</a></div>')
    new = page(card('陈甲（副教授）', PEER if outcome == 'wrong_id' else PERSON, '研究方向：<br>图像处理'))
    fixtures = {DIRECTORY: old, DEPARTMENT_HOME: home, NEW_PAGE: new}
    fetched = []

    def read(source):
        url = source['url']
        fetched.append(url)
        if url == NEW_PAGE and outcome == 'unavailable':
            raise OSError('保留先前档案')
        return fixtures[url].encode()

    report = run(tmp_path, kind='professors', units=('nwpu/cs',), fetcher=read)
    assert fetched[:2] == [DIRECTORY, DEPARTMENT_HOME]
    if outcome == 'moved':
        assert fetched == [DIRECTORY, DEPARTMENT_HOME, NEW_PAGE] and report['ok'] == 1
        after = yaml.safe_load(record.read_bytes())
        assert (after['detail_url'], after['profile_url']) == (DIRECTORY, PERSON)
        assert after['title'] == '副教授' and after['research_direction_raw'] == '图像处理'
        assert after['provenance']['title']['source'] == NEW_PAGE
        assert after['provenance']['research_direction_raw']['source'] == NEW_PAGE
        observations = mentor_fields.read(tmp_path)['records']['nwpu/cs/chenjia']['fields']
        for field in ('title', 'research_direction_raw'):
            assert observations[field]['source_url'] == NEW_PAGE
            assert observations[field]['source_sha256'] == sha256(new.encode()).hexdigest()

        after['research_direction_raw'] = '已人工复核'
        after['provenance']['research_direction_raw']['origin'] = 'manual'
        record.write_text(yaml.safe_dump(after, allow_unicode=True), encoding='utf-8')
        fixtures[NEW_PAGE] = page(card('陈甲（教授）', PERSON, '研究方向：<br>另一官方方向'))
        recheck = run(tmp_path, kind='professors', units=('nwpu/cs',), fetcher=read, retry=True)
        assert recheck['results'][0]['changed_fields'] == ['title']
        current = yaml.safe_load(record.read_bytes())
        assert current['title'] == '教授' and current['research_direction_raw'] == '已人工复核'
        assert current['provenance']['research_direction_raw'] == after['provenance']['research_direction_raw']
    else:
        assert report['error'] == 1 and record.read_bytes() == before


def test_regular_crawl_enrich_uses_registered_identity_for_a_directory_page(context, monkeypatch):
    cfg, hook, original = context
    cfg = {key: value for key, value in cfg.items() if not key.startswith('_')}
    professor = Professor.model_validate(original)
    html = page(card('陈甲（副教授）', PERSON, '研究方向：<br>图像处理'),
                card('陈乙（教授）', PEER, '研究方向：<br>他人方向'))
    monkeypatch.setattr(crawl.fetch, 'fetch_text', lambda *args, **kwargs: (html, {'fetched_at': '2026-11-23'}, True))
    monkeypatch.setattr(crawl.store, 'load_all', lambda *args: {professor.slug: professor})
    monkeypatch.setattr(crawl.store, 'load_issues', lambda *args: [])
    monkeypatch.setattr(crawl.store, 'save_issues', lambda *args: None)
    monkeypatch.setattr(crawl.store, 'append_changes', lambda *args: None)
    saved = []
    monkeypatch.setattr(crawl.store, 'save_professor', saved.append)

    assert crawl.phase_enrich(cfg, hook, False)['enriched'] == 1
    assert len(saved) == 1
    assert saved[0].title == '副教授'
    assert saved[0].research_direction_raw == '图像处理'
    assert saved[0].provenance['research_direction_raw'].source == DIRECTORY
    assert saved[0].profile_url == PERSON
