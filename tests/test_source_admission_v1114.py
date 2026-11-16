import copy
from datetime import timedelta

import pytest
import yaml

from crawler import source_discovery as discovery
from crawler.opportunity_monitor import activity_title
from tests.test_source_discovery_v18 import NOW, PARENT, CHILD, RAW, COLUMN, fixture


def test_rule_admission_rechecks_parent_and_column_and_never_publishes(tmp_path):
    _, calls, fetch = fixture(tmp_path)
    result = discovery.run(tmp_path, fetcher=fetch, now=NOW, auto_admit=True)
    assert calls == [PARENT, CHILD, PARENT, CHILD]
    assert result['automatic_admission']['approved'] == 1
    candidate = result['candidates'][0]
    assert candidate['status'] == 'approved' and candidate['automatic_admission']['state'] == 'approved'
    configs = yaml.safe_load((tmp_path / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']
    assert len(configs) == 2 and configs[-1]['discovery_depth'] == 1
    assert configs[-1]['dept'] == ''
    assert not (tmp_path / 'data/opportunities.json').exists()
    discovery.admit_verified(tmp_path, fetcher=fetch, now=NOW + timedelta(hours=1))
    assert calls == [PARENT, CHILD, PARENT, CHILD]


def test_changed_column_retries_later_without_admitting_or_overwriting(tmp_path):
    _, calls, fetch = fixture(tmp_path)
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    config_path = tmp_path / 'sites/opportunities.yaml'; original = config_path.read_bytes()
    result = discovery.admit_verified(tmp_path, fetcher=lambda url, _: RAW if url == PARENT else COLUMN.replace(b'winter.html', b'changed.html'), now=NOW)
    assert result['approved'] == 0 and result['pending'] == 1
    assert config_path.read_bytes() == original
    current = discovery.read(tmp_path)['candidates'][0]
    assert current['source_sha256'] == candidate['source_sha256']
    assert current['automatic_admission']['state'] == 'retry_pending'
    result = discovery.admit_verified(tmp_path, fetcher=fetch, now=NOW + timedelta(hours=1))
    assert result['attempted'] == 0


@pytest.mark.parametrize('label,url', [
    ('2027年夏令营报名通知', 'https://grad.example.edu.cn/info/1010/1234.htm'),
    ('研究生招生', 'https://grad.example.edu.cn/2026/1116/c123a456/page.htm'),
    ('本科生招生', 'https://grad.example.edu.cn/bkszs.htm'),
    ('博士招生', 'https://grad.example.edu.cn/bsyjs.htm'),
])
def test_announcement_footer_and_wrong_scope_are_not_columns(label, url):
    assert not discovery.column_link(dict(title=label, url=url))


def test_article_page_with_camp_links_in_footer_fails_inspection():
    raw = b'<html><div class="TRS_Editor">Article body</div>' + COLUMN + b'</html>'
    with pytest.raises(ValueError, match='\u5355\u6761\u516c\u544a'):
        discovery.inspect(raw, CHILD)


def test_menu_links_alone_and_special_admission_directories_do_not_qualify(tmp_path):
    raw = '<html><meta charset="utf-8"><a href="/summer/">全国优秀大学生夏令营</a></html>'.encode()
    with pytest.raises(ValueError, match='活动公告'):
        discovery.inspect(raw, CHILD)
    configs, _, fetch = fixture(tmp_path)
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    assert discovery.automatic_reason(tmp_path, dict(candidate, label='港澳台硕士招生专业目录'), configs)


def test_innovation_course_navigation_does_not_make_an_alumni_column_an_activity_source():
    raw = '<html><meta charset="utf-8"><a href="/yy/kjcxsjkc.htm">科技创新实践课程</a><a href="/info/1001/1234.htm">校友羽毛球联赛报名</a></html>'.encode()
    with pytest.raises(ValueError, match='活动公告'):
        discovery.inspect(raw, 'https://cs.example.edu.cn/yy/tzgg.htm')


def test_untrusted_personal_http_and_deep_sources_remain_manual(tmp_path):
    configs, _, fetch = fixture(tmp_path)
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    cases = [
        (dict(candidate, url=CHILD.replace('https:', 'http:')), configs),
        (candidate, [dict(configs[0], mode='direct_page')]),
        (candidate, [dict(configs[0], discovery_depth=2)]),
        (candidate, []),
    ]
    for value, registry in cases:
        assert discovery.automatic_reason(tmp_path, value, registry)
    assert not discovery.automatic_reason(tmp_path, candidate, configs)


def test_explicit_rejection_is_never_overridden_by_automatic_admission(tmp_path):
    _, calls, fetch = fixture(tmp_path)
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    discovery.decide(tmp_path, candidate['id'], 'reject', now=NOW)
    result = discovery.admit_verified(tmp_path, fetcher=fetch, now=NOW)
    assert result['attempted'] == 0 and calls == [PARENT, CHILD]
    assert discovery.read(tmp_path)['candidates'][0]['status'] == 'rejected'


def test_candidate_admission_budget_leaves_remaining_candidates_for_next_run(tmp_path):
    _, _, fetch = fixture(tmp_path)
    discovery.run(tmp_path, fetcher=fetch, now=NOW)
    original = discovery.read(tmp_path)
    first = original['candidates'][0]
    second = copy.deepcopy(first); second.update(id='second', url='https://grad.example.edu.cn/more.html', label='夏令营')
    original['candidates'].append(second); discovery.atomic_json(tmp_path / 'cache/source-discovery.json', original)
    parent = RAW.replace(b'</html>', '<a href="https://grad.example.edu.cn/more.html">夏令营</a></html>'.encode())
    result = discovery.admit_verified(tmp_path, max_candidates=1, fetcher=lambda url, _: parent if url == PARENT else COLUMN, now=NOW)
    assert result['attempted'] == 1 and result['approved'] == 1
    assert sum(c['status'] == 'candidate' for c in discovery.read(tmp_path)['candidates']) == 1


def test_canonical_duplicate_parent_paths_are_normalized():
    assert discovery.canonical('https://cnic.cas.cn/../../yjsjy/') == 'https://cnic.cas.cn/yjsjy/'


def test_registered_department_without_policy_becomes_discovery_seed_only(tmp_path):
    configs, _, _ = fixture(tmp_path)
    unit = tmp_path / 'sites/example'; unit.mkdir()
    (unit / 'cyber.yaml').write_text(yaml.safe_dump(dict(school='example', dept='cyber',
        dept_name='网络空间安全学院', base_url='http://cyber.example.edu.cn')), encoding='utf-8')
    values = discovery.seeds(tmp_path, configs)
    new = next(row for row in values if row.get('seed_kind') == 'registered_department')
    assert new['url'] == 'https://cyber.example.edu.cn/'
    assert new['declared_url'] == 'http://cyber.example.edu.cn'
    assert new['dept'] == 'cyber' and new['school'] == 'example'
    assert len(yaml.safe_load((tmp_path / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']) == 1
    assert not (tmp_path / 'data/admissions.yaml').exists()


def test_general_department_notices_can_be_inspected_without_guessing_url_conventions():
    assert discovery.column_link(dict(title='学院公告', url='https://ai.example.edu.cn/xwgg/xygg/index.htm'))
    assert discovery.column_link(dict(title='通知公告', url='https://air.example.edu.cn/xxgg.htm'))
    raw = '<html><meta charset="utf-8"><a href="/xwdt.htm">新闻动态</a></html>'.encode()
    assert discovery.column_link(discovery.links(raw, PARENT)[0])
    with pytest.raises(ValueError, match='活动公告'):
        discovery.inspect('<html><meta charset="utf-8"><a href="/a">教工运动会通知</a></html>'.encode(), CHILD)


@pytest.mark.parametrize('title', ['2027年大学生暑期学校申请通知', '2027年优秀大学生冬季研修报名',
    '2027年计算机学院暑期研学营招募', '2027年自动化学院冬季训练营报名', '2027年科研训练营申请通知',
    '2027年智能研究院学术开放日报名'])
def test_research_camp_names_are_discovery_leads(title):
    assert activity_title(title)


@pytest.mark.parametrize('title', ['2027年中学生冬季研学营', '2027年科研训练营入选名单公示',
    '2027年海外暑期学校报名', '2027年暑期研学营考核结果', '关于公布2027年接收推荐免试研究生复试成绩...',
    '2027年优秀大学生夏令营入营通知', '我院成功举办2027年优秀大学生夏令营'])
def test_broader_keywords_do_not_remove_audience_and_result_exclusions(title):
    assert not activity_title(title)
