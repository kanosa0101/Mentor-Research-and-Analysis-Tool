import hashlib
from pathlib import Path

import pytest
import yaml

from crawler import automatic_evidence, policy_intake
from test_automatic_review_v18 import NOW, accepted, setup
from test_complete_evidence_v1116 import POLICY_HTML, policy_setup


def prepare(root):
    row = policy_intake.candidates(root)[0]
    doc = policy_intake.collect(POLICY_HTML, row, root/'cache', lambda *a: pytest.fail(), lambda *a: pytest.fail())
    return policy_intake.prepare(root, row, POLICY_HTML, doc, NOW)


def test_each_actual_display_value_is_an_explicit_review_claim(policy_setup):
    proposal = prepare(policy_setup)
    policy_intake.validate_display_checks(proposal)
    checks, policy = proposal['checks'], proposal['policy']
    for key, field in policy['fields'].items():
        assert checks[key] == {'value': field['text'], 'quote': field['quote']}
    assert 'application_procedure' not in checks
    assert checks['application_requirements']['value'] == policy['material_actions'][0]['instruction']['text']
    assert checks['deadline_0']['value']['at'] == policy['events'][0]['at']


@pytest.mark.parametrize('change', ['materials_value', 'missing_materials', 'deadline_value', 'actual_display', 'scope'])
def test_complete_quote_or_other_field_cannot_mask_changed_display_values(policy_setup, monkeypatch, change):
    original = policy_intake.prepare
    def mismatched(*args):
        result = original(*args)
        if change == 'materials_value':
            result['checks']['materials']['value'] = '只提交简历'
        elif change == 'missing_materials':
            del result['checks']['materials']
        elif change == 'deadline_value':
            result['checks']['deadline_0']['value']['at'] = '2027-12-31'
        elif change == 'actual_display':
            result['policy']['fields']['materials']['text'] = '只提交简历'
        else:
            result['checks']['scope']['value']['degree'] = 'master'
        return result
    monkeypatch.setattr(policy_intake, 'prepare', mismatched)
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML,
                              checker=lambda *a: pytest.fail('unbound actual values reached AI'))
    assert result['published'] == 0 and result['manual_required'] == 1
    assert '实际' in result['results'][0]['reason']


def test_binding_is_rechecked_after_the_ai_response(policy_setup, monkeypatch):
    prepared = prepare(policy_setup)
    monkeypatch.setattr(policy_intake, 'prepare', lambda *a: prepared)
    def altered(*args):
        result = accepted(*args)
        prepared['policy']['fields']['materials']['text'] = '遗漏原材料要求'
        return result
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=altered)
    assert result['published'] == 0 and result['manual_required'] == 1


def test_actual_pku_software_container_excludes_page_chrome_but_never_article_images():
    raw = (Path(__file__).parent/'fixtures/policy_intake/pku-software-2027.html').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '95388667f992b534e2f7dcf50665108c62af3c12d036abd61818213b6c39bb4f'
    url = 'https://ss.pku.edu.cn/zsxx/zsjz/6ef1d7aef13c41db93e9eb95fc411379.htm'
    doc, links = automatic_evidence.inspect_html(raw, url)
    assert not links and '快递使用EMS' in doc['text'] and '2026年12月28日12:00' in doc['text']
    assert '博士招生小组' in doc['text']
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, 'html.parser')
    image = soup.new_tag('img', src='/official-conditions.png')
    soup.select_one('#articleDiv.gpCmsArticle00').append(image)
    with pytest.raises(automatic_evidence.EvidenceError, match='正文图片'):
        automatic_evidence.inspect_html(str(soup).encode(), url)


def test_real_software_policy_keeps_program_plan_campus_and_each_delivery_deadline(tmp_path):
    raw = (Path(__file__).parent/'fixtures/policy_intake/pku-software-2027.html').read_bytes()
    (tmp_path/'data').mkdir();(tmp_path/'sites/pku').mkdir(parents=True)
    (tmp_path/'data/schools.yaml').write_text(yaml.safe_dump({'schools':[{'id':'pku','name':'北京大学'}]},allow_unicode=True),encoding='utf8')
    (tmp_path/'sites/pku/software.yaml').write_text(yaml.safe_dump({'school':'pku','dept':'software','dept_name':'软件与微电子学院'},allow_unicode=True),encoding='utf8')
    row=dict(url='https://ss.pku.edu.cn/zsxx/zsjz/6ef1d7aef13c41db93e9eb95fc411379.htm',school='pku',dept='software',
             title='北京大学软件与微电子学院2027年软件工程工学博士研究生“申请-考核制”招生说明',publication_date='2026-10-23')
    doc=automatic_evidence.collect(raw,row['url'],pdf_fetcher=lambda *a:pytest.fail(),docx_fetcher=lambda *a:pytest.fail())
    value=policy_intake.prepare(tmp_path,row,raw,doc,NOW)
    policy_intake.validate_display_checks(value)
    policy=value['policy']
    assert policy['level']=='program' and policy['program']=='软件工程'
    assert value['checks']['scope']['value']['program']=='软件工程'
    assert '住宿地点安排在大兴校区' in policy['fields']['tuition']['text']
    assert '6人' in policy['fields']['quota']['text'] and '09.领域智能软件' in policy['fields']['quota']['text']
    assert [(e['at'],e['label']) for e in policy['events']]==[
        ('2026-12-25T17:00:00+08:00','申请报名截止'),('2026-12-28T12:00:00+08:00','申请材料送达截止')]
    assert '体检' in policy['fields']['exams']['text'] and '违规处理' in policy['fields']['exams']['text']
    assert value['application_url']=='https://admission.pku.edu.cn/applications/'


def test_same_named_assessment_section_repeated_is_still_ambiguous():
    with pytest.raises(ValueError,match='重复'):
        policy_intake.sections(['一、录取','甲批规则','二、录取','乙批规则'])
