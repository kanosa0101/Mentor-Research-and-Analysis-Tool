import hashlib
import json
from datetime import timedelta

import pytest

from crawler import legacy_refresh, mentor_fields as fields, mentor_quality as quality, quality_status
from tests.test_mentor_contact_chain_v1119 import missing_contacts, person_file
from tests.test_mentor_quality_v1114 import NOW, body, put, root
from tests.test_mentor_recovery_v1115 import configure


def register(root, *, source='https://test.edu.cn/a', value='current@test.edu.cn', origin='crawled'):
    cfg=configure(root)
    person=missing_contacts(root)
    person.update(email=value,homepage='https://person.example.org/site')
    person['provenance']['email']=dict(origin=origin,source=source,fetched_at=NOW.date().isoformat(),confidence='auto')
    put(person_file(root),person)
    return cfg,person


def install_hook(root):
    path=root/'sites/test/demo.py'
    path.write_text(path.read_text(encoding='utf8')+'''
def parse_contact(cfg, original):
    assert 'email' not in original
    _, index=cfg['_read_source']('https://test.edu.cn/current-roster')
    url='https://test.edu.cn/'+index.strip()
    _, table=cfg['_read_source'](url)
    value=json.loads(table).get(original['name'])
    if not value:return {}
    return {'name':original['name'],'email':value,'_field_sources':{'email':url},
            '_contact_locator':{'email':{'article_url':'https://test.edu.cn/current-roster'}}}
''',encoding='utf8')


def response(name,value,*,target='a'):
    def fetch(request):
        if request['url'].endswith('/current-roster'):return target
        if isinstance(value,Exception):raise value
        return json.dumps({name:value},ensure_ascii=False)
    return fetch


def review(root):
    return fields.read(root)['records']['test/cs/teacher']['secondary_email']


def test_secondary_same_then_replaced_source_remains_under_normal_schedule(root):
    cfg,person=register(root)
    install_hook(root)
    name=person['name']
    premature=fields.run(root,limit=2,request_budget=6,now=NOW+timedelta(days=13),fetcher=lambda _:pytest.fail('not at 14 days'))
    assert premature['attempted']==0
    first_date=NOW+timedelta(days=14)
    first=fields.run(root,limit=2,request_budget=6,now=first_date,fetcher=response(name,person['email']))
    assert first['secondary_email']=={'verified':1} and first['filled_fields']==0
    assert first['results'][0]['changed_fields']==[]
    old=review(root)['last_success']
    assert old['url'].endswith('/a') and old['value']==person['email']
    assert quality.load_yaml(person_file(root))['provenance']['email']['fetched_at']==first_date.date().isoformat()
    # A changed parser configuration wakes a record before the next 14-day date.
    put(root/'sites/test/cs.yaml',dict(cfg,parser_stage='new-roster'))
    updated_date=first_date+timedelta(days=1)
    changed='new-person@test.edu.cn'
    second=fields.run(root,limit=2,request_budget=6,now=updated_date,fetcher=response(name,changed,target='b'))
    assert second['secondary_email']=={'verified':1} and second['results'][0]['changed_fields']==['email']
    stored=quality.load_yaml(person_file(root))
    assert stored['email']==changed and stored['provenance']['email']['source'].endswith('/b')
    assert review(root)['last_success']['sha256']==hashlib.sha256(json.dumps({name:changed},ensure_ascii=False).encode()).hexdigest()
    assert review(root)['next_check_at']==(updated_date+timedelta(days=14)).isoformat(timespec='seconds')


@pytest.mark.parametrize('failure,code,retry',[(ValueError('HTTP 403'),'http_forbidden',168),
    (ValueError('HTTP 429'),'rate_limited',24),(None,'no_current_unique_email',168),
    ('office@test.edu.cn','no_current_unique_email',168)])
def test_failure_preserves_old_value_date_and_evidence_and_is_visible(root,failure,code,retry):
    _,person=register(root)
    install_hook(root)
    initial=NOW+timedelta(days=14)
    fields.run(root,limit=2,request_budget=6,now=initial,fetcher=response(person['name'],person['email']))
    previous=review(root)['last_success']
    before=person_file(root).read_bytes()
    stamp=initial+timedelta(days=14)
    report=fields.run(root,limit=2,request_budget=6,now=stamp,fetcher=response(person['name'],failure))
    assert report['sources_error']==1 and person_file(root).read_bytes()==before
    assert review(root)['last_success']==previous and review(root)['reason_code']==code
    assert review(root)['next_check_at']==(stamp+timedelta(hours=retry)).isoformat(timespec='seconds')
    alerts=quality_status.refresh(root,stamp)
    assert alerts['summary']['missing_fields']==0
    assert alerts['mentor_field_breakdown']['secondary_email_by_reason']=={code:1}


def test_budget_resume_reuses_approved_hook_captures_after_restart(root):
    _,person=register(root)
    install_hook(root)
    stamp=NOW+timedelta(days=14)
    routes=[]
    def fetch(source):
        routes.append(source['url'])
        return response(person['name'],'renewed@test.edu.cn',target='b')(source)
    first=fields.run(root,limit=2,request_budget=1,now=stamp,fetcher=fetch)
    assert first['secondary_email']=={'continuing':1} and first['requests']==1
    assert quality.load_yaml(person_file(root))['email']==person['email']
    second=fields.run(root,limit=2,request_budget=1,now=stamp+timedelta(hours=1),fetcher=fetch)
    assert second['secondary_email']=={'verified':1} and second['requests']==1
    assert routes==['https://test.edu.cn/current-roster','https://test.edu.cn/b']


def test_multiple_profiles_reuse_one_current_roster_in_one_domain(root):
    _,person=register(root)
    install_hook(root)
    other=dict(person,slug='another',name='李老师',email='li@test.edu.cn')
    put(person_file(root).with_name('another.yaml'),other)
    def fetch(source):
        if source['url'].endswith('/current-roster'):return 'a'
        return json.dumps({person['name']:person['email'],other['name']:other['email']},ensure_ascii=False)
    result=fields.run(root,limit=2,request_budget=2,now=NOW+timedelta(days=14),fetcher=fetch)
    assert result['secondary_email']=={'verified':2} and result['requests']==2


@pytest.mark.parametrize('retired_link_remains',[False,True])
def test_linked_secondary_can_change_through_named_official_source(root,retired_link_remains):
    _,person=register(root)
    stamp=NOW+timedelta(days=14)
    requests=[]
    def fetch(source):
        route=source['url'].split('/')[-1]
        requests.append(route)
        if route=='old':
            retired='<p><a href="/a">联系方式</a></p>' if retired_link_remains else ''
            return body(email=None)+'<main><h1>张老师</h1>'+retired+'<p><a href="/b">联系方式</a></p></main>'
        if route=='a':raise ValueError('HTTP 404')
        return '<main><h1>张老师</h1><p>邮箱：renewed@test.edu.cn</p></main>'
    fields.run(root,limit=1,request_budget=1,now=stamp,fetcher=fetch)
    result=fields.run(root,limit=1,request_budget=2,now=stamp+timedelta(hours=1),fetcher=fetch)
    assert requests==(['old','a','b'] if retired_link_remains else ['old','b']) and result['secondary_email']=={'verified':1}
    assert review(root)['last_success']['linked_from']['url']=='https://test.edu.cn/old'
    assert quality.load_yaml(person_file(root))['email']=='renewed@test.edu.cn'


@pytest.mark.parametrize('source,origin',[('https://test.edu.cn/a','manual'),('http://test.edu.cn/old','crawled')])
def test_primary_or_manual_email_does_not_start_secondary_recheck(root,source,origin):
    register(root,source=source,origin=origin)
    install_hook(root)
    result=fields.run(root,limit=1,request_budget=6,now=NOW+timedelta(days=20),fetcher=lambda _:pytest.fail('not secondary'))
    assert result['attempted']==0


@pytest.mark.parametrize('other_name',['李老师','张老师'])
def test_registered_address_of_other_mentor_cannot_be_assigned(root,other_name):
    _,person=register(root)
    install_hook(root)
    other=dict(person,slug='another',name=other_name,email='shared@test.edu.cn',detail_url='https://test.edu.cn/different-profile')
    other['provenance']={'email':dict(origin='manual',source='maintainer',fetched_at='2026-11-16')}
    put(person_file(root).with_name('another.yaml'),other)
    report=fields.run(root,limit=2,request_budget=6,now=NOW+timedelta(days=14),fetcher=response(person['name'],other['email']))
    assert report['secondary_email']=={'retry':1} and review(root)['reason_code']=='shared_contact'
    assert quality.load_yaml(person_file(root))['email']==person['email']


@pytest.mark.parametrize('through_hook',[False,True])
def test_first_missing_email_write_uses_the_same_other_owner_gate(root,through_hook):
    configure(root)
    person=missing_contacts(root)
    other=dict(person,slug='another',detail_url='https://test.edu.cn/different-profile',
               email='shared@test.edu.cn',homepage='https://person.example.org/site',
               provenance={'email':dict(origin='manual',source='maintainer',fetched_at='2026-11-16')})
    put(person_file(root).with_name('another.yaml'),other)
    if through_hook:install_hook(root)
    fetch=response(person['name'],other['email']) if through_hook else lambda _:body(email=other['email'])
    report=fields.run(root,limit=1,request_budget=4,now=NOW,fetcher=fetch)
    assert report['filled_fields']==0 and 'email' not in quality.load_yaml(person_file(root))


def test_concurrent_manual_update_cannot_be_overwritten_or_falsely_verified(root):
    _,person=register(root)
    install_hook(root)
    def fetch(source):
        if source['url'].endswith('/a'):
            manual=dict(person,email='manual@test.edu.cn')
            manual['provenance']={'email':dict(origin='manual',source='maintainer',fetched_at='2026-11-16')}
            put(person_file(root),manual)
        return response(person['name'],'changed@test.edu.cn')(source)
    result=fields.run(root,limit=1,request_budget=6,now=NOW+timedelta(days=14),fetcher=fetch)
    assert result['secondary_email']=={'retry':1} and review(root)['reason_code']=='registration_changed'
    assert 'last_success' not in review(root)
    assert quality.load_yaml(person_file(root))['email']=='manual@test.edu.cn'


def test_ordinary_primary_merge_cannot_overwrite_or_remove_a_secondary_email(root):
    _,person=register(root)
    supplied={'name':person['name'],'title':'教授','email':'conflicting@test.edu.cn','_rejected_email':person['email']}
    merged,_,checked=legacy_refresh.merge_profile(person,supplied,body().encode(),NOW.date().isoformat())
    assert merged['email']==person['email'] and 'email' not in checked
    supplied['_field_sources']={'email':'https://test.edu.cn/b'}
    actual={'url':'https://test.edu.cn/b','sha256':'a'*64,'fetched_at':NOW.isoformat()}
    merged,_,checked=legacy_refresh.merge_profile(person,supplied,body().encode(),NOW.date().isoformat(),verified_sources=[actual])
    assert merged['email']=='conflicting@test.edu.cn' and 'email' in checked


def test_seed_does_not_attach_same_day_same_url_old_hash_to_changed_email(root):
    _,person=register(root)
    gap=dict(person)
    gap.pop('email')
    # The field evidence is still the older value when the YAML commit succeeds
    # just before an interrupted final write to the shared ledger.
    fields.observation(root,gap,now=NOW)
    first=person['provenance']['email']['source']
    fields.observation(root,person,parsed={'email':person['email']},source_url=first,source_sha256='a'*64,
                       fetched_at=NOW.isoformat(),now=NOW)
    fields.seed(root,NOW)
    assert review(root)['last_success']['sha256']=='a'*64
    person['email']='changed@test.edu.cn'
    put(person_file(root),person)
    fields.seed(root,NOW+timedelta(hours=1))
    assert 'last_success' not in review(root)


def test_resumed_linked_proof_is_rehashed_before_committing(root):
    _,person=register(root)
    routes={'old':body(email=None)+'<main><h1>张老师</h1><p><a href="/a">联系方式</a></p><p><a href="/b">联系方式</a></p></main>',
            'a':'<main><h1>张老师</h1><p>邮箱：changed@test.edu.cn</p></main>',
            'b':'<main><h1>张老师</h1><p>研究方向：机器学习</p></main>'}
    stamp=NOW+timedelta(days=14)
    fetch=lambda source:routes[source['url'].split('/')[-1]]
    initial=fields.run(root,limit=1,request_budget=2,now=stamp,fetcher=fetch)
    assert initial['secondary_email']=={'continuing':1}
    raw=review(root)['frontier']['proofs'][0]['sha256']
    (root/'cache/mentor_quality/evidence'/(raw+'.body')).write_bytes(b'changed')
    result=fields.run(root,limit=1,request_budget=1,now=stamp+timedelta(hours=1),fetcher=fetch)
    assert result['secondary_email']=={'retry':1} and review(root)['reason_code']=='evidence_unavailable'
    assert 'frontier' not in review(root) and quality.load_yaml(person_file(root))['email']==person['email']
    recovered=fields.run(root,limit=1,request_budget=3,now=stamp+timedelta(hours=3),fetcher=fetch)
    assert recovered['secondary_email']=={'verified':1}
    assert quality.load_yaml(person_file(root))['email']=='changed@test.edu.cn'
