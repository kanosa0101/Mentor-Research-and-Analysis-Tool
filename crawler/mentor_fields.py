"""Field-level public mentor gaps; absence is not a network or identity failure."""
import hashlib
import json
import re
from copy import deepcopy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from bs4 import UnicodeDammit

from crawler.opportunity_monitor import atomic_json,output_lock
from crawler.public_discovery import research_text,title_group,valid_email
from crawler import mentor_recovery
from sites.profile_fields import direction_is_mixed

CONTACT_FIELDS=('email','homepage')
FIELDS=(*CONTACT_FIELDS,'research_direction_raw','supervisor','title')
LABELS={'email':'本人邮箱','homepage':'个人或课题组主页','research_direction_raw':'研究方向','supervisor':'招生资格','title':'职称'}
PATH='cache/mentor_quality/field-gaps.json'
LEDGER_LOCK=Lock()
SECONDARY_EMAIL_PERIOD=timedelta(days=14)
LOCAL_ZONE=timezone(timedelta(hours=8))


def present(person,field):
    value=person.get(field)
    if field=='email':return valid_email(value)
    if field=='homepage':return bool(mentor_recovery.homepage_url(value))
    if field=='research_direction_raw':return bool(research_text(value)) and not direction_is_mixed(value)
    if field=='title':return title_group(value)!='unknown'
    return bool(re.search(r'博|硕',value or '') and not re.search(r'无|非|不|未具备',value or ''))


def identifier(person):
    return person['school']+'/'+person['dept']+'/'+person['slug']


def read(root):
    path=Path(root)/PATH
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {'version':1,'records':{}}


def secondary_email_source(person,*,include_primary=False):
    provenance=(person.get('provenance') or {}).get('email') or {}
    source=mentor_recovery.homepage_url(provenance.get('source'))
    if not source or provenance.get('origin')!='crawled' or not present(person,'email'):return None
    detail=person['detail_url']
    if (include_primary or mentor_recovery.canonical(source).rstrip('/')!=mentor_recovery.canonical(detail).rstrip('/')
            or urlsplit(source).path.lower().endswith('.pdf')):
        return provenance
    return None


def secondary_registration(person,provenance):
    return {key:provenance.get(key) for key in ('source','fetched_at')} | {'value':person['email']}


def secondary_schedule(person,now,*,include_primary=False):
    provenance=secondary_email_source(person,include_primary=include_primary)
    if not provenance:return None
    registration=secondary_registration(person,provenance)
    try:
        fetched=datetime.fromisoformat(provenance.get('fetched_at') or '')
        if not fetched.tzinfo:fetched=fetched.replace(tzinfo=LOCAL_ZONE)
        scheduled=min(fetched,now)+SECONDARY_EMAIL_PERIOD
    except ValueError:
        scheduled=now
    return dict(registration=registration,status='scheduled',next_check_at=scheduled.astimezone(timezone.utc).isoformat(timespec='seconds'))


def commit_contact_profile(file,before,after,owners,owner_lock,*,recheck=False):
    from crawler.mentor_quality import write_profile
    old,value=before.get('email'),after.get('email')
    if recheck or old!=value:
        ident=identifier(before)
        with owner_lock:
            if value and owners.get(value.casefold(),set())-{ident}:
                raise ValueError('官方邮箱在其他导师记录中登记，无法确认本人独占归属')
            write_profile(file,before,after)
            if old and old.casefold()!=(value or '').casefold():
                owners.get(old.casefold(),set()).discard(ident)
            if value:owners.setdefault(value.casefold(),set()).add(ident)
    elif after!=before:
        write_profile(file,before,after)


def secondary_due(review,signature,stamp,digest_by_url):
    if not review:return False
    changed=any(url in digest_by_url and digest_by_url[url]!=digest for url,digest in review.get('directory_versions',{}).items())
    return (review['next_check_at']<=stamp or changed or
            bool(review.get('parser_signature') and review['parser_signature']!=signature))


def summarize(state):
    pending=[(record,field,value) for record in state['records'].values() for field,value in record['fields'].items() if value.get('status')!='resolved']
    optional=[(record,field,value) for record,field,value in pending if field=='homepage' or value.get('optional')]
    active=[(record,field,value) for record,field,value in pending if field!='homepage' and not value.get('optional')]
    return dict(profiles=len({record['id'] for record,_,_ in active}),fields=len(active),
                by_field=dict(Counter(field for _,field,_ in active)),by_reason=dict(Counter(v['reason_code'] for _,_,v in active)),
                by_status=dict(Counter(v['status'] for _,_,v in active)),by_unit=dict(Counter(record['unit'] for record,_,_ in active)),
                optional_fields=len(optional),optional_by_field=dict(Counter(field for _,field,_ in optional)))


def seed(root,now=None,*,email_owners=None):
    """Inventory missing/contaminated fields without making a network request."""
    from crawler.mentor_quality import load_yaml,profile_missing
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds');path=root/PATH
    with LEDGER_LOCK,output_lock(path):
        state=read(root)
        signatures={};configs={};seen=set()
        for file in sorted((root/'data/professors').glob('*/*/*.yaml')):
            person=load_yaml(file);key=identifier(person);record=state['records'].get(key)
            seen.add(key)
            if email_owners is not None and present(person,'email'):
                email_owners.setdefault(person['email'].casefold(),set()).add(key)
            unit=key.rsplit('/',1)[0]
            if unit not in configs:
                cfg_path=root/'sites'/(unit+'.yaml')
                configs[unit]=(load_yaml(cfg_path) or {}) if cfg_path.exists() else {}
            cfg=configs[unit]
            review=secondary_schedule(person,now,include_primary=bool(cfg.get('contact_hook_only')))
            gaps=[field for field in FIELDS if not present(person,field)]
            if not gaps and record is None and review is None:continue
            if record is None:
                record=dict(id=key,unit=person['school']+'/'+person['dept'],ref=person['slug'],name=person['name'],first_seen=stamp,fields={})
                state['records'][key]=record
            if review is None:
                record.pop('secondary_email',None)
            elif (record.get('secondary_email') or {}).get('registration')!=review['registration']:
                if unit not in signatures:
                    signatures[unit]=mentor_recovery.signature(root,cfg) if cfg else None
                if signatures[unit]:review['parser_signature']=signatures[unit]
                prior=record['fields'].get('email') or {}
                if (prior.get('reason_code')=='field_verified' and prior.get('verified_value')==person['email'] and
                        prior.get('source_url')==review['registration']['source'] and
                        prior.get('source_sha256') and prior.get('fetched_at')):
                    try:prior_day=datetime.fromisoformat(prior['fetched_at']).astimezone(LOCAL_ZONE).date().isoformat()
                    except ValueError:prior_day=None
                    if prior_day and prior_day==review['registration']['fetched_at']:
                        review['last_success']=dict(url=prior['source_url'],sha256=prior['source_sha256'],fetched_at=prior['fetched_at'],value=person['email'])
                record['secondary_email']=review
            for field in FIELDS:
                prior=record['fields'].get(field)
                if field=='homepage' and prior:prior['optional']=True
                if field not in gaps:
                    if prior and prior.get('status')!='resolved':
                        confirmed_source=(person.get('provenance',{}).get(field) or {}).get('source')
                        # A separate writer may have captured newer bytes at
                        # the same URL; a prior gap SHA cannot prove this value.
                        prior.pop('source_sha256',None)
                        prior.pop('fetched_at',None)
                        prior.pop('verified_value',None)
                        prior.update(status='resolved',reason_code='record_now_complete',reason='当前登记已有该字段；沿用其实际来源日期',resolved_at=stamp,
                                     pending_since=None,source_url=confirmed_source,next_action='none',next_check_at=None)
                    continue
                manual=(person.get('provenance',{}).get(field) or {}).get('origin')=='manual'
                if prior and prior.get('status')!='resolved' and manual==(prior.get('reason_code')=='manual_field'):continue
                mixed=field=='research_direction_raw' and direction_is_mixed(person.get(field))
                code='manual_field' if manual else 'content_mixed' if mixed else 'not_checked'
                record['fields'][field]=dict(first_seen=(prior or {}).get('first_seen',stamp),pending_since=stamp,
                    status='manual_review' if manual else 'pending',reason_code=code,reason='人工字段保留，需本人维护确认' if manual else '方向混有项目或履历，需从本人原文提取' if mixed else '当前缺少'+LABELS[field]+'，等待核验本人官方资料',
                    next_action='manual_review' if manual else 'verify_field',source_url=person['detail_url'],next_check_at=None if manual else stamp)
                if field=='homepage':record['fields'][field]['optional']=True
            record['updated_at']=stamp
        for key in state['records'].keys()-seen:
            record=state['records'][key]
            if profile_missing(root,record['unit'],record['ref']):
                del state['records'][key]
        state['scanned_at']=stamp;state['summary']=summarize(state);atomic_json(path,state)
    return state


def observation(root,person,*,parsed=None,body=None,source_sha256=None,fetched_at=None,now=None,error=None,
                parser_signature=None,source_url=None,contact_search=None,contact_only=False,ledger_only=False,ledger=None,
                verified_sources=()):
    """Record what a verified personal source did/did not disclose, per field."""
    from crawler import mentor_recovery
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds');path=root/PATH;key=identifier(person)
    parsed=parsed or {};scope=parsed.get('_field_scope') or parsed.get('bio_raw') or ''
    declared_sources=parsed.get('_field_sources') or {}
    captured_sources={row['url']:row for row in verified_sources if row.get('url') and row.get('fetched_at')
                      and re.fullmatch('[a-f0-9]{64}',row.get('sha256') or '')}
    with LEDGER_LOCK,(nullcontext() if ledger is not None else output_lock(path)):
        state=ledger if ledger is not None else read(root);record=state['records'].get(key)
        gaps=[field for field in FIELDS if not present(person,field)]
        if record is None and not gaps:return
        if record is None:record=dict(id=key,unit=person['school']+'/'+person['dept'],ref=person['slug'],name=person['name'],first_seen=stamp,fields={});state['records'][key]=record
        selected=() if ledger_only else CONTACT_FIELDS if contact_only else FIELDS
        for field in (set(gaps)|set(record['fields'])) & set(selected):
            prior=record['fields'].get(field,{})
            proof_source=source_url or person['detail_url']
            proof_sha, proof_time=source_sha256, fetched_at
            verified=bool(parsed.get(field)) and not error
            current=((person.get('provenance') or {}).get(field) or {})
            if target:=declared_sources.get(field):
                proof=captured_sources.get(target)
                verified=(verified and proof is not None and current.get('origin')!='manual'
                          and current.get('source')==target and parsed[field]==person.get(field))
                if verified:
                    proof_source,proof_sha,proof_time=target,proof['sha256'],proof['fetched_at']
                else:
                    proof_source,proof_sha=prior.get('source_url') or proof_source,None
            if field=='email' and present(person,field):
                verified=(verified and mentor_recovery.personal_email(parsed.get(field))==person[field] and
                          current.get('origin')!='manual' and (not current.get('source') or current['source']==proof_source))
            if field=='research_direction_raw' and present(person,field):
                verified=(verified and parsed.get(field)==person[field] and current.get('origin')!='manual'
                          and (not current.get('source') or current['source']==proof_source))
            if present(person,field) and prior.get('status')=='resolved' and not verified:continue
            if (not contact_only and contact_search is None and field in CONTACT_FIELDS
                    and (record.get('contact_search') or {}).get('next_at') and not present(person,field)):continue
            value=dict(prior,first_seen=prior.get('first_seen',stamp),checked_at=stamp,source_url=proof_source)
            if field=='homepage':value['optional']=True
            if proof_sha:value.update(source_sha256=proof_sha,fetched_at=proof_time)
            if parser_signature:value['parser_signature']=parser_signature
            if present(person,field):
                if field=='email' and verified and proof_sha and proof_time:value['verified_value']=person[field]
                elif field=='email' or field=='research_direction_raw' and not verified:
                    for item in ('verified_value','source_sha256','fetched_at'):value.pop(item,None)
                value.update(status='resolved',reason_code='field_verified' if verified else 'record_now_complete',
                             reason='本人官方资料已提供该字段' if verified else '当前登记已有该字段；本轮未重新取得该字段证据',pending_since=None,next_action='none',next_check_at=None,resolved_at=stamp)
            else:
                code='not_extracted';reason='当前解析器未提取到'+LABELS[field];action='adapt_parser';hours=168;status='pending'
                manual=(person.get('provenance',{}).get(field) or {}).get('origin')=='manual'
                if manual:code,reason,action,status='manual_field','人工字段保留，自动任务不覆盖','manual_review','manual_review'
                elif parsed.get('_rejected_email') and field=='email':code,reason,action,status='shared_contact','官方资料的邮箱归属不明确，不能当作本人邮箱','manual_review','manual_review'
                elif error:
                    failure=mentor_recovery.classify(str(error));code=failure['reason_code'];action=failure['next_action'];hours=failure['retry_hours'];reason=str(error)[:500]
                    if '尚无本人详情来源' in str(error):code,action,hours='source_missing','discover_official_source',24*7
                    elif code=='identity_conflict':status='manual_review'
                    elif code=='identity_evidence_missing':status='pending'
                    else:status='error'
                elif field=='research_direction_raw' and direction_is_mixed(person.get(field)):
                    code,reason='content_mixed','本次未取得可替换的纯研究方向，保留原值待继续提取'
                elif scope:
                    marker={'email':r'邮箱|电子邮件|e-?mail|@','homepage':r'个人主页|课题组主页|实验室主页|homepage',
                            'research_direction_raw':r'研究方向|研究领域|研究兴趣|主要从事|research interests?',
                            'supervisor':r'博士(?:研究)?生导师|硕士(?:研究)?生导师|博导|硕导','title':r'职称|教授|研究员|讲师|工程师'}[field]
                    if not re.search(marker,scope,re.I):
                        code='not_found_in_checked_source';reason='本次核验的本人公开资料未见明确'+LABELS[field]+'；不代表所有官网均未公开'
                        action='wait_for_source_update';hours=24*30;status='waiting_source'
                else:
                    code='source_missing';reason='尚无足够的本人详情正文判断该字段是否公开';action='discover_official_source';hours=24
                pending_since=(stamp if not prior.get('checked_at') or prior.get('status') in ('waiting_source','resolved') else prior.get('pending_since') or stamp)
                value.update(status=status,reason_code=code,reason=reason,next_action=action,pending_since=pending_since,
                             next_check_at=None if status=='manual_review' else (now+timedelta(hours=hours)).isoformat(timespec='seconds'))
            record['fields'][field]=value
        if contact_search is not None:
            record['contact_search']=contact_search
            for field in CONTACT_FIELDS:
                value=record['fields'].get(field)
                if value and value['reason_code']!='manual_field' and value['status']!='resolved':
                    if contact_search['next_at']:
                        value.update(status='pending',reason_code='additional_official_source',reason='已登记下一处官方来源，待核验本人字段',
                                     next_action='discover_official_source',next_check_at=contact_search['next_at'])
                    elif value['reason_code']=='additional_official_source':
                        value.update(status='waiting_source',reason_code='checked_official_sources',reason='已核验本轮可用的本人官方来源，未确认该字段',
                                     next_action='wait_for_source_update',next_check_at=(now+timedelta(days=30)).isoformat(timespec='seconds'))
        record['updated_at']=stamp
        if ledger is None:
            state['summary']=summarize(state)
            atomic_json(path,state)


def due(record,cfg,root,stamp,directory_revision=None,*,parser_signature=None):
    from crawler.mentor_recovery import signature
    current=parser_signature or signature(root,cfg)
    revision_changed=bool(directory_revision and (record.get('contact_search') or {}).get('directory_revision')!=directory_revision)
    return any(value.get('status')!='resolved' and value.get('reason_code')!='manual_field' and
               (value.get('parser_signature')!=current or field in CONTACT_FIELDS and revision_changed or
                value.get('status')!='manual_review' and (not value.get('next_check_at') or value['next_check_at']<=stamp))
               for field,value in record['fields'].items())


def needs_contact(person,field):
    return not present(person,field) and (person.get('provenance',{}).get(field) or {}).get('origin')!='manual'


def add_links(search,links,parent,scope,cfg,depth):
    if depth>2 or len(search['queue'])>=8:return
    known={mentor_recovery.canonical(url) for url in (*search['visited'],*(item['url'] for item in search['queue']))}
    for link in links:
        if link['kind']=='homepage_check':
            target=link['url']
            allowed=bool(mentor_recovery.homepage_scope(target,scope))
        else:
            target=mentor_recovery.contact_target(link['url'],cfg)
            allowed=mentor_recovery.contact_allowed(target,scope,cfg)
        canonical=mentor_recovery.canonical(target)
        if canonical in known or not allowed:continue
        search['queue'].append(dict(link,url=target,parent=parent,depth=depth))
        known.add(canonical)
        if len(search['queue'])>=8:break


def cached_detail(root,original,record,legacy,now):
    rows=[(legacy.get('last_success'),legacy.get('source_url'),legacy.get('raw_sha256'),'legacy_refresh')] if legacy.get('status')=='ok' else []
    rows += [(v.get('fetched_at'),v.get('source_url'),v.get('source_sha256'),'mentor_quality') for v in record['fields'].values()]
    for prior,url,digest,folder in sorted(rows,key=lambda row:row[0] or '',reverse=True):
        moment=datetime.fromisoformat(prior) if prior else None
        if url!=original['detail_url'] or not moment or not timedelta(0)<=now-moment<=timedelta(days=1):continue
        if not digest or not re.fullmatch('[a-f0-9]{64}',digest):continue
        file=root/'cache'/folder/'evidence'/(digest+'.body')
        if file.is_file():
            raw=file.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('缓存原文SHA不一致，未复用')
            return raw,prior
    return None,None


def directory_contacts(root,person,cfg,sources,search,scope):
    index=mentor_recovery.directory_index(root,cfg,sources,max_pages=2)
    search['directory_revision']=mentor_recovery.directory_revision(index)
    evidence={row['url']:row for row in index['evidence']}
    original_url=mentor_recovery.canonical(person['detail_url'])
    matches={row['url']:row for row in index['links'] if mentor_recovery.matches_name(row['name'],person['name'])}
    for row in index['rosters']:
        parent=evidence.get(row['url'])
        if (not parent or parent['sha256']!=row['sha256'] or
                not mentor_recovery.contact_allowed(mentor_recovery.contact_target(row['url'],cfg),scope,cfg)):continue
        _,html=sources.captured(parent)
        parsed,href=mentor_recovery.directory_fields(cfg,html,person['name'])
        if not parsed:continue
        anchored=(row['url']==original_url or mentor_recovery.roster_points_at(href,row['url'],original_url) or
                  mentor_recovery.identity(person,parsed,row['url'])=='name_and_email')
        if not anchored:continue
        if mentor_recovery.personal_email(parsed.get('email')):
            return {'email':parsed['email']},parent,'named_official_roster_row'
    if len(matches)<=8:
        for target,row in matches.items():
            parent=evidence.get(row['directory_url'])
            if (not parent or target==original_url or
                    not mentor_recovery.contact_allowed(mentor_recovery.contact_target(parent['url'],cfg),scope,cfg)):continue
            _,html=sources.captured(parent)
            if not mentor_recovery.named_link(html,parent['url'],target,person['name']):continue
            kind='registered_roster_link' if len(matches)==1 and parent['url']==original_url else 'directory'
            add_links(search,[dict(url=target,kind=kind)],parent,scope,cfg,1)
    search['directory']=bool(index['frontier'])
    return {},None,None


def secondary_hook_proof(person,parsed,captures,cfg=None):
    if (parsed.get('_verified_roster_name') or parsed.get('name'))!=person['name']:return None
    value=mentor_recovery.personal_email(parsed.get('email'))
    target=(parsed.get('_field_sources') or {}).get('email')
    if not value or target not in captures:return None
    locator=(parsed.get('_contact_locator') or {}).get('email') or {}
    parent=captures.get(locator.get('article_url'))
    if cfg and cfg.get('contact_hook_only'):
        if parsed.get('_verified_roster_name')!=person['name']:return None
        registered=person['detail_url']
        original_url=urlsplit(registered)
        https_hosts=(('ai.fudan.edu.cn','cs.fudan.edu.cn','faculty.fudan.edu.cn')
                     if cfg.get('school')=='fudan' and cfg.get('hook')=='fudan_cs' else
                     ('cs.ustc.edu.cn',) if cfg.get('school')=='ustc' and cfg.get('dept')=='cs' and cfg.get('hook')=='ustc_cs' else ())
        https_equivalent=(original_url.scheme=='http' and original_url.netloc in https_hosts and
                          target=='https:'+registered[5:] and captures[target]['url']==target)
        if target!=registered and not https_equivalent:
            roster=cfg.get('profile_field_roster') if cfg.get('hook')=='jlu_cs' else None
            named_roster=(roster and locator.get('directory_url')==target and
                           (target==roster or re.fullmatch(re.escape(roster.removesuffix('.htm'))+r'/\d+\.htm',target)))
            if not (parent and parent['url']==person['detail_url'] and
                    (mentor_recovery.profile_email_image(target,cfg) or named_roster)):return None
    return dict(captures[target],value=value,identity_basis='configured_official_contact_source',
                **({'locator':locator} if locator else {}),**({'linked_from':parent} if parent else {}))


def managed_email_rejection(person,parsed,captures,previous):
    url=person['detail_url']
    old=person['email']
    locator=(parsed.get('_contact_locator') or {}).get('email') or {}
    visible={value.casefold() for item in locator.get('visible_addresses',())
             if (value:=mentor_recovery.personal_email(item))}
    if (url not in captures or previous.get('source')!=url or parsed.get('_verified_roster_name')!=person['name']
            or (parsed.get('_field_sources') or {}).get('email')!=url or parsed.get('_rejected_email')!=old
            or locator.get('article_url')!=url or locator.get('rejected_mailto')!='mailto:'+old
            or len(visible)<2 or old.casefold() in visible):
        return None
    return dict(captures[url],value=old,locator=locator,previous_provenance=previous)


def linked_secondary_proof(person,cfg,hook,scope,sources,read_related,captures,review):
    """Rebuild the current named chain, checkpointing bounded work between runs."""
    frontier=review.setdefault('frontier',dict(queue=[],visited=[],proofs=[]))
    if not frontier['queue'] and not frontier['visited']:
        seeds=[dict(url=person['detail_url'],kind='secondary_root')]
        if cfg.get('profile_directory_format'):
            seeds.insert(0,dict(url=review['registration']['source'],kind='secondary_roster'))
        add_links(frontier,seeds,None,scope,cfg,0)
    for _ in range(3):
        if not frontier['queue']:break
        item=frontier['queue'][0];url=item['url']
        try:_,html=read_related(url)
        except Exception as error:
            if (item['kind']=='secondary_root' or
                    mentor_recovery.classify(str(error))['reason_code']!='http_not_found'):raise
            frontier['retired_source']=str(error)[:500]
            frontier['visited'].append(url);frontier['queue'].pop(0)
            continue
        parent=item['parent'];proof=None
        if parent:sources.captured(parent)
        if item['kind']=='secondary_roster':
            parsed,href=mentor_recovery.directory_fields(cfg,html,person['name'])
            if parsed and mentor_recovery.roster_points_at(href,url,mentor_recovery.canonical(person['detail_url'])):
                email=mentor_recovery.personal_email(parsed.get('email'))
                if email:proof=dict(captures[url],value=email,identity_basis='named_official_roster_row')
        else:
            heading=mentor_recovery.named_detail(html,person['name'])
            detail=mentor_recovery.contact_details(html,url,person['name'],verified=heading)
            if item['kind']=='secondary_root':
                try:parsed=hook.parse_detail(cfg,html,url) or {}
                except (mentor_recovery.DiscoveryBudgetExhausted,mentor_recovery.IdentityConflict):raise
                except Exception:parsed={}
                if parsed.get('name') and parsed['name']!=person['name']:
                    raise ValueError('详情明确姓名与原记录不符')
                proof=secondary_hook_proof(person,parsed,captures)
                if not detail['links']:
                    detail['links']=[dict(url=person[f],kind='registered') for f in ('homepage','profile_url')
                                     if mentor_recovery.homepage_url(person.get(f))]
            elif detail['email']:
                proof=dict(captures[url],value=detail['email'],identity_basis='official_person_link_and_named_section',
                           **({'linked_from':parent} if parent else {}))
            add_links(frontier,detail['links'],captures[url],scope,cfg,item['depth']+1)
        if proof and proof not in frontier['proofs']:frontier['proofs'].append(proof)
        frontier['visited'].append(url);frontier['queue'].pop(0)
    candidates={item['value'].casefold() for item in frontier['proofs']}
    if not frontier['queue'] and len(candidates)>1:
        raise ValueError('本人官方二级来源邮箱不一致，保留旧值待核对')
    if not frontier['queue'] and candidates:
        previous=review['registration']['source']
        return next((item for item in frontier['proofs'] if item['url']==previous),frontier['proofs'][0])
    if not frontier['queue'] and frontier.get('retired_source'):
        raise ValueError(frontier['retired_source'])
    return None


def attempt_secondary_email(person,file,cfg,hook,scope,sources,read_related,captures,review,signatures,owners,owner_lock,now):
    signature,versions=signatures;stamp=sources.stamp
    managed=cfg.get('contact_hook_only')
    previous=secondary_email_source(person,include_primary=bool(managed))
    if not previous or secondary_registration(person,previous)!=review['registration']:return person,None
    if review.get('parser_signature')!=signature or now-datetime.fromisoformat(review.get('started_at',stamp))>timedelta(days=1):
        for field in ('frontier','started_at','hook_captures'):review.pop(field,None)
    review.setdefault('started_at',stamp)
    review['parser_signature']=signature
    review.pop('changed_value',None)
    proof=None;reason='no_current_unique_email';message='当前官方二级资料未给出唯一的本人邮箱';hours=168
    try:
        if callable(getattr(hook,'parse_contact',None)):
            # Hide the old value only from the read-only extractor, never from
            # the identity/owner check or the record being written.
            query=deepcopy({key:value for key,value in person.items() if key!='email'})
            def previous_body():
                evidence=review.get('last_success') or {}
                if evidence.get('url')!=previous['source'] or evidence.get('value')!=person['email']:return None
                try:return sources.captured(evidence)[0]
                except (OSError,ValueError,KeyError):return None
            def read_hook(target):
                if not mentor_recovery.contact_allowed(mentor_recovery.contact_target(target,cfg),scope,cfg):
                    raise ValueError('字段来源离开已登记官方机构边界')
                evidence=(review.get('hook_captures') or {}).get(target)
                if evidence:
                    try:
                        raw,html=sources.captured(evidence)
                        captures[target]=evidence
                        return raw,'' if raw.startswith(b'%PDF-') else html
                    except (OSError,ValueError,KeyError):pass
                return read_related(target)
            context=dict(cfg,_previous_email=person['email'],_previous_email_source=previous['source'],
                         _read_previous_email_evidence=previous_body,_read_source=read_hook)
            parsed=hook.parse_contact(context,query) or {}
            proof=secondary_hook_proof(person,parsed,captures,cfg)
            if managed and not proof and (withdrawal:=managed_email_rejection(person,parsed,captures,previous)):
                sources.captured(withdrawal)
                updated=dict(person,provenance=dict(person['provenance']))
                updated.pop('email')
                updated['provenance'].pop('email')
                commit_contact_profile(file,person,updated,owners,owner_lock)
                return updated,dict(review,status='withdrawn',checked_at=stamp,changed_value=True,
                                    reason_code='inherited_template_mailto',withdrawal=withdrawal,
                                    next_check_at=(now+timedelta(days=30)).isoformat(timespec='seconds'))
        if not managed and not captures and not proof:
            proof=linked_secondary_proof(person,cfg,hook,scope,sources,read_related,captures,review)
        if not proof and (review.get('frontier') or {}).get('queue'):
            return person,dict(review,status='continuing',next_check_at=stamp)
        if proof:
            for evidence in (proof,proof.get('linked_from')):
                if not evidence:continue
                try:sources.captured(evidence)
                except (OSError,ValueError,KeyError) as error:
                    raise ValueError('二级邮箱证据原文缺失或SHA不符，需重新获取') from error
            value=proof['value']
            if managed and value.casefold()!=person['email'].casefold() and proof['url']!=previous['source']:
                raise ValueError('新旧官方邮箱来源不同，保留既有登记')
            day=datetime.fromisoformat(proof['fetched_at']).astimezone(LOCAL_ZONE).date().isoformat()
            provenance=dict(previous,source=proof['url'],fetched_at=day)
            updated=dict(person,email=value,provenance=dict(person['provenance'],email=provenance))
            commit_contact_profile(file,person,updated,owners,owner_lock,recheck=True)
            checked=dict(registration=secondary_registration(updated,provenance),status='verified',checked_at=stamp,
                         next_check_at=(now+SECONDARY_EMAIL_PERIOD).isoformat(timespec='seconds'),
                         last_success=proof,parser_signature=signature,changed_value=value!=person['email'])
            urls=[proof['url'],(proof.get('linked_from') or {}).get('url')]
            checked['directory_versions']={url:versions[url] for url in urls if url in versions}
            return updated,checked
    except mentor_recovery.DiscoveryBudgetExhausted:
        if not (review.get('frontier') or {}).get('visited'):
            if not captures:raise
            review['hook_captures']=dict(captures)
        return person,dict(review,status='continuing',next_check_at=stamp)
    except Exception as error:
        diagnosis=mentor_recovery.classify(str(error))
        reason=diagnosis['reason_code'];message=str(error)[:500];hours=diagnosis['retry_hours']
        if '其他导师记录' in message:reason='shared_contact'
        if '二级邮箱证据原文缺失' in message:reason='evidence_unavailable';hours=2
        if '核验期间导师记录已变化' in message:reason='registration_changed';hours=2
    finished=dict(review,status='waiting_source' if reason=='no_current_unique_email' else 'retry',reason_code=reason,reason=message,
                  checked_at=stamp,failed_since=review.get('failed_since') or stamp,
                  next_check_at=(now+timedelta(hours=hours)).isoformat(timespec='seconds'))
    if reason not in ('network_timeout','rate_limited','server_error'):
        finished.pop('frontier',None);finished.pop('started_at',None)
    finished.pop('hook_captures',None)
    urls=set(review.get('directory_versions',{}))|{review['registration']['source']}
    finished['directory_versions']={url:versions[url] for url in urls if url in versions}
    return person,finished


def process_record(root,record,cfg,sources,legacy,now,directory_revision,ledger,hook,signature,versions,owners,owner_lock):
    from crawler import legacy_refresh,mentor_quality
    stamp=sources.stamp
    file=root/'data/professors'/record['unit']/(record['ref']+'.yaml')
    original=person=mentor_quality.load_yaml(file)
    scope=cfg.get('base_url') or original['detail_url']
    managed_email=cfg.get('contact_hook_only')
    search_fields=('homepage',) if managed_email else CONTACT_FIELDS
    generic_fields=tuple(field for field in search_fields if field!='homepage' or not cfg.get('homepage_hook_only'))
    report=dict(id=record['id'],status='checked',reused_evidence=False,filled_fields=[],changed_fields=[],field_evidence={})
    search=deepcopy(record.get('contact_search') or {})
    if search.get('signature')!=signature or not search.get('next_at'):
        search=dict(signature=signature,queue=[],visited=[],directory=False,next_at=None,directory_revision=directory_revision)
    if cfg.get('homepage_hook_only'):
        search['queue']=[item for item in search['queue'] if
                         item['kind']!='homepage_check' or item.get('identity_basis')=='configured_official_contact_source']
        if not any(needs_contact(person,field) for field in generic_fields):
            search['queue']=[item for item in search['queue'] if item['kind']=='homepage_check']
            search['directory']=False
            if not search['queue']:search['next_at']=None
    resume=bool(search['next_at'] and search['next_at']<=stamp and any(needs_contact(person,f) for f in search_fields))
    due_other=any(f not in CONTACT_FIELDS and v.get('status') not in ('resolved','manual_review') and
                  (not v.get('next_check_at') or v['next_check_at']<=stamp or v.get('parser_signature')!=signature)
                  for f,v in record['fields'].items())

    def write(new,changed,evidence,basis,parent=None):
        nonlocal person
        commit_contact_profile(file,person,new,owners,owner_lock)
        for field in CONTACT_FIELDS:
            if needs_contact(person,field) and present(new,field):
                report['field_evidence'][field]=dict(evidence,value=new[field],identity_basis=basis,
                                                     **({'linked_from':parent} if parent else {}))
        person=new
        report['changed_fields'].extend(changed)

    def save_contact(values,evidence,basis,parent=None):
        day=datetime.fromisoformat(evidence['fetched_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()
        new=dict(person,provenance=dict(person.get('provenance',{})))
        for field in CONTACT_FIELDS if basis=='configured_official_contact_source' else generic_fields:
            if needs_contact(person,field) and values.get(field):
                new[field]=values[field]
                new['provenance'][field]=dict(origin='crawled',source=evidence['url'],fetched_at=day,confidence='auto')
        changed=[field for field in CONTACT_FIELDS if new.get(field)!=person.get(field)]
        write(new,changed,evidence,basis,parent)
        observation(root,person,parsed={**{f:values[f] for f in changed},'_field_scope':person['name']},source_url=evidence['url'],
                    source_sha256=evidence['sha256'],fetched_at=evidence['fetched_at'],now=now,parser_signature=signature,contact_only=True,ledger=ledger)

    def homepage_candidate(value,evidence,basis,depth):
        if cfg.get('homepage_hook_only') and basis!='configured_official_contact_source':return
        if not needs_contact(person,'homepage') or not value or not evidence:return
        if mentor_recovery.canonical(value)==mentor_recovery.canonical(person['detail_url']):return
        if not mentor_recovery.homepage_scope(value,scope):
            search['external_homepage_candidate']=dict(url=value,declared_at=evidence,next_review_at=(now+timedelta(days=30)).isoformat(timespec='seconds'))
            return
        add_links(search,[dict(url=value,kind='homepage_check',value=value,identity_basis=basis)],evidence,scope,cfg,depth)
        if search['queue'] and not search['next_at']:search['next_at']=stamp

    captures={}
    def read_related(target):
        if not mentor_recovery.contact_allowed(mentor_recovery.contact_target(target,cfg),scope,cfg):
            raise ValueError('字段来源离开已登记官方机构边界')
        contact_cfg=cfg if mentor_recovery.profile_email_image(target,cfg) else None
        body,text=sources.read(target,official_scope=scope,contact_cfg=contact_cfg)
        captures[target]=sources.capture(target,body,stamp)
        return body,text
    parsed_cfg=dict(cfg,_expected_name=original['name'],_read_source=read_related,_original_profile=original)

    review=record.get('secondary_email')
    reviewing=secondary_due(review,signature,stamp,versions)
    if reviewing:
        person,checked=attempt_secondary_email(person,file,parsed_cfg,hook,scope,sources,read_related,captures,deepcopy(review),
                                               (signature,versions),owners,owner_lock,now)
        if checked:
            report['secondary_email']=checked
            ledger['records'][record['id']]['secondary_email']=checked
            ledger['records'][record['id']]['updated_at']=stamp
            if checked['status']=='verified':
                proof=checked['last_success']
                observation(root,person,parsed={'email':person['email']},source_url=proof['url'],source_sha256=proof['sha256'],
                            fetched_at=proof['fetched_at'],now=now,parser_signature=signature,contact_only=True,ledger=ledger)
                if checked['changed_value']:report['changed_fields'].append('email')
            elif checked['status']=='withdrawn':
                proof=checked['withdrawal']
                observation(root,person,parsed={'_rejected_email':proof['value']},source_url=proof['url'],
                            source_sha256=proof['sha256'],fetched_at=proof['fetched_at'],now=now,
                            parser_signature=signature,contact_only=True,ledger=ledger)
                email_state=ledger['records'][record['id']]['fields']['email']
                email_state.update(withdrawal=proof,status='waiting_source',next_action='wait_for_source_update',
                                   next_check_at=checked['next_check_at'])
                report['changed_fields'].append('email')
        if not due(record,cfg,root,stamp,directory_revision,parser_signature=signature):return report

    if not reviewing and getattr(hook,'parse_contact',None) and any(needs_contact(person,f) for f in CONTACT_FIELDS):
        try:
            supplemental=hook.parse_contact(parsed_cfg,person) or {}
            if (supplemental.get('_verified_roster_name') or supplemental.get('name'))==person['name']:
                for field,validate in (('email',mentor_recovery.personal_email),('homepage',mentor_recovery.homepage_url)):
                    target=(supplemental.get('_field_sources') or {}).get(field)
                    value=validate(supplemental.get(field))
                    if managed_email and field=='email' and not secondary_hook_proof(person,supplemental,captures,cfg):
                        continue
                    if target in captures and value and needs_contact(person,field):
                        locator=(supplemental.get('_contact_locator') or {}).get(field)
                        parent=captures.get((locator or {}).get('article_url'))
                        evidence=dict(captures[target],**({'locator':locator} if locator else {}))
                        if field=='homepage':homepage_candidate(value,evidence,'configured_official_contact_source',1)
                        else:save_contact({field:value},evidence,'configured_official_contact_source',parent)
        except mentor_recovery.DiscoveryBudgetExhausted:
            if not resume:raise
        except Exception as failure:
            report.setdefault('source_errors',[]).append(str(failure)[:300])

    if not resume or due_other:
        url=original['detail_url'];raw=None;fetched_at=None;evidence=None;parsed={};contact={};error=None
        primary=mentor_recovery.contact_target(url,cfg)
        try:
            if not mentor_recovery.contact_allowed(primary,scope,cfg):
                raise ValueError('字段来源离开已登记官方机构边界')
            raw,fetched_at=cached_detail(root,original,record,legacy,now)
            report['reused_evidence']=raw is not None
            if raw is None:raw,_=sources.read(primary,official_scope=scope);fetched_at=stamp
            evidence=sources.capture(url,raw,fetched_at)
            html=UnicodeDammit(raw).unicode_markup or ''
            try:
                parsed=hook.parse_detail(parsed_cfg,html,url)
                parsed=legacy_refresh.ordinary_profile_fields(cfg,parsed)
            except (mentor_recovery.DiscoveryBudgetExhausted,mentor_recovery.IdentityConflict):
                raise
            except Exception as parse_error:
                error=parse_error
            if parsed.get('name') and ''.join(parsed['name'].split())!=''.join(original['name'].split()):
                raise mentor_recovery.IdentityConflict('详情明确姓名与原记录不符，保留旧记录')
            strong_name=(parsed.get('name')==original['name'] or mentor_recovery.named_detail(html,original['name']))
            if strong_name and (not parsed.get('name') or parsed['name']==original['name']):
                contact=mentor_recovery.contact_details(html,url,original['name'],verified=True)
            if cfg.get('roster_only') and not strong_name:
                raise ValueError('尚无本人详情来源：当前仅有名册登记')
            contact_owner=strong_name or parsed.get('_verified_roster_name')==original['name']
            for field,validate in (('email',mentor_recovery.personal_email),('homepage',mentor_recovery.homepage_url)):
                value=(validate(parsed.get(field)) or contact.get(field)) if field in generic_fields and contact_owner and needs_contact(person,field) else None
                if value:parsed[field]=value
                else:parsed.pop(field,None)
            if homepage:=parsed.pop('homepage',None):
                target=(parsed.get('_field_sources') or {}).get('homepage')
                homepage_candidate(homepage,captures.get(target) if target else evidence,'registered_official_detail',1)
            if present(person,'email'):parsed.pop('_rejected_email',None)
            if parsed.get('email') or parsed.get('homepage'):error=None
            day=datetime.fromisoformat(fetched_at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
            proposed={field:parsed[field] for field in FIELDS if parsed.get(field) and not present(person,field)
                      and (person.get('provenance',{}).get(field) or {}).get('origin')!='manual'}
            if not present(person,'research_direction_raw') and parsed.get('research_directions'):
                proposed['research_directions']=parsed['research_directions']
            updated,changed=person,[]
            if proposed:
                for key in ('name','_verified_roster_name','_field_sources'):
                    if key in parsed:proposed[key]=parsed[key]
                updated,changed,_=legacy_refresh.merge_profile(person,proposed,raw,day,verified_sources=captures.values())
                # Keep already stored values and dates on a gap-only recheck.
                updated['last_parsed']=now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            elif not strong_name and not parsed:
                raise error or ValueError('未解析出可用详情字段，保留旧记录')
            subsource={}
            for field,target in (parsed.get('_field_sources') or {}).items():
                if field in CONTACT_FIELDS and field in changed and target in captures:
                    subsource[field]=captures[target]
            write(updated,changed,evidence,'registered_official_detail')
            for field,capture in subsource.items():
                if field in report['field_evidence']:
                    report['field_evidence'][field].update(capture,linked_from=evidence)
                    observation(root,person,parsed={field:updated[field]},source_url=capture['url'],source_sha256=capture['sha256'],
                                fetched_at=capture['fetched_at'],now=now,parser_signature=signature,contact_only=True,ledger=ledger)
                    parsed.pop(field,None)
        except mentor_recovery.DiscoveryBudgetExhausted:
            if not resume and not report['field_evidence'] and not report.get('secondary_email') and not search.get('external_homepage_candidate') and not search['queue']:raise
        except Exception as failure:
            error=failure
        identity_conflict=isinstance(error,mentor_recovery.IdentityConflict)
        if identity_conflict:
            search.update(queue=[],directory=False,next_at=None)
            search.pop('external_homepage_candidate',None)
        if not identity_conflict and not resume and not record.get('contact_search',{}).get('next_at') and any(needs_contact(person,f) for f in generic_fields):
            search['visited']=[primary]
            registered=[dict(url=person[f],kind='registered') for f in ('homepage','profile_url') if mentor_recovery.homepage_url(person.get(f))]
            add_links(search,registered+(contact.get('links') or []),evidence,scope,cfg,1)
            search['directory']=bool(cfg.get('list') or cfg.get('profile_directory_format'))
            search['next_at']=stamp if search['queue'] else (now+timedelta(days=1)).isoformat(timespec='seconds') if search['directory'] else None
        observation(root,person,parsed=parsed,source_url=url,source_sha256=evidence['sha256'] if evidence else None,
                    fetched_at=fetched_at,now=now,error=error,parser_signature=signature,contact_search=search,ledger=ledger,
                    verified_sources=captures.values())
        if error and (identity_conflict or not report['field_evidence']):report.update(status='error',reason=str(error)[:500])
        if evidence:report.update(source_sha256=evidence['sha256'],fetched_at=evidence['fetched_at'])

    steps=0
    while search['next_at'] and search['next_at']<=stamp and any(needs_contact(person,f) for f in search_fields) and steps<3:
        steps+=1
        try:
            if not search['queue']:
                if not search['directory']:break
                values,evidence,basis=directory_contacts(root,person,cfg,sources,search,scope)
                if values:save_contact(values,evidence,basis)
                if not search['queue']:
                    search['next_at']=(now+timedelta(hours=1)).isoformat(timespec='seconds') if search['directory'] else None
                    break
                continue
            item=search['queue'][0];url=item['url'];parent=item['parent']
            parent_html=''
            if parent:
                if not mentor_recovery.contact_allowed(mentor_recovery.contact_target(parent['url'],cfg),scope,cfg):
                    raise ValueError('来源证据离开已登记官方机构边界')
                _,parent_html=sources.captured(parent)
            request_scope=mentor_recovery.homepage_scope(url,scope) if item['kind']=='homepage_check' else scope
            if not request_scope:raise ValueError('个人主页来源离开已登记官方关系')
            if request_scope!=scope and not mentor_recovery.hosted_homepage_link(parent_html,person['name'],url,scope):
                raise ValueError('托管主页缺少本人官方页面的明确链接')
            raw,html=sources.read(url,official_scope=request_scope,homepage_target=item['kind']=='homepage_check')
            evidence=sources.capture(url,raw,stamp)
            heading=mentor_recovery.named_detail(html,person['name'])
            detail=mentor_recovery.contact_details(html,url,person['name'],verified=heading and item['kind'] in ('registered','registered_roster_link'))
            basis=None
            if item['kind']=='homepage_check':
                if mentor_recovery.linked_homepage_identity(html,person['name'],person.get('aliases') or (),url=url,scope=scope):
                    basis='official_person_link_and_named_section'
                    save_contact({'homepage':item['value']},parent,item['identity_basis'])
                    if 'homepage' in report['field_evidence']:report['field_evidence']['homepage']['target_evidence']=evidence
            elif item['kind']=='directory':
                try:
                    parsed=hook.parse_detail(parsed_cfg,html,url)
                except (mentor_recovery.DiscoveryBudgetExhausted,mentor_recovery.IdentityConflict):
                    raise
                except Exception:
                    parsed={}
                if heading:parsed.setdefault('name',person['name'])
                basis=mentor_recovery.identity(person,parsed,url)
                if basis:
                    detail=mentor_recovery.contact_details(html,url,person['name'],verified=True)
                    detail['email']=mentor_recovery.personal_email(parsed.get('email')) or detail['email']
                    detail['homepage']=mentor_recovery.homepage_url(parsed.get('homepage')) or detail['homepage']
            elif heading or detail['email'] or detail['homepage']:
                basis={'registered':'registered_person_link','registered_roster_link':'registered_roster_and_named_detail',
                       'linked':'official_person_link_and_named_section','linked_contact':'official_contact_link_and_named_section'}[item['kind']]
            if basis:
                homepage_candidate(detail.pop('homepage',None),evidence,basis,item['depth']+1)
                save_contact(detail,evidence,basis,parent)
                if any(needs_contact(person,f) for f in generic_fields):
                    add_links(search,detail['links'],evidence,scope,cfg,item['depth']+1)
            search['visited'].append(url);search['queue'].pop(0)
        except mentor_recovery.DiscoveryBudgetExhausted:
            break
        except Exception as failure:
            report.setdefault('source_errors',[]).append(str(failure)[:300])
            diagnosis=mentor_recovery.classify(str(failure))
            if diagnosis['reason_code'] in ('rate_limited','network_timeout','server_error'):
                search['next_at']=(now+timedelta(hours=diagnosis['retry_hours'])).isoformat(timespec='seconds')
                break
            if search['queue']:
                search['visited'].append(search['queue'].pop(0)['url'])
            else:
                search['next_at']=(now+timedelta(hours=24)).isoformat(timespec='seconds')
                break
        if not search['queue']:
            search['next_at']=(now+timedelta(days=1)).isoformat(timespec='seconds') if search['directory'] else None
    if not any(needs_contact(person,f) for f in search_fields):
        search['next_at']=None
    if resume or search['visited'] or search['queue'] or search.get('external_homepage_candidate'):
        observation(root,person,now=now,parser_signature=signature,contact_search=search,ledger_only=True,ledger=ledger)
    report['filled_fields']=[field for field in FIELDS if not present(original,field) and present(person,field)]
    report['changed_fields']=list(dict.fromkeys(report['changed_fields']))
    report['next_contact_source']=search['queue'][0]['url'] if search['queue'] else None
    return report


def run(root,*,limit=6,request_budget=12,domain_budget=8,workers=4,units=(),fetcher=None,now=None):
    """Advance contact sources in parallel across institutions with shared request limits."""
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds')
    with output_lock(root/'cache/mentor_quality/field-refresh.json'):
        return run_locked(root,limit,request_budget,domain_budget,workers,units,fetcher,now,stamp)


def run_locked(root,limit,request_budget,domain_budget,workers,units,fetcher,now,stamp):
    from crawler import legacy_refresh,mentor_quality
    from crawler.source_discovery import boundary,fetch_html
    owners={};owner_lock=Lock();state=seed(root,now,email_owners=owners)
    report_path=root/'cache/mentor_quality/field-refresh.json'
    previous=json.loads(report_path.read_text(encoding='utf8')) if report_path.exists() else {}
    cooldowns={domain:until for domain,until in previous.get('domain_cooldowns',{}).items() if until>stamp}
    legacy_path=root/'cache/legacy_refresh/state.json'
    legacy=json.loads(legacy_path.read_text(encoding='utf8')).get('records',{}) if legacy_path.exists() else {}
    configs={};revisions={};versions={};signatures={};candidates=[]
    for key,record in state['records'].items():
        if units and record['unit'] not in units:continue
        if record['unit'] not in configs:
            config_path=root/'sites'/(record['unit']+'.yaml')
            if not config_path.exists():continue
            configs[record['unit']]=mentor_quality.load_yaml(config_path)
            signatures[record['unit']]=mentor_recovery.signature(root,configs[record['unit']])
            index_path=root/'cache/mentor_quality/discovery'/(record['unit'].replace('/','-')+'.json')
            index=json.loads(index_path.read_text(encoding='utf8')) if index_path.exists() else {}
            revisions[record['unit']]=mentor_recovery.directory_revision(index)
            versions[record['unit']]={item['url']:item['sha256'] for item in index.get('evidence',[]) if item.get('sha256')}
        cfg=configs[record['unit']]
        signature=signatures[record['unit']]
        review=record.get('secondary_email')
        reviewing=secondary_due(review,signature,stamp,versions[record['unit']])
        if not reviewing and not due(record,cfg,root,stamp,revisions[record['unit']],parser_signature=signature):continue
        latest=(review.get('checked_at') or review['next_check_at']) if reviewing else max((field.get('checked_at','') for field in record['fields'].values()),default='')
        follow=(record.get('contact_search') or {}).get('next_at')
        email=record['fields'].get('email',{})
        email_open=email.get('status') not in (None,'resolved') and email.get('reason_code')!='manual_field'
        source_missing=any(v.get('reason_code') in ('source_missing','directory_only','template_empty') for v in record['fields'].values())
        candidates.append(((not bool(reviewing or follow and follow<=stamp),not email_open,not source_missing,latest,key),key,record,cfg))
    domains={};used=Counter();budget_lock=Lock()
    for row in sorted(candidates,key=lambda row:row[0]):
        cfg=row[3]
        try:domain=boundary(cfg['base_url'])
        except (ValueError,KeyError):domain=cfg['school']
        if domain not in cooldowns:domains.setdefault(domain,[]).append(row)
    groups={domain:[] for domain in domains}
    while limit>0 and any(domains.values()):
        for domain,rows in domains.items():
            if rows and limit>0:groups[domain].append(rows.pop(0));limit-=1
    working={'records':{row[1]:deepcopy(row[2]) for rows in groups.values() for row in rows}}

    def process_domain(job):
        domain,rows=job
        results=[]
        blocked_until=None
        active_cfg={}
        def count_request():
            with budget_lock:
                if used.total()>=request_budget or used[domain]>=domain_budget:
                    raise mentor_recovery.DiscoveryBudgetExhausted('字段补齐本轮请求预算已用完')
                used[domain]+=1
        def bounded(source):
            nonlocal blocked_until
            homepage=source.get('homepage_target')
            url=source['url'] if homepage else mentor_recovery.contact_target(source['url'],active_cfg)
            scope=source.get('official_scope') or url
            if not (mentor_recovery.same_scope(url,scope) if homepage else mentor_recovery.contact_allowed(url,scope,active_cfg)):
                raise ValueError('字段来源离开已登记官方机构边界')
            if blocked_until:raise mentor_recovery.DiscoveryBudgetExhausted('官方域名进入冷却')
            try:
                if fetcher:count_request();return fetcher(dict(source,url=url,official_scope=scope))
                pdf=mentor_recovery.profile_pdf(url,active_cfg)
                png=source.get('official_contact_png') and mentor_recovery.profile_email_image(url,active_cfg)
                types=('image/png',) if png else ('application/pdf',) if pdf else mentor_recovery.content_types(url)
                return fetch_html(url,scope,before_request=count_request,allow_pdf=pdf,accepted_types=types,
                                  **({'allow_contact_png':True} if png else {}))
            except Exception as error:
                if mentor_recovery.classify(str(error))['reason_code']=='rate_limited':
                    blocked_until=(now+timedelta(hours=24)).isoformat(timespec='seconds')
                raise
        sources=mentor_quality.Sources(root,bounded,stamp)
        hooks={}
        for _,key,record,cfg in rows:
            try:
                active_cfg=cfg
                old=legacy.get('professor/'+record['unit']+'/'+record['ref']+'.yaml',{})
                if record['unit'] not in hooks:hooks[record['unit']]=legacy_refresh.load_hook(root,cfg)
                unit=record['unit']
                results.append(process_record(root,record,cfg,sources,old,now,revisions[unit],working,hooks[unit],
                                              signatures[unit],versions[unit],owners,owner_lock))
            except mentor_recovery.DiscoveryBudgetExhausted:
                break
            except Exception as error:
                results.append(dict(id=key,status='error',reason=str(error)[:500],filled_fields=[],reused_evidence=False))
        return results,blocked_until

    results=[]
    with ThreadPoolExecutor(max_workers=max(1,workers)) as pool:
        jobs=[(domain,rows) for domain,rows in groups.items() if rows and domain not in cooldowns]
        for (domain,_),(rows,blocked_until) in zip(jobs,pool.map(process_domain,jobs)):
            results.extend(rows)
            if blocked_until:cooldowns[domain]=blocked_until
    path=root/PATH
    with LEDGER_LOCK,output_lock(path):
        current=read(root)
        for key,updated in working['records'].items():
            before=state['records'][key]
            if updated==before:continue
            row=current['records'].setdefault(key,before)
            for field,value in updated['fields'].items():
                if value!=before['fields'].get(field) and row['fields'].get(field)==before['fields'].get(field):
                    row['fields'][field]=value
            if row.get('contact_search')==before.get('contact_search') and 'contact_search' in updated:
                row['contact_search']=updated['contact_search']
            if row.get('secondary_email')==before.get('secondary_email') and 'secondary_email' in updated:
                row['secondary_email']=updated['secondary_email']
            row['updated_at']=max(row.get('updated_at',''),updated['updated_at'])
        current['summary']=summarize(current)
        atomic_json(path,current)
    secondary=Counter(row['secondary_email']['status'] for row in results if row.get('secondary_email'))
    report=dict(checked_at=stamp,attempted=len(results),requests=used.total(),request_budget=request_budget,
                domain_budget=domain_budget,requests_by_domain=dict(used),domain_cooldowns=cooldowns,
                reused=sum(row['reused_evidence'] for row in results),filled_fields=sum(len(row['filled_fields']) for row in results),
                filled_profiles=sum(bool(row['filled_fields']) for row in results),errors=sum(row['status']=='error' for row in results),
                secondary_email=dict(secondary),sources_error=secondary['retry']+secondary['waiting_source'],
                summary=current['summary'],results=results)
    atomic_json(root/'cache/mentor_quality/field-refresh.json',report)
    return report
