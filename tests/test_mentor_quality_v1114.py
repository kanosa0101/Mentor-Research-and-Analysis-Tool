import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from crawler import legacy_refresh, mentor_fields, mentor_quality as quality, quality_status
from crawler.model import Issue
from sites import cyber_expansion
from sites.hust_profile import identity_names
from bs4 import BeautifulSoup


NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding='utf-8')


@pytest.fixture
def root(tmp_path):
    put(tmp_path / 'sites/test/cs.yaml', dict(school='test', dept='cs', dept_name='计算机学院', hook='demo'))
    (tmp_path / 'sites/test/demo.py').write_text('''import json
from bs4 import BeautifulSoup
def parse_detail(cfg, html, url):
    return json.loads(BeautifulSoup(html, 'html.parser').select_one('script[type="application/json"]').string)
''', encoding='utf-8')
    person = dict(slug='teacher', name='张老师', school='test', dept='cs', status='roster',
                  detail_url='https://test.edu.cn/old', email='teacher@test.edu.cn',
                  last_verified='2026-10-01', provenance={})
    put(tmp_path / 'data/professors/test/cs/teacher.yaml', person)
    put(tmp_path / 'data/issues/test-cs.yaml', [dict(kind='fetch_or_parse_error', ref='teacher',
        message='Old HTTP failure', first_seen='2026-10-14', resolved=False, reviewed=None)])
    return tmp_path


def body(name='张老师', email='teacher@test.edu.cn'):
    data = dict(name=name, email=email, bio_raw=name+'研究机器学习', title='教授')
    return '<p>'+name+'</p><script type="application/json">'+json.dumps(data, ensure_ascii=False)+'</script>'


def test_success_is_evidenced_and_keeps_original_review_date(root):
    result = quality.run(root, fetcher=lambda _: body(), now=NOW)
    assert result['resolved'] == 1 and result['active'] == 0
    p = quality.load_yaml(root / 'data/professors/test/cs/teacher.yaml')
    assert p['last_verified'] == '2026-10-01' and p['last_fetched'] == '2026-11-16'
    issue = quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]
    assert issue['resolved'] and issue['reviewed'] is None
    assert issue['automatic_check']['evidence'][0]['sha256']
    assert list((root / 'cache/mentor_quality/evidence').glob('*.body'))
    assert Issue.model_validate(issue).model_dump()['automatic_check'] == issue['automatic_check']


def test_removed_profile_leaves_active_field_and_issue_queues_with_evidence_preserved(root):
    mentor_fields.seed(root, now=NOW)
    quality.run(root, fetcher=lambda _: body(), now=NOW)
    issue_path = root / 'data/issues/test-cs.yaml'
    before = quality.load_yaml(issue_path)[0]
    profile = root / 'data/professors/test/cs/teacher.yaml'
    profile.unlink()

    fields = mentor_fields.seed(root, now=NOW + timedelta(days=1))
    assert 'test/cs/teacher' not in fields['records'] and fields['summary']['fields'] == 0
    for days in (1, 30):
        result = quality.run(root, retry=True, fetcher=lambda _: pytest.fail('retired profile fetched'),
                             now=NOW + timedelta(days=days))
        assert result['attempted'] == result['active'] == 0
    issue = quality.load_yaml(issue_path)[0]
    assert issue['resolved'] and issue['reviewed'] is None
    assert issue['automatic_check']['evidence'] == before['automatic_check']['evidence']
    assert issue['review_history'][:-1] == before['review_history']
    assert issue['review_history'][-1]['state'] == 'retired'
    assert 'test/cs/fetch_or_parse_error/teacher' not in json.loads(
        (root / 'cache/mentor_quality/state.json').read_text(encoding='utf-8'))['records']


def test_unavailable_department_does_not_retire_existing_queue_records(root):
    mentor_fields.seed(root, now=NOW)
    folder = root / 'data/professors/test/cs'
    folder.rename(root / 'offline')

    assert 'test/cs/teacher' in mentor_fields.seed(root, now=NOW)['records']
    report = quality.run(root, limit=0, now=NOW)
    assert report['active'] == 1
    assert not quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]['resolved']


def test_profile_parse_error_does_not_retire_existing_queue_records(root):
    mentor_fields.seed(root, now=NOW)
    profile = root / 'data/professors/test/cs/teacher.yaml'
    profile.write_text('{', encoding='utf-8')
    ledger = root / mentor_fields.PATH
    before = ledger.read_bytes()

    with pytest.raises(yaml.YAMLError):
        mentor_fields.seed(root, now=NOW)
    assert ledger.read_bytes() == before
    with pytest.raises(yaml.YAMLError):
        quality.run(root, now=NOW)
    assert not quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]['resolved']


def test_recurring_check_reopens_failure_without_resetting_pending_since(root):
    quality.run(root, fetcher=lambda _: body(), now=NOW)
    assert quality.run(root, fetcher=lambda _: pytest.fail('not due'), now=NOW+timedelta(days=2))['attempted'] == 0
    failed = quality.run(root, fetcher=lambda _: body(name='其他教师'), now=NOW+timedelta(days=8))
    assert failed['error'] == failed['reopened'] == 1
    since = failed['results'][0]['pending_since']
    assert quality.run(root, fetcher=lambda _: pytest.fail('identity conflict cools down'), now=NOW+timedelta(days=9))['attempted'] == 0
    retry = quality.run(root, fetcher=lambda _: body(name='其他教师'), now=NOW+timedelta(days=15))
    assert retry['results'][0]['pending_since'] == since
    assert retry['results'][0]['last_success'] == NOW.isoformat(timespec='seconds')
    assert not quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]['resolved']


def test_manual_fields_are_not_replaced(root):
    path = root / 'data/professors/test/cs/teacher.yaml'
    p = quality.load_yaml(path)
    p['email'] = 'manual@test.edu.cn'
    p['provenance']['email'] = dict(origin='manual', source=p['detail_url'], fetched_at='2026-10-01')
    put(path, p)
    quality.run(root, fetcher=lambda _: body(), now=NOW)
    assert quality.load_yaml(path)['email'] == 'manual@test.edu.cn'


@pytest.mark.parametrize('candidate_email,expected', [('teacher@test.edu.cn', 'resolved'), ('other@test.edu.cn', 'error')])
def test_official_directory_fallback_requires_name_and_email(root, candidate_email, expected):
    cfg_path = root / 'sites/test/cs.yaml'
    cfg = quality.load_yaml(cfg_path)
    cfg['profile_lookup_urls'] = ['https://test.edu.cn/list1.htm']
    put(cfg_path, cfg)
    def fetch(source):
        if source['url'].endswith('/old'):
            raise ValueError('HTTP 403')
        if source['url'].endswith('list1.htm'):
            return '<a href="/profile/page.htm">张老师</a><a href="https://other.test/page.htm">张老师</a>'
        assert source['url'] == 'https://test.edu.cn/profile/page.htm'
        return body(email=candidate_email)
    result = quality.run(root, fetcher=fetch, now=NOW)
    assert result['results'][0]['status'] == expected
    p = quality.load_yaml(root / 'data/professors/test/cs/teacher.yaml')
    assert p['detail_url'].endswith('/profile/page.htm' if expected == 'resolved' else '/old')
    if expected == 'resolved':
        assert p['slug'] == 'teacher' and result['results'][0]['previous_source'].endswith('/old')


def test_refresh_error_creates_issue_even_without_deployed_ledger(root):
    (root / 'data/issues/test-cs.yaml').unlink()
    path = root / 'cache/legacy_refresh/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'records': {'professor/test/cs/teacher.yaml': {
        'status':'error','source_url':'https://test.edu.cn/old','error':'HTTP 403','last_attempt':NOW.isoformat()}}}), encoding='utf-8')
    result = quality.run(root, fetcher=lambda _: body(), now=NOW)
    assert result['created'] == result['resolved'] == 1


def test_stale_refresh_failure_does_not_create_issue_for_repaired_url(root):
    (root / 'data/issues/test-cs.yaml').unlink()
    path = root / 'cache/legacy_refresh/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'records': {'professor/test/cs/teacher.yaml': {
        'status':'error','source_url':'https://test.edu.cn/retired','error':'HTTP 403'}}}), encoding='utf-8')
    assert quality.run(root, fetcher=lambda _: pytest.fail('not applicable'), now=NOW)['created'] == 0


def test_successful_empty_run_initializes_state_without_fake_attempt(tmp_path):
    result = quality.run(tmp_path, fetcher=lambda _: pytest.fail('no work'), now=NOW)
    assert result['attempted'] == result['created'] == result['active'] == 0
    assert json.loads((tmp_path / 'cache/mentor_quality/state.json').read_text()) == {'version': 1, 'records': {}}


def test_budget_keeps_unattempted_queue_visible_and_preserves_waiting_clock(root):
    person = quality.load_yaml(root / 'data/professors/test/cs/teacher.yaml')
    person.update(slug='teacher2', detail_url='https://test.edu.cn/second')
    put(root / 'data/professors/test/cs/teacher2.yaml', person)
    path = root / 'data/issues/test-cs.yaml'
    issues = quality.load_yaml(path)
    issues.append(dict(issues[0], ref='teacher2'))
    put(path, issues)
    assert quality.run(root, limit=1, fetcher=lambda _: body(), now=NOW)['attempted'] == 1
    state_path = root / 'cache/mentor_quality/state.json'
    key = 'test/cs/fetch_or_parse_error/teacher2'
    queued = json.loads(state_path.read_text(encoding='utf-8'))['records'][key]
    assert queued['status'] == 'pending' and '等待首次复核' in queued['reason']
    assert queued['pending_since'] == NOW.isoformat(timespec='seconds')
    assert 'checked_at' not in queued and not queued.get('evidence')
    assert queued['source_urls'] == {'profile': 'https://test.edu.cn/second'}
    later = NOW + timedelta(hours=25)
    quality.run(root, limit=0, fetcher=lambda _: pytest.fail('budget exhausted'), now=later)
    waiting = quality_status.refresh(root, later)['active']
    assert len(waiting) == 1 and waiting[0]['overdue'] and waiting[0]['last_attempt_at'] is None
    assert waiting[0]['opened_at'] == queued['pending_since']
    assert waiting[0]['source_urls'] == ['https://test.edu.cn/second']
    attempted = quality.run(root, limit=1, fetcher=lambda _: body(name='其他教师'), now=later)['results'][0]
    assert attempted['pending_since'] == queued['pending_since']


@pytest.mark.parametrize('manual_field', ['reviewed', 'resolved'])
def test_manual_completion_removes_stale_automatic_alerts(root, manual_field):
    quality.run(root, fetcher=lambda _: body(name='其他教师'), now=NOW)
    path = root / 'data/issues/test-cs.yaml'
    issues = quality.load_yaml(path)
    issues[0][manual_field] = True
    put(path, issues)
    refresh_path = root / 'cache/legacy_refresh/state.json'
    refresh_path.parent.mkdir(parents=True)
    refresh_path.write_text(json.dumps({'records': {'professor/test/cs/teacher.yaml': {
        'status': 'error', 'source_url': 'https://test.edu.cn/old', 'error': 'known error before manual handling',
        'last_attempt': (NOW+timedelta(hours=1)).isoformat()}}}), encoding='utf-8')
    later = NOW + timedelta(days=10)
    result = quality.run(root, fetcher=lambda _: pytest.fail('manually handled'), now=later)
    assert result['attempted'] == 0
    assert json.loads((root / 'cache/mentor_quality/state.json').read_text())['records'] == {}
    assert quality_status.refresh(root, later)['active'] == []


def test_new_refresh_failure_rechecks_resolved_issue_before_weekly_due(root):
    quality.run(root, fetcher=lambda _: body(), now=NOW)
    later = NOW + timedelta(days=1)
    path = root / 'cache/legacy_refresh/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'records': {'professor/test/cs/teacher.yaml': {
        'status': 'error', 'source_url': 'https://test.edu.cn/old', 'error': 'new HTTP 403',
        'last_attempt': later.isoformat(timespec='seconds')}}}), encoding='utf-8')
    result = quality.run(root, fetcher=lambda _: body(name='其他教师'), now=later)
    assert result['attempted'] == result['error'] == 1 and result['created'] == 0
    assert result['results'][0]['pending_since'] == later.isoformat(timespec='seconds')
    assert result['results'][0]['last_success'] == NOW.isoformat(timespec='seconds')
    assert not quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]['resolved']


@pytest.mark.parametrize('attempt', ['2026-11-16T08:59:59+00:00', '2026-11-16T09:00:00+00:00', '2026-11-16T17:00:00+08:00'])
def test_old_or_same_instant_failure_does_not_reopen_resolved_issue(root, attempt):
    quality.run(root, fetcher=lambda _: body(), now=NOW)
    path = root / 'cache/legacy_refresh/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'records': {'professor/test/cs/teacher.yaml': {
        'status': 'error', 'source_url': 'https://test.edu.cn/old', 'error': 'old HTTP 403',
        'last_attempt': attempt}}}), encoding='utf-8')
    result = quality.run(root, fetcher=lambda _: pytest.fail('old failure'), now=NOW+timedelta(days=1))
    assert result['attempted'] == result['active'] == 0
    assert quality.load_yaml(root / 'data/issues/test-cs.yaml')[0]['resolved']


def test_concurrent_issue_edit_does_not_claim_success_or_weekly_delay(root):
    path = root / 'data/issues/test-cs.yaml'
    def fetch(_):
        issues = quality.load_yaml(path)
        issues[0]['message'] = 'new manual investigation'
        put(path, issues)
        return body()
    result = quality.run(root, fetcher=fetch, now=NOW)['results'][0]
    assert result['status'] == 'pending' and result['last_success'] is None
    assert result['pending_since'] == NOW.isoformat(timespec='seconds')
    assert result['next_check_at'] == (NOW + timedelta(days=1)).isoformat(timespec='seconds')
    assert not quality.load_yaml(path)[0]['resolved']


def nudt_page(name, email):
    return f'<p>姓名：</p><p>{name}</p><p>学院：</p><p>计算机学院</p><p>导师层次：</p><p>博导</p><p>基本情况：</p><p>研究计算机系统。{email}</p>'


def test_shared_contact_is_discovered_withdrawn_and_not_reintroduced_by_daily_refresh(tmp_path):
    cfg = dict(school='nudt',dept='cs',dept_name='计算机学院',hook='roster')
    put(tmp_path / 'sites/nudt/cs.yaml', cfg)
    shutil.copy2(ROOT / 'sites/nudt/roster.py', tmp_path / 'sites/nudt/roster.py')
    for i, name in enumerate(['甲老师','乙老师']):
        person = dict(slug=str(i), name=name, school='nudt',dept='cs',status='enriched',
            detail_url=f'https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/getView.view?keyId={i}',
            email='group@nudt.edu.cn',bio_raw='研究计算机系统。group@nudt.edu.cn',provenance={})
        put(tmp_path / f'data/professors/nudt/cs/{i}.yaml', person)
    def fetch(source):
        return nudt_page('甲老师' if source['url'].endswith('=0') else '乙老师', 'group@nudt.edu.cn').encode('utf-8')
    result = quality.run(tmp_path, fetcher=fetch, now=NOW)
    assert result['created'] == result['pending'] == 2
    for p in (tmp_path / 'data/professors/nudt/cs').glob('*.yaml'):
        assert not quality.load_yaml(p).get('email')
    assert quality.load_yaml(tmp_path / 'sites/nudt/cs.yaml')['shared_public_contacts'] == {'group@nudt.edu.cn':['乙老师','甲老师']}
    refreshed = legacy_refresh.run(tmp_path, kind='professors', fetcher=fetch, now=NOW+timedelta(days=1))
    assert refreshed['ok'] == 2 and refreshed['error'] == 0
    assert all(not quality.load_yaml(p).get('email') for p in (tmp_path / 'data/professors/nudt/cs').glob('*.yaml'))


def test_rejected_public_email_does_not_remove_manual_contact():
    p = dict(slug='x', name='张老师', school='nudt',dept='cs',detail_url='https://nudt.edu.cn/person',
        email='group@nudt.edu.cn',provenance={'email':dict(origin='manual',source='https://nudt.edu.cn/person',fetched_at='2026-10-01')})
    result, _, _ = legacy_refresh.merge_profile(p, {'bio_raw':'张老师研究系统','_rejected_email':'group@nudt.edu.cn'},'<p>张老师</p>','2026-11-16')
    assert result['email'] == p['email']


def test_explicit_different_profile_identity_is_rejected_even_if_old_name_is_in_body():
    p=dict(slug='teacher',name='张老师',school='test',dept='cs',detail_url='https://test.edu.cn/person')
    with pytest.raises(ValueError,match='明确姓名'):
        legacy_refresh.merge_profile(p,{'name':'李老师','bio_raw':'李老师与张老师合作'},'<p>李老师与张老师合作</p>','2026-11-16')


def test_fixed_parser_configuration_retries_without_manual_command(root):
    cfg_path=root/'sites/test/cs.yaml'
    cfg=quality.load_yaml(cfg_path);cfg['roster_only']=True;put(cfg_path,cfg)
    first=legacy_refresh.run(root,kind='professors',now=NOW,fetcher=lambda _:pytest.fail('roster only'))
    assert first['manual_required']==1
    assert legacy_refresh.run(root,kind='professors',now=NOW+timedelta(days=2),fetcher=lambda _:pytest.fail('not due'))['attempted']==0
    cfg['roster_only']=False;put(cfg_path,cfg)
    fixed=legacy_refresh.run(root,kind='professors',now=NOW+timedelta(days=2),fetcher=lambda _:body().encode('utf-8'))
    assert fixed['ok']==1


def test_unchanged_unsupported_parser_is_rechecked_weekly(root):
    cfg_path=root/'sites/test/cs.yaml';cfg=quality.load_yaml(cfg_path);cfg['roster_only']=True;put(cfg_path,cfg)
    legacy_refresh.run(root,kind='professors',now=NOW,fetcher=lambda _:pytest.fail('roster only'))
    next_check=legacy_refresh.run(root,kind='professors',now=NOW+timedelta(days=7),fetcher=lambda _:pytest.fail('roster only'))
    assert next_check['manual_required']==1


def test_hust_english_identity_does_not_use_non_identity_keywords():
    html = '''<title>华中科技大学主页平台管理系统 ke zhou--英文主页--Home</title>
<meta name="description" content="周可,ZHOU KE,个人主页"><meta name="keywords" content="实验室，周可，智能存储">
<div class="js-top"><div class="info"><h2>ke zhou</h2></div></div>
<div class="dft-side"><div class="Psl-info"><div class="cont">Professor<br>Supervisor of Doctorate Candidates</div></div></div>'''
    assert identity_names(BeautifulSoup(html,'html.parser')) == []
    with pytest.raises(ValueError):
        cyber_expansion.parse_detail({'school':'hust'},html,'http://faculty.hust.edu.cn/zhouke2/')


def test_hust_follows_only_real_same_person_chinese_link(tmp_path):
    cfg = dict(school='hust',dept='cyber',hook='cyber_expansion')
    put(tmp_path / 'sites/hust/cyber.yaml',cfg)
    shutil.copy2(ROOT/'sites/cyber_expansion.py',tmp_path/'sites/cyber_expansion.py')
    original=dict(name='周可',slug='zhouke',school='hust',dept='cyber',detail_url='http://faculty.hust.edu.cn/zhouke2/')
    def fetch(source):
        if source['url']==original['detail_url']:
            return '<a href="http://faculty.hust.edu.cn/zhouke2/zh_CN/index.htm">中文</a><a href="http://faculty.hust.edu.cn/other/zh_CN/index.htm">中文</a>'
        assert source['url']=='http://faculty.hust.edu.cn/zhouke2/zh_CN/index.htm'
        return '<div class="js-top"><div class="info"><h2>周可</h2></div></div><div class="infoblock"><p>职称：教授</p><p>博士生导师</p><p>所在单位：网络空间安全学院</p></div>'
    sources=quality.Sources(tmp_path,fetch,NOW.isoformat())
    updated,_,_,_=quality.profile(tmp_path,original,cfg,sources)
    assert updated['detail_url'].endswith('/zhouke2/zh_CN/index.htm') and updated['title']=='教授'
    assert updated['provenance']['detail_url']['source']==original['detail_url']


def test_whu_bio_contact_and_explicit_research_are_not_publication_emails():
    html = '''<div class="jjside"><p>教授</p><p>博士生导师</p><p>所在单位：国家网络安全学院</p></div>
<div class="rightfont"><p>核心研究方向包括：软件可靠性、形式化验证。</p><p>有意申请者，请将简历发送至电子邮箱：<span>teacher@whu.edu.cn</span>。</p><p>论文作者 paper@whu.edu.cn</p></div>'''
    parsed = cyber_expansion.parse_detail({'school':'whu'},html,'https://jszy.whu.edu.cn/person/')
    assert parsed['email'] == 'teacher@whu.edu.cn'
    assert parsed['research_directions'] == ['软件可靠性、形式化验证']


def test_nankai_gender_suffix_is_not_a_different_person_but_other_qualifiers_stay():
    from sites.nankai.faculty import parse_detail
    template='<div class="introduce-form"><div class="form"><p><span class="attribute">姓名：</span>{}</p><p><span class="attribute">电子邮件：</span>teacher@nankai.edu.cn</p></div></div>'
    assert parse_detail({'dept':'cs'},template.format('张健（男）'),'https://cc.nankai.edu.cn/page.htm')['name']=='张健'
    assert parse_detail({'dept':'cs'},template.format('王刚（计）'),'https://cc.nankai.edu.cn/page.htm')['name']=='王刚（计）'
