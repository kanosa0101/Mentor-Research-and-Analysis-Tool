import hashlib

import pytest

from crawler import mentor_fields as fields, mentor_quality as quality, mentor_recovery as recovery
from tests.test_mentor_contact_chain_v1119 import missing_contacts, person_file
from tests.test_mentor_quality_v1114 import NOW, body, put, root
from tests.test_mentor_recovery_v1115 import configure


SCOPE = 'https://ia.cas.cn'
HOME = 'https://people.ucas.ac.cn/~teacher'


def profile():
    return (body(email=None) + '<div class="gunius-info"><h3 class="name">张老师<span> / 博士</span></h3></div>'
            '<div class="gunius-list"><p>个人主页：<a href="' + HOME + '">访问主页</a></p></div>')


def hosted():
    return ('<title>张老师-中国科学院大学-UCAS</title><div class="b-pinfo"><div class="bp-enty">'
            '<p><strong>张老师，中国科学院自动化研究所，研究员</strong></p>'
            '<p>本人邮箱：hosted@ucas.ac.cn</p></div></div>')


def setup_profile(root):
    cfg = configure(root)
    cfg.update(base_url=SCOPE, profile_lookup_urls=[])
    put(root / 'sites/test/cs.yaml', cfg)
    person = missing_contacts(root)
    person['detail_url'] = SCOPE + '/teacher'
    put(person_file(root), person)


def test_official_link_requires_both_page_identities_and_preserves_mail_scope(root):
    setup_profile(root)
    # The real IA adapter supplies the parsed homepage only after verifying its named section.
    script = root / 'sites/test/demo.py'
    script.write_text(script.read_text(encoding='utf-8').replace(
        "return json.loads(", "result = json.loads(") +
        "\n    result['homepage'] = '" + HOME + "'\n    return result\n", encoding='utf-8')
    requests = []

    def fetch(source):
        requests.append(source)
        return hosted() if source['url'] == HOME else profile()

    report = fields.run(root, limit=1, request_budget=2, fetcher=fetch, now=NOW)
    person = quality.load_yaml(person_file(root))
    assert person['homepage'] == HOME and not person.get('email')
    evidence = report['results'][0]['field_evidence']['homepage']
    assert evidence['sha256'] == hashlib.sha256(profile().encode()).hexdigest()
    assert evidence['target_evidence']['sha256'] == hashlib.sha256(hosted().encode()).hexdigest()
    assert requests[-1]['official_scope'] == 'https://people.ucas.ac.cn'
    assert not recovery.contact_allowed(HOME, SCOPE, {})
    before = person_file(root).read_bytes()
    fields.run(root, limit=1, request_budget=2, fetcher=lambda _: pytest.fail('same-clock refetch'), now=NOW)
    assert person_file(root).read_bytes() == before


@pytest.mark.parametrize('url,scope', [
    (HOME, 'https://other.edu.cn'),
    (HOME.replace('https:', 'http:'), SCOPE), (HOME + '?next=/another', SCOPE),
    ('https://people.ucas.ac.cn.evil.example/~teacher', SCOPE),
    ('https://someone@people.ucas.ac.cn/~teacher', SCOPE),
    ('https://people.ucas.ac.cn:8443/~teacher', SCOPE),
    ('https://people.ucas.ac.cn/news/teacher', SCOPE),
])
def test_hosted_exception_does_not_expand_other_source_boundaries(url, scope):
    assert recovery.homepage_scope(url, scope) is None


@pytest.mark.parametrize('page', [
    hosted().replace('张老师-中国科学院', '李老师-中国科学院'),
    hosted().replace('自动化研究所', '计算技术研究所'),
    hosted().replace('<p><strong>张老师', '<p><strong>李老师'),
    '<h1>张老师</h1><p>中国科学院自动化研究所</p>',
    hosted().replace('b-pinfo', 'footer'),
])
def test_hosted_identity_requires_own_title_and_affiliation(page):
    assert not recovery.linked_homepage_identity(page, '张老师', url=HOME, scope=SCOPE)


@pytest.mark.parametrize('page', [
    profile().replace('gunius-list', 'footer'),
    profile().replace('个人主页', '论文链接'),
    profile().replace('个人主页', '学生个人主页'),
    profile().replace('个人主页', '合作导师个人主页'),
    profile().replace('个人主页', '课题组主页'),
    profile().replace('<h3 class="name">张老师', '<h3 class="name">李老师'),
    profile().replace(HOME, HOME + '2'),
])
def test_hosted_link_requires_named_own_section_and_explicit_link(page):
    assert not recovery.hosted_homepage_link(page, '张老师', HOME, SCOPE)


def ict_profile():
    return ('<title>张老师--中国科学院计算技术研究所</title><div class="main"><div class="swwls_ryxl">'
            '<dd class="swwls_imgtextlist_dd"><h5>张老师 教授</h5><p class="p-people-content">'
            '<b id="grwy">个人网页：</b><span><a href="' + HOME + '">个人网页</a></span></p></dd></div></div>')


def test_ict_hosted_identity_requires_corresponding_institute_and_named_personal_cell():
    scope = 'https://www.ict.ac.cn'
    target = hosted().replace('张老师，中国科学院自动化研究所，研究员', '张老师 女 博导 中国科学院计算技术研究所')
    assert recovery.homepage_scope(HOME, scope) == 'https://people.ucas.ac.cn'
    assert recovery.hosted_homepage_link(ict_profile(), '张老师', HOME, scope)
    assert recovery.linked_homepage_identity(target, '张老师', url=HOME, scope=scope)
    assert not recovery.linked_homepage_identity(target, '张老师', url=HOME, scope=SCOPE)
    assert not recovery.contact_allowed(HOME, scope, {})
    for primary in (ict_profile().replace('张老师 教授', '李老师 教授'),
                    ict_profile().replace('个人网页：', '学生网页：'),
                    ict_profile().replace('grwy', 'other'),
                    ict_profile().replace(HOME, HOME + '2')):
        assert not recovery.hosted_homepage_link(primary, '张老师', HOME, scope)
