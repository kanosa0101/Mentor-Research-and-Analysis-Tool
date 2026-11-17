"""Real institutional notice proposal parsing; image/AI gates have separate tests."""
import copy
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler import automatic_review as automatic, opportunity_extract as extract, opportunity_attachments as attachments, opportunity_util as util

FIXTURES = Path(__file__).parent / 'fixtures/activity_intake'
URL = 'https://cibr.ac.cn/detail/cibrPersonneladmissions/4c3c22415af7498da6049027ccdd65cd'
LISTING = 'https://cibr.ac.cn/cibrPersonnel/admissions'
NOW = datetime(2026, 11, 17, 2, tzinfo=timezone.utc)
CONFIGS = [dict(url=LISTING, school='cibr', dept='', name='北京脑科学与类脑研究所')]


@pytest.fixture
def notice(tmp_path):
    raw = (FIXTURES/'cibr-winter-2027.html').read_bytes()
    doc = extract.document(raw, URL)
    doc['published_at'] = dict(value='2026-11-02', quote='2026-11-02')
    doc['documents'] = [dict(text=attachments.parse_docx((FIXTURES/name).read_bytes())['text'])
                        for name in ('cibr-application-2027.docx', 'cibr-personal-statement.docx')]
    doc['text'] = '\n'.join([doc['text'], *(d['text'] for d in doc['documents'])])
    item = {key:'' for key in util.TEXT}
    item.update({key:None for key in util.YEARS})
    item.update({key:[] for key in util.LISTS})
    item.update(id='activity-cibr', title='探知脑科学，积蓄脑动力—— 北京脑所2027年冬季培训班开始报名啦',
                source_url=URL, school_id='cibr', dept_id='', unit='北京脑所培训实习')
    draft = dict(item=item, source_url=URL, listing_url=LISTING,
                 fetch={'sha256':hashlib.sha256(raw).hexdigest()}, quotes=[], reviewed_fields={})
    return tmp_path, draft, doc


def test_actual_cibr_proposal_keeps_cohort_unknown_and_all_submission_conditions(notice):
    root, draft, doc = notice
    fields = automatic.prepare_new(root, draft, doc, NOW, CONFIGS)
    item = draft['item']
    assert item['kind'] == 'winter_camp' and item['camp_year'] == 2027
    assert item['graduation_year'] is None and item['admission_year'] is None
    assert item['unit'] == '北京脑科学与类脑研究所'
    assert item['registration_start'] == item['published_at'] == '2026-11-02'
    assert item['deadline'] == '2026-11-30T17:00:00+08:00'
    assert item['application_url'] == 'https://wj.qq.com/s2/28488862/va6k/'
    assert '缺少填报问卷或未提交电子材料均不得进入选拔环节' in item['application_method']
    assert '硕士研究生（二、三年级）' in item['eligibility'][0]
    assert any('2000字以内' in value and '他人或AI协助' in value for value in item['materials'])
    assert any('请使用电子签' in value for value in item['materials'])
    statement = next(value for value in item['materials'] if '2000字以内' in value)
    application = next(value for value in item['materials'] if '请使用电子签' in value)
    assert '个人陈述' in ''.join(statement.split()) and '申请人签名' in statement and '日期' in statement
    assert '2027年冬季培训班申请表' in application and '日期' in application
    assert fields['materials']['quote'] == doc['text']
    assert 'cibrstudent-apply@cibr.ac.cn' in item['contact']
    assert '精彩瞬间' not in item['contact']


@pytest.mark.parametrize('change', ['missing', 'different_value', 'different_quote'])
def test_immediate_window_needs_real_same_page_publication_date(notice, change):
    root, draft, doc = notice
    if change == 'missing':
        doc.pop('published_at')
    elif change == 'different_value':
        doc['published_at']['value'] = '2026-11-17'
    else:
        doc['published_at']['quote'] = '2026-11-17'
    with pytest.raises(automatic.NeedsHuman, match='发布日期'):
        automatic.prepare_new(root, draft, doc, NOW, CONFIGS)


@pytest.mark.parametrize('key,value', [('url','https://cibr.ac.cn/other'), ('school','another'),
    ('dept','another'), ('name','北京脑所培训实习'), ('enabled',False)])
def test_institute_registry_requires_exact_active_source_binding(notice, key, value):
    root, draft, doc = notice
    configs = copy.deepcopy(CONFIGS)
    configs[0][key] = value
    with pytest.raises(automatic.NeedsHuman, match='学校身份未登记'):
        automatic.prepare_new(root, draft, doc, NOW, configs)


def test_another_institute_name_cannot_be_inferred_from_same_domain(notice):
    root, draft, doc = notice
    configs = [dict(CONFIGS[0], name='另一家脑科学研究所')]
    with pytest.raises(automatic.NeedsHuman):
        automatic.prepare_new(root, draft, doc, NOW, configs)


def test_abbreviation_must_be_explicitly_introduced_by_official_name(notice):
    root, draft, doc = notice
    doc['text'] = doc['text'].replace('以下简称“北京脑所”', '以下简称“另一个简称”')
    doc['lines'] = [line.replace('以下简称“北京脑所”', '以下简称“另一个简称”') for line in doc['lines']]
    with pytest.raises(automatic.NeedsHuman, match='机构统一主办'):
        automatic.prepare_new(root, draft, doc, NOW, CONFIGS)


def test_nested_time_preserves_parent_application_steps_and_later_selection_rule(notice):
    _, _, doc = notice
    parts = automatic.sections(doc['lines'])
    assert parts['window'] == '即日起至2026年11月30日17：00。'
    assert '缺少填报问卷' in parts['application_method']
    assert '主要活动安排' not in parts['application_method']
    assert '加盖教务部门公章' in parts['materials']
    assert '报名时间' not in parts['materials']


def test_two_separate_eligibility_headings_still_require_scope_review():
    with pytest.raises(automatic.NeedsHuman, match='重复'):
        automatic.sections(['一、申请条件', '本科生。', '二、申请材料', '成绩单。', '三、报名条件', '硕士生。'])


def test_missing_material_list_does_not_treat_email_as_complete_materials(notice):
    root, draft, doc = notice
    doc['lines'] = [line for line in doc['lines'] if not line.startswith(('①','②','③','④','⑤','⑥','⑦'))]
    with pytest.raises(automatic.NeedsHuman, match='完整的申请对象'):
        automatic.prepare_new(root, draft, doc, NOW, CONFIGS)


def test_past_deadline_cannot_publish_a_still_online_notice(notice):
    root, draft, doc = notice
    with pytest.raises(automatic.NeedsHuman, match='结束|截止'):
        automatic.prepare_new(root, draft, doc, datetime(2026,12,1,tzinfo=timezone.utc), CONFIGS)
