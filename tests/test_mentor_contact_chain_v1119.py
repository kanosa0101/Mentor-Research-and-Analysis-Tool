import hashlib
import json
from datetime import timedelta
from threading import Barrier, Lock

import pytest

from crawler import legacy_refresh, mentor_fields as fields, mentor_quality as quality, mentor_recovery as recovery
from crawler.source_discovery import canonical
from tests.test_mentor_quality_v1114 import NOW, body, put, root
from tests.test_mentor_recovery_v1115 import configure


def person_file(root):
    return root / 'data/professors/test/cs/teacher.yaml'


def missing_contacts(root):
    person = quality.load_yaml(person_file(root))
    person.pop('email', None)
    person.update(title='教授', supervisor='博导', research_direction_raw='机器学习')
    put(person_file(root), person)
    return person


def test_three_round_contact_chain_keeps_each_source_and_never_repeats_primary(root):
    configure(root)
    missing_contacts(root)
    pages = {
        '/old': body(email=None) + '<main><h1>张老师</h1><p>实验室主页：<a href="/lab">访问</a></p></main>',
        '/lab': '<main><h2>张老师</h2><p><a href="/contact">联系方式</a></p></main>',
        '/contact': '<main><h2>张老师</h2><p>本人邮箱：zhang@test.edu.cn</p></main>',
    }
    calls = []

    def fetch(source):
        route = source['url'].removeprefix('https://test.edu.cn')
        calls.append(route)
        return pages[route]

    first = fields.run(root, limit=1, request_budget=1, fetcher=fetch, now=NOW)
    assert first['results'][0]['filled_fields'] == []
    assert first['results'][0]['next_contact_source'].endswith('/lab')
    second = fields.run(root, limit=1, request_budget=1, fetcher=fetch, now=NOW + timedelta(hours=1))
    assert second['results'][0]['filled_fields'] == ['homepage']
    assert second['results'][0]['field_evidence']['homepage']['sha256'] == hashlib.sha256(pages['/old'].encode()).hexdigest()
    assert second['results'][0]['field_evidence']['homepage']['target_evidence']['sha256'] == hashlib.sha256(pages['/lab'].encode()).hexdigest()
    assert second['results'][0]['next_contact_source'].endswith('/contact')
    third = fields.run(root, limit=1, request_budget=1, fetcher=fetch, now=NOW + timedelta(hours=2))
    assert calls == ['/old', '/lab', '/contact']
    assert third['results'][0]['filled_fields'] == ['email']
    assert third['results'][0]['field_evidence']['email']['linked_from']['url'].endswith('/lab')
    person = quality.load_yaml(person_file(root))
    assert person['homepage'].endswith('/lab') and person['email'] == 'zhang@test.edu.cn'
    assert person['provenance']['homepage']['source'].endswith('/old')
    assert person['provenance']['email']['source'].endswith('/contact')
    ledger = fields.read(root)['records']['test/cs/teacher']['fields']
    assert ledger['email']['source_sha256'] == hashlib.sha256(pages['/contact'].encode()).hexdigest()
    assert ledger['homepage']['source_url'].endswith('/old')
    before = person_file(root).read_bytes()
    fields.run(root, limit=1, request_budget=1, fetcher=fetch, now=NOW + timedelta(hours=3))
    assert calls == ['/old', '/lab', '/contact'] and person_file(root).read_bytes() == before


def test_registered_roster_is_an_automatic_identity_path(root):
    cfg = configure(root)
    cfg.update(roster_only=True, list={'url': 'https://test.edu.cn/people'})
    put(root / 'sites/test/cs.yaml', cfg)
    person = missing_contacts(root)
    person['detail_url'] = 'https://test.edu.cn/people'
    put(person_file(root), person)
    called = []

    def fetch(source):
        called.append(source['url'])
        if source['url'].endswith('/people'):
            return '<a href="/new">张老师</a>'
        if source['url'].endswith('/new'):
            return '<main><h1>张老师</h1><p>邮箱：zhang@test.edu.cn</p></main>'
        return '<p>院系主页</p>'

    fields.run(root, limit=1, request_budget=1, fetcher=fetch, now=NOW)
    result = fields.run(root, limit=1, request_budget=3, fetcher=fetch, now=NOW+timedelta(days=1))
    assert result['results'][0]['field_evidence']['email']['identity_basis'] == 'registered_roster_and_named_detail'
    saved = quality.load_yaml(person_file(root))
    assert saved['detail_url'].endswith('/people') and saved['provenance']['email']['source'].endswith('/new')
    assert 'homepage' not in saved


def test_contact_extractor_ignores_other_people_roles_and_site_chrome():
    html = '''<main><article class="member"><h2>张老师</h2><p>邮箱：office@test.edu.cn</p>
      <p>学生邮箱：student@test.edu.cn</p><p>招生联系人邮箱：apply@test.edu.cn</p></article>
      <article class="member"><h2>李老师</h2><p>邮箱：li@test.edu.cn</p></article></main>
      <footer><p>邮箱：footer@test.edu.cn</p><a href="/home">个人主页</a></footer>'''
    result = recovery.contact_details(html, 'https://test.edu.cn/page', '张老师')
    assert result == {'email': None, 'homepage': None, 'links': []}


@pytest.mark.parametrize('head,peer,name',[('h2','h2','李老师'),('h1','h2','李老师'),
    ('h1','h3 class="teacher-name"','李老师'),('h1','h2','Professor John Smith'),('h1','h2','John Smith')])
def test_main_page_sections_cannot_fill_one_teacher_from_another_teacher(root,head,peer,name):
    configure(root)
    missing_contacts(root)
    own=f'<{head}>张老师</{head}><p>研究方向：机器学习</p>'
    if head=='h2':own=f'<section>{own}</section>'
    main=f'''<main>{own}<section><{peer}>{name}</{peer.split()[0]}><p>邮箱：li@test.edu.cn</p>
      <p><a href="/li">个人主页</a></p></section></main>'''
    report=fields.run(root,limit=1,request_budget=1,now=NOW,fetcher=lambda _:body(email=None)+main)
    assert report['filled_fields']==0
    assert report['results'][0]['next_contact_source'] is None
    assert not {'email','homepage'} & quality.load_yaml(person_file(root)).keys()


def test_retryable_child_response_keeps_queue_and_retries_after_cooldown(root):
    configure(root)
    missing_contacts(root)
    calls=[]
    declared=body(email=None)+'<main><h1>张老师</h1><p><a href="/contact">联系方式</a></p></main>'
    def fetch(source):
        calls.append(source['url'])
        if source['url'].endswith('/old'):return declared
        if calls.count('https://test.edu.cn/contact')==1:raise ValueError('HTTP 429')
        return '<main><h1>张老师</h1><p>邮箱：zhang@test.edu.cn</p></main>'
    first=fields.run(root,limit=1,request_budget=2,now=NOW,fetcher=fetch)
    assert first['results'][0]['next_contact_source'].endswith('/contact')
    saved=fields.read(root)['records']['test/cs/teacher']['contact_search']
    assert saved['next_at']==(NOW+timedelta(hours=24)).isoformat(timespec='seconds')
    assert fields.run(root,limit=1,request_budget=2,now=NOW+timedelta(hours=1),fetcher=fetch)['attempted']==0
    final=fields.run(root,limit=1,request_budget=2,now=NOW+timedelta(hours=25),fetcher=fetch)
    assert final['results'][0]['filled_fields']==['email']
    assert [i.split('/')[-1] for i in calls]==['old','contact','contact']


def test_unreachable_wrong_identity_and_external_homepages_remain_candidates(root):
    configure(root)
    missing_contacts(root)
    for step,(href,destination) in enumerate((('/missing',ValueError('HTTP 403')),
            ('/someone','<main><h1>李老师</h1><p>邮箱：li@test.edu.cn</p></main>'),('https://example.org/person',None))):
        calls=[]
        def fetch(source):
            calls.append(source['url'])
            if source['url'].endswith('/old'):
                return body(email=None)+f'<main><h1>张老师</h1><p>个人主页：<a href="{href}">访问</a></p></main>'
            if isinstance(destination,Exception):raise destination
            return destination
        fields.run(root,limit=1,request_budget=2,now=NOW+timedelta(days=31*step),fetcher=fetch)
        assert not {'homepage','email'} & quality.load_yaml(person_file(root)).keys()
        if step==2:
            assert calls==['https://test.edu.cn/old']
            candidate=fields.read(root)['records']['test/cs/teacher']['contact_search']['external_homepage_candidate']
            assert candidate['url']==href and candidate['declared_at']['sha256']


def test_algorithmic_contact_review_can_reopen_but_manual_value_is_protected(root):
    cfg = configure(root)
    person = missing_contacts(root)
    person['provenance'] = {'homepage': {'origin': 'manual', 'source':'maintainer', 'fetched_at':'2026-11-16'}}
    put(person_file(root), person)
    fields.observation(root, person, parsed={'_rejected_email':'office@test.edu.cn'},
                       parser_signature=recovery.signature(root,cfg), now=NOW)
    row = fields.read(root)['records']['test/cs/teacher']
    assert not fields.due(row,cfg,root,NOW.isoformat())
    assert fields.due(row, cfg, root, NOW.isoformat(), 'new-roster-revision')
    cfg['profile_http_hosts']=['test.edu.cn']
    put(root / 'sites/test/cs.yaml',cfg)
    result = fields.run(root, limit=1, request_budget=2, now=NOW, fetcher=lambda _:
                        body(email='zhang@test.edu.cn')+'<p><a href="https://other.example.com/a">个人主页</a></p>')
    assert result['results'][0]['filled_fields'] == ['email']
    assert 'homepage' not in quality.load_yaml(person_file(root))


def test_parallel_domains_share_total_budget_and_respect_429_cooldown(root):
    cfg = configure(root)
    person = missing_contacts(root)
    put(root / 'sites/other/cs.yaml', dict(cfg, school='other', base_url='https://other.edu.cn'))
    path = root/'sites/other/demo.py'
    path.write_bytes((root/'sites/test/demo.py').read_bytes())
    put(root / 'data/professors/other/cs/teacher.yaml', dict(person, school='other', detail_url='https://other.edu.cn/old'))
    barrier = Barrier(2, timeout=5)
    calls = []
    lock = Lock()

    def fetch(source):
        with lock:
            calls.append(source['url'])
        barrier.wait()
        if 'test.edu.cn' in source['url']:
            raise ValueError('HTTP 429')
        return body(email='zhang@other.edu.cn')

    first = fields.run(root, limit=2, request_budget=2, domain_budget=1, workers=2, fetcher=fetch, now=NOW)
    assert first['requests_by_domain'] == {'test.edu.cn': 1, 'other.edu.cn': 1}
    assert set(first['domain_cooldowns']) == {'test.edu.cn'}
    assert len(calls) == 2
    later = fields.run(root,limit=2,request_budget=2,now=NOW+timedelta(hours=1),fetcher=lambda source: calls.append(source['url']) or body())
    assert later['domain_cooldowns'] == first['domain_cooldowns']
    assert all('test.edu.cn' not in url for url in calls[2:])


def test_site_pdf_eligibility_requires_opt_in_school_host_and_exact_attachment_path(root):
    cfg=configure(root)
    source='http://test.edu.cn/_upload/article/files/d4/45/e46a2ca6469693738d84d1fffc3f/7e0b4187-7b2b-44da-951d-f9439b508c1e.pdf'
    with pytest.raises(ValueError):
        canonical(source,'https://test.edu.cn')
    assert not recovery.contact_allowed(source,'https://test.edu.cn',cfg)
    cfg.update(profile_http_hosts=['test.edu.cn'], profile_pdf_hosts=['test.edu.cn'])
    assert recovery.contact_target(source,cfg)==source
    assert recovery.contact_allowed(source,'https://test.edu.cn',cfg)
    assert not recovery.contact_allowed(source,'https://other.edu.cn',cfg)
    assert not recovery.contact_allowed(source+'?a=1','https://test.edu.cn',cfg)
    assert not recovery.contact_allowed('https://test.edu.cn/news/doc.pdf','https://test.edu.cn',cfg)


def test_supplemental_hook_only_publishes_captured_field_sources(root):
    configure(root)
    person=missing_contacts(root)
    person['homepage']='https://test.edu.cn/home'
    put(person_file(root),person)
    path=root/'sites/test/demo.py'
    path.write_text(path.read_text(encoding='utf-8')+'''
def parse_contact(cfg, original):
    source='https://test.edu.cn/roster'
    cfg['_read_source'](source)
    return dict(name=original['name'],email='zhang@test.edu.cn',_field_sources={'email': source})
''',encoding='utf-8')
    reply='<p>本院导师名册 张老师 邮箱：zhang@test.edu.cn</p>'
    first=fields.run(root,limit=1,request_budget=1,now=NOW,fetcher=lambda _:reply)
    assert first['results'][0]['field_evidence']['email']['sha256']==hashlib.sha256(reply.encode()).hexdigest()
    verified=quality.load_yaml(person_file(root))
    assert verified['provenance']['email']['source']=='https://test.edu.cn/roster'
    put(person_file(root),person)
    path.write_text(path.read_text(encoding='utf-8').replace("    cfg['_read_source'](source)\n",''),encoding='utf-8')
    fields.run(root,limit=1,request_budget=1,now=NOW+timedelta(hours=1),fetcher=lambda _:body(email=None))
    assert 'email' not in quality.load_yaml(person_file(root))


def test_external_cache_cannot_produce_official_contact(root):
    configure(root)
    person=missing_contacts(root)
    person['detail_url']='https://outside.example.net/person'
    put(person_file(root),person)
    raw=body(email='external@example.net').encode()
    digest=hashlib.sha256(raw).hexdigest()
    cache=root/'cache/legacy_refresh'
    (cache/'evidence').mkdir(parents=True)
    (cache/'evidence'/(digest+'.body')).write_bytes(raw)
    (cache/'state.json').write_text(json.dumps({'records':{'professor/test/cs/teacher.yaml':{
        'status':'ok','source_url':person['detail_url'],'last_success':NOW.isoformat(),'raw_sha256':digest}}}),encoding='utf-8')
    result=fields.run(root,limit=1,request_budget=1,now=NOW,fetcher=lambda _:pytest.fail('external source must not be requested'))
    assert result['requests']==result['filled_fields']==0
    assert not result['results'][0]['reused_evidence']
    assert 'email' not in quality.load_yaml(person_file(root))


def test_normal_professor_and_issue_refresh_cannot_bypass_homepage_gate(root):
    configure(root)
    missing_contacts(root)
    reply=body().replace('"title":', '"homepage":"https://test.edu.cn/unverified", "title":')
    result=legacy_refresh.run(root,kind='professors',limit=1,fetcher=lambda _:reply.encode(),now=NOW)
    assert result['ok']==1
    assert 'homepage' not in quality.load_yaml(person_file(root))
    original=quality.load_yaml(person_file(root))
    cfg=quality.load_yaml(root/'sites/test/cs.yaml')
    sources=quality.Sources(root,lambda _:reply,NOW.isoformat())
    updated,_,_,_=quality.profile(root,original,cfg,sources,allow_alternative=False)
    assert 'homepage' not in updated


@pytest.mark.parametrize('source',['https://test.edu.cn/old','https://test.edu.cn/new-contact'])
def test_seed_does_not_relabel_old_evidence_after_an_interrupted_ledger_write(root,source):
    configure(root)
    person=missing_contacts(root)
    fields.observation(root,person,parsed={'_field_scope':'张老师'},source_sha256='a'*64,
                       fetched_at=NOW.isoformat(),now=NOW)
    person['email']='zhang@test.edu.cn'
    person['provenance']['email']={'origin':'crawled','source':source,
                                   'fetched_at':'2026-11-16','confidence':'auto'}
    put(person_file(root),person)
    row=fields.seed(root,NOW+timedelta(hours=1))['records']['test/cs/teacher']['fields']['email']
    assert row['status']=='resolved' and row['source_url']==source
    assert 'source_sha256' not in row and 'fetched_at' not in row
