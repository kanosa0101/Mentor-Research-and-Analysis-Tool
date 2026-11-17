from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sites import cyber_expansion, hust_profile, related_v7
from sites.zju import zju_cs


INDEX = 'http://www.cs.zju.edu.cn/csen/27006/list.htm'
ARTICLE = 'http://www.cs.zju.edu.cn/csen/2021/0525/c27006a2377953/page.htm'
REPORT_PATH = '/_upload/article/files/d4/45/e46a2ca6469693738d84d1fffc3f/7e0b4187-7b2b-44da-951d-f9439b508c1e.pdf'
REPORT = 'http://www.cs.zju.edu.cn' + REPORT_PATH
NEXT_ARTICLE = 'http://www.cs.zju.edu.cn/csen/2027/0201/c27006a9999999/page.htm'
NEXT_PATH = REPORT_PATH.replace('7e0b4187', '8e0b4187')
NEXT_REPORT = 'http://www.cs.zju.edu.cn' + NEXT_PATH
PDF_COLUMNS = ['序号', '所室机构', '姓名', '职 称', '研究方向', '办公地点', '办公室电话', 'Email', '备注', '团队']


def _index_html(*notices):
    return ''.join(f'<a href="{url}">计算机学院导师与导师团队信息-{year}（持续更新中）</a>' for year, url in notices)


def _roster_pdf(period, entries, department='软件所'):
    title = [f'研究生导师信息库-{period}'] + [None] * 9
    rows = [[str(i), department, name, '副教授', 'shared@zju.edu.cn', None, None, email, '硕导', None]
            for i, (name, email) in enumerate(entries, 1)]
    return SimpleNamespace(pages=[SimpleNamespace(extract_tables=lambda: [[title, PDF_COLUMNS, *rows]])])


def test_zju_current_official_pdf_selects_only_unique_names_and_email_cells():
    fake_pdf = _roster_pdf('2026.09', [
        ('甲老师', 'a@cs.zju.\nedu.cn'), ('乙老师', 'b@zju.edu.cn'), ('乙老师（AI）', 'bb@zju.edu.cn'),
        ('丙老师', 'same@zju.edu.cn'), ('丁老师', 'same@zju.edu.cn'), ('戊老师', 'x@zju.edu.cn; y@zju.edu.cn'),
        ('己老师', ''), ('庚老师', 'office@zju.edu.cn'),
    ])
    html = (f'<a href="{REPORT_PATH}">2026全日制导师信息库-09.pdf</a>'
            f'<a href="https://another.edu.cn{REPORT_PATH}">2027全日制导师信息库-01.pdf</a>')
    reads = []

    def reader(url):
        reads.append(url)
        if url == INDEX:
            return b'official index', _index_html(('2026', ARTICLE))
        return (b'official article', html) if url == ARTICLE else (b'%PDF-test roster', '')

    cfg = {'profile_contact_roster_index': INDEX, '_read_source': reader}
    with patch('pdfplumber.open', return_value=nullcontext(fake_pdf)) as load:
        found = zju_cs.parse_contact(cfg, {'name': '甲老师'})
        for name in ('乙老师', '丙老师', '丁老师', '戊老师', '己老师', '庚老师', '同名未登记'):
            assert not zju_cs.parse_contact(cfg, {'name': name})
        assert load.call_count == 1
    assert found['email'] == 'a@cs.zju.edu.cn'
    assert found['_field_sources']['email'] == REPORT
    assert found['_contact_locator']['email'] == {'index_url': INDEX, 'article_url': ARTICLE, 'page': 1, 'table_row': 3}
    assert set(reads) == {INDEX, ARTICLE, REPORT}


def test_zju_index_rechecks_new_year_announcement_and_pdf_and_does_not_fall_back():
    pages = {
        INDEX: (b'index', _index_html(('2026', ARTICLE))),
        ARTICLE: (b'old article', f'<a href="{REPORT_PATH}">2026全日制导师信息库-09.pdf</a>'),
        REPORT: (b'%PDF-older synthetic case', ''),
        NEXT_ARTICLE: (b'new article', f'<a href="{NEXT_PATH}">2027全日制导师信息库-02.pdf</a>'),
        NEXT_REPORT: (b'%PDF-newer synthetic case', ''),
    }
    reads = []

    def reader(url):
        reads.append(url)
        if isinstance(pages[url], Exception):
            raise pages[url]
        return pages[url]

    cfg = {'profile_contact_roster_index': INDEX, '_read_source': reader}
    original = {'name': '甲老师'}
    old_pdf = _roster_pdf('2026.09', [('甲老师', 'a@zju.edu.cn')])
    new_pdf = _roster_pdf('2027.02', [('甲老师', 'changed@zju.edu.cn')])
    with patch('pdfplumber.open', side_effect=[nullcontext(old_pdf), nullcontext(new_pdf), nullcontext(old_pdf)]):
        assert zju_cs.parse_contact(cfg, original)['email'] == 'a@zju.edu.cn'
        pages[INDEX] = b'updated index', _index_html(('2026', ARTICLE), ('2027', NEXT_ARTICLE))
        recheck = dict(cfg, _previous_email='a@zju.edu.cn', _read_previous_email_evidence=lambda: pages[REPORT][0])
        changed = zju_cs.parse_contact(recheck, original)
    assert changed['email'] == 'changed@zju.edu.cn'
    assert changed['_field_sources']['email'] == NEXT_REPORT
    assert reads == [INDEX, ARTICLE, REPORT, INDEX, NEXT_ARTICLE, NEXT_REPORT]
    pages[NEXT_REPORT] = ValueError('HTTP 404')
    with pytest.raises(ValueError, match='HTTP 404'):
        zju_cs.parse_contact(cfg, original)
    assert reads[-3:] == [INDEX, NEXT_ARTICLE, NEXT_REPORT]
    pages[NEXT_REPORT] = b'%PDF-stale bytes', ''
    with patch('pdfplumber.open', return_value=nullcontext(old_pdf)):
        with pytest.raises(ValueError, match='表头变化'):
            zju_cs.parse_contact(cfg, original)
    assert 'email' not in original
    before = {'name': '甲老师', 'email': 'manual@zju.edu.cn',
              'provenance': {'email': {'origin': 'manual'}}}
    assert zju_cs.parse_contact(dict(cfg, _read_source=lambda url: pytest.fail(f'unexpected read {url}')), before) == {}


def test_zju_different_department_across_rosters_requires_identity_review():
    responses = {
        INDEX: (b'index', _index_html(('2027', NEXT_ARTICLE))),
        NEXT_ARTICLE: (b'article', f'<a href="{NEXT_PATH}">2027全日制导师信息库-02.pdf</a>'),
        NEXT_REPORT: (b'%PDF-same-name-different-department', ''),
    }
    current_pdf = _roster_pdf('2027.02', [('甲老师', 'new@zju.edu.cn')], department='网络研究所')
    old_pdf = _roster_pdf('2026.09', [('甲老师', 'old@zju.edu.cn')], department='软件所')
    cfg = {'profile_contact_roster_index': INDEX, '_read_source': responses.__getitem__,
           '_previous_email': 'old@zju.edu.cn', '_read_previous_email_evidence': lambda: b'%PDF-prior-department'}
    with patch('pdfplumber.open', side_effect=[nullcontext(current_pdf), nullcontext(old_pdf)]):
        with pytest.raises(ValueError, match='未通过姓名与独立身份特征匹配'):
            zju_cs.parse_contact(cfg, {'name': '甲老师'})
        with pytest.raises(ValueError, match='未通过姓名与独立身份特征匹配'):
            zju_cs.parse_contact(dict(cfg, _read_previous_email_evidence=lambda: None), {'name': '甲老师'})


def test_zju_rejects_two_latest_links_and_wrong_person():
    html = (f'<a href="{REPORT_PATH}">2026全日制导师信息库-09.pdf</a>'
            f'<a href="{REPORT_PATH.replace("7e0b4187", "8e0b4187")}">2026全日制导师信息库-09.pdf</a>')
    with pytest.raises(ValueError, match='唯一日期'):
        zju_cs._latest_roster_link(ARTICLE, html, zju_cs._ROSTER_LABEL, zju_cs._ROSTER_FILE, '唯一日期')
    url = 'https://person.zju.edu.cn/registered'
    page = ('<div class="personal_name">其他人</div><div class="personal_bottom">'
            '<li>邮箱：other@zju.edu.cn</li></div>')
    with pytest.raises(ValueError, match='姓名未与名册一致'):
        zju_cs.parse_detail({'_expected_name': '甲老师'}, page, url)


def test_zju_personal_homepage_is_in_named_profile_scope():
    page = ('<div class="personal_name">甲老师<span>副教授</span></div>'
            '<div class="personal_bottom"><li>个人主页：<a href="https://teacher.example.org">打开</a></li></div>'
            '<footer><li>邮箱：shared@zju.edu.cn</li><li>个人主页：https://fake.example.org</li></footer>')
    result = zju_cs.parse_detail({'_expected_name': '甲老师'}, page, 'https://person.zju.edu.cn/registered')
    assert result['homepage'] == 'https://teacher.example.org'
    assert 'email' not in result


def test_hust_scoped_biography_uses_same_person_and_visible_contacts_only():
    profile = 'http://faculty.hust.edu.cn/already-listed/zh_CN/index.htm'
    more = 'http://faculty.hust.edu.cn/already-listed/zh_CN/more/42/jsjjgd/index.htm'
    head = '<div class="js-top"><div class="info"><h2>甲老师</h2></div></div>'
    profile_html = (
        head + '<div class="Psl-info"><a href="/another-person/zh_CN/more/42/jsjjgd/index.htm">More+</a>'
        '<a href="/already-listed/zh_CN/more/42/jsjjgd/index.htm">More+</a></div>'
        '<div class="Ot-ctact"><div class="cont"><li>邮箱：<span _tsites_encrypt_field="1">'
        'must-not-appear@hust.edu.cn</span></li></div></div>'
        '<footer><li>邮箱：shared@hust.edu.cn</li></footer>'
    )
    full_html = (head + '<div class="zw-article"><div class="atccont"><p>本人邮箱：abc@mail.hust.edu.cn</p>'
                 '<p>个人主页：https://teacher.example.org/about</p><p>课题组个人主页：https://lab.example.org</p>'
                 '<p>学生邮箱：other@hust.edu.cn</p></div></div>')
    use = []

    def reader(url):
        use.append(url)
        raw = {profile: profile_html, more: full_html}[url]
        return raw.encode(), raw

    cfg = {'hust_contact_profile': True, '_read_source': reader}
    original = {'name': '甲老师', 'detail_url': profile}
    assert related_v7.parse_contact(cfg, original) == cyber_expansion.parse_contact(cfg, original)
    parsed = hust_profile.parse_contact(cfg, original)
    assert parsed['email'] == 'abc@mail.hust.edu.cn'
    assert parsed['homepage'] == 'https://teacher.example.org/about'
    assert parsed['_field_sources'] == {'email': more, 'homepage': more}
    assert use == [profile, more] * 3
    assert related_v7.parse_contact({'school': 'csu', '_read_source': reader}, original) == {}
    assert cyber_expansion.parse_contact({'school': 'whu', '_read_source': reader}, original) == {}
    with pytest.raises(ValueError, match='身份与名单不符'):
        hust_profile.parse_contact(cfg, dict(original, name='其他人'))


def test_hust_rechecks_same_teacher_through_current_biography_link():
    profile = 'http://faculty.hust.edu.cn/registered/zh_CN/index.htm'
    old = 'http://faculty.hust.edu.cn/registered/zh_CN/more/42/jsjjgd/index.htm'
    new = old.replace('/42/', '/84/')
    head = '<div class="js-top"><div class="info"><h2>甲老师</h2></div></div>'

    def root(bio):
        return (head + f'<div class="Psl-info"><a href="{bio}">More+</a></div>'
                '<div class="dft-midcont"><div class="Psl-info"><div class="cont">'
                '<p>个人主页：https://alternate.example.edu/about</p></div></div></div>')

    def details(body):
        return head + '<div class="zw-article"><div class="atccont">' + body + '</div></div>'

    responses = {profile: root(old), old: details('<p>本人邮箱：old@hust.edu.cn</p>'),
                 new: details('<p>本人邮箱：new@hust.edu.cn</p>')}
    reads = []

    def reader(url):
        reads.append(url)
        if isinstance(responses[url], Exception):
            raise responses[url]
        html = responses[url]
        return html.encode(), html

    cfg = {'hust_contact_profile': True, '_read_source': reader}
    original = {'name': '甲老师', 'detail_url': profile}
    assert hust_profile.parse_contact(cfg, original)['_field_sources']['email'] == old
    responses[profile] = root(new)
    renewed = hust_profile.parse_contact(cfg, original)
    assert renewed['email'] == 'new@hust.edu.cn'
    assert renewed['_field_sources']['email'] == new
    for no_personal_email in ('', '<p>课题组邮箱：shared@hust.edu.cn</p>', '<p>邮箱：office@hust.edu.cn</p>',
                              '<p>邮箱：first@hust.edu.cn</p><p>邮箱：second@hust.edu.cn</p>'):
        responses[new] = details(no_personal_email)
        assert 'email' not in hust_profile.parse_contact(cfg, original)
    responses[new] = OSError('HTTP 403')
    with pytest.raises(OSError, match='HTTP 403'):
        hust_profile.parse_contact(cfg, original)
    assert reads[0:4] == [profile, old, profile, new]
    assert reads.count(old) == 1
