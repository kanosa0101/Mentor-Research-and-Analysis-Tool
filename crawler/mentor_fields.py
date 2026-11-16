"""Field-level public mentor gaps; absence is not a network or identity failure."""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path

from bs4 import UnicodeDammit

from crawler.opportunity_monitor import atomic_json,output_lock
from crawler.public_discovery import research_text,title_group,valid_email
from sites.profile_fields import direction_is_mixed

FIELDS=('email','research_direction_raw','supervisor','title')
LABELS={'email':'本人邮箱','research_direction_raw':'研究方向','supervisor':'招生资格','title':'职称'}
PATH='cache/mentor_quality/field-gaps.json'


def present(person,field):
    value=person.get(field)
    if field=='email':return valid_email(value)
    if field=='research_direction_raw':return bool(research_text(value)) and not direction_is_mixed(value)
    if field=='title':return title_group(value)!='unknown'
    return bool(re.search(r'博|硕',value or '') and not re.search(r'无|非|不|未具备',value or ''))


def identifier(person):
    return person['school']+'/'+person['dept']+'/'+person['slug']


def read(root):
    path=Path(root)/PATH
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {'version':1,'records':{}}


def summarize(state):
    active=[(record,field,value) for record in state['records'].values() for field,value in record['fields'].items() if value.get('status')!='resolved']
    return dict(profiles=len({record['id'] for record,_,_ in active}),fields=len(active),
                by_field=dict(Counter(field for _,field,_ in active)),by_reason=dict(Counter(v['reason_code'] for _,_,v in active)),
                by_status=dict(Counter(v['status'] for _,_,v in active)),by_unit=dict(Counter(record['unit'] for record,_,_ in active)))


def seed(root,now=None):
    """Inventory missing/contaminated fields without making a network request."""
    from crawler.mentor_quality import load_yaml
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds');path=root/PATH
    with output_lock(path):
        state=read(root)
        for file in sorted((root/'data/professors').glob('*/*/*.yaml')):
            person=load_yaml(file);key=identifier(person);record=state['records'].get(key)
            gaps=[field for field in FIELDS if not present(person,field)]
            if not gaps and record is None:continue
            if record is None:
                record=dict(id=key,unit=person['school']+'/'+person['dept'],ref=person['slug'],name=person['name'],first_seen=stamp,fields={})
                state['records'][key]=record
            for field in FIELDS:
                prior=record['fields'].get(field)
                if field not in gaps:
                    if prior and prior.get('status')!='resolved':
                        prior.update(status='resolved',reason_code='record_now_complete',reason='当前登记已有该字段；沿用其实际来源日期',resolved_at=stamp,
                                     pending_since=None,source_url=(person.get('provenance',{}).get(field) or {}).get('source'),next_action='none',next_check_at=None)
                    continue
                if prior and prior.get('status')!='resolved':continue
                manual=(person.get('provenance',{}).get(field) or {}).get('origin')=='manual'
                mixed=field=='research_direction_raw' and direction_is_mixed(person.get(field))
                code='manual_field' if manual else 'content_mixed' if mixed else 'not_checked'
                record['fields'][field]=dict(first_seen=(prior or {}).get('first_seen',stamp),pending_since=stamp,
                    status='manual_review' if manual else 'pending',reason_code=code,reason='人工字段保留，需本人维护确认' if manual else '方向混有项目或履历，需从本人原文提取' if mixed else '当前缺少'+LABELS[field]+'，等待核验本人官方资料',
                    next_action='manual_review' if manual else 'verify_field',source_url=person['detail_url'],next_check_at=None if manual else stamp)
            record['updated_at']=stamp
        state['scanned_at']=stamp;state['summary']=summarize(state);atomic_json(path,state)
    return state


def observation(root,person,*,parsed=None,body=None,source_sha256=None,fetched_at=None,now=None,error=None,parser_signature=None):
    """Record what a verified personal source did/did not disclose, per field."""
    from crawler import mentor_recovery
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds');path=root/PATH;key=identifier(person)
    parsed=parsed or {};scope=parsed.get('_field_scope') or parsed.get('bio_raw') or ''
    with output_lock(path):
        state=read(root);record=state['records'].get(key)
        gaps=[field for field in FIELDS if not present(person,field)]
        if record is None and not gaps:return
        if record is None:record=dict(id=key,unit=person['school']+'/'+person['dept'],ref=person['slug'],name=person['name'],first_seen=stamp,fields={});state['records'][key]=record
        for field in set(gaps)|set(record['fields']):
            prior=record['fields'].get(field,{})
            value=dict(prior,first_seen=prior.get('first_seen',stamp),checked_at=stamp,source_url=person['detail_url'])
            if source_sha256:value.update(source_sha256=source_sha256,fetched_at=fetched_at)
            if parser_signature:value['parser_signature']=parser_signature
            if present(person,field):
                verified=bool(parsed.get(field)) and not error
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
                    marker={'email':r'邮箱|电子邮件|e-?mail|@','research_direction_raw':r'研究方向|研究领域|研究兴趣|主要从事|research interests?',
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
        record['updated_at']=stamp;state['summary']=summarize(state);atomic_json(path,state)


def due(record,cfg,root,stamp):
    from crawler.mentor_recovery import signature
    current=signature(root,cfg)
    return any(value.get('status') not in ('resolved','manual_review') and
               (not value.get('next_check_at') or value['next_check_at']<=stamp or value.get('parser_signature')!=current)
               for value in record['fields'].values())


def run(root,*,limit=6,request_budget=12,units=(),fetcher=None,now=None):
    """Bounded gap refresh, reusing recent captured official responses first."""
    from crawler import legacy_refresh,mentor_quality,mentor_recovery
    from crawler.source_discovery import fetch_html
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds');state=seed(root,now)
    legacy_path=root/'cache/legacy_refresh/state.json'
    legacy=json.loads(legacy_path.read_text(encoding='utf8')).get('records',{}) if legacy_path.exists() else {}
    configs={};candidates=[]
    for key,record in state['records'].items():
        if units and record['unit'] not in units:continue
        if record['unit'] not in configs:
            config_path=root/'sites'/(record['unit']+'.yaml')
            if not config_path.exists():continue
            configs[record['unit']]=mentor_quality.load_yaml(config_path)
        cfg=configs[record['unit']]
        if not due(record,cfg,root,stamp):continue
        latest=max((field.get('checked_at','') for field in record['fields'].values()),default='')
        candidates.append((latest,key,record,cfg))
    candidates.sort(key=lambda row:row[:2]);used=0;results=[]
    def count_request():
        nonlocal used
        if used>=request_budget:raise mentor_recovery.DiscoveryBudgetExhausted('字段补齐本轮请求预算已用完')
        used+=1
    def bounded(source):
        if fetcher:count_request();return fetcher(source)
        url=mentor_recovery.canonical(source['url']);scope=source.get('official_scope') or url
        return fetch_html(url,scope,before_request=count_request,accepted_types=mentor_recovery.content_types(url))
    for _,key,record,cfg in candidates[:limit]:
        file=root/'data/professors'/record['unit']/(record['ref']+'.yaml');original=mentor_quality.load_yaml(file)
        old=legacy.get('professor/'+record['unit']+'/'+file.name,{})
        cached=False;raw=None;parsed={};fetched_at=None;sources=mentor_quality.Sources(root,bounded,stamp)
        signature=mentor_recovery.signature(root,cfg)
        try:
            if cfg.get('roster_only'):raise ValueError('尚无本人详情来源：当前仅有名册登记')
            evidence_rows=[(old.get('last_success'),old.get('source_url'),old.get('raw_sha256'),'legacy_refresh')] if old.get('status')=='ok' else []
            evidence_rows += [(v.get('fetched_at'),v.get('source_url'),v.get('source_sha256'),'mentor_quality') for v in record['fields'].values()]
            for prior,url,digest,folder in sorted(evidence_rows,key=lambda row:row[0] or '',reverse=True):
                moment=datetime.fromisoformat(prior) if prior else None
                if url!=original['detail_url'] or not moment or not timedelta(0)<=now-moment<=timedelta(days=1):continue
                evidence=root/'cache'/folder/'evidence'/((digest or '')+'.body')
                if evidence.is_file():
                    raw=evidence.read_bytes()
                    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('缓存原文SHA不一致，未复用')
                    cached=True;fetched_at=prior;break
            if raw is None:
                raw,_=sources.read(original['detail_url'],official_scope=cfg.get('base_url') or original['detail_url']);fetched_at=stamp
            html=UnicodeDammit(raw).unicode_markup or ''
            hook=legacy_refresh.load_hook(root,cfg)
            parsed=hook.parse_detail(dict(cfg,_expected_name=original['name'],_read_source=lambda url:sources.read(url,official_scope=cfg.get('base_url') or original['detail_url'])),html,original['detail_url'])
            day=datetime.fromisoformat(fetched_at).astimezone(timezone(timedelta(hours=8))).date().isoformat()
            updated,changed,checked=legacy_refresh.merge_profile(original,parsed,raw,day)
            updated['last_parsed']=now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            mentor_quality.write_profile(file,original,updated)
            digest=hashlib.sha256(raw).hexdigest()
            observation(root,updated,parsed=parsed,body=raw,source_sha256=digest,fetched_at=fetched_at,now=now,parser_signature=signature)
            filled=[field for field in FIELDS if not present(original,field) and present(updated,field)]
            results.append(dict(id=key,status='checked',reused_evidence=cached,filled_fields=filled,changed_fields=changed,source_sha256=digest,fetched_at=fetched_at))
        except mentor_recovery.DiscoveryBudgetExhausted:
            break
        except Exception as error:
            observation(root,original,parsed=parsed,body=raw,source_sha256=hashlib.sha256(raw).hexdigest() if raw else None,fetched_at=fetched_at,now=now,error=error,parser_signature=signature)
            results.append(dict(id=key,status='error',reason=str(error)[:500],reused_evidence=cached,filled_fields=[]))
    report=dict(checked_at=stamp,attempted=len(results),requests=used,request_budget=request_budget,reused=sum(row['reused_evidence'] for row in results),
                filled_fields=sum(len(row['filled_fields']) for row in results),filled_profiles=sum(bool(row['filled_fields']) for row in results),
                errors=sum(row['status']=='error' for row in results),summary=read(root).get('summary',{}),results=results)
    atomic_json(root/'cache/mentor_quality/field-refresh.json',report)
    return report
