"""Append new official admissions policies after complete evidence and AI checks.

Existing policies are never rewritten here. Unclear scope, changed versions and
unsupported documents remain explicit queue records, not published summaries.
"""
import copy
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml

from crawler import admissions_util, ai_review, automatic_evidence, notice_util, opportunity_attachments
from crawler import opportunity_extract as extract, opportunity_review as review, policy_revalidation
from crawler.legacy_refresh import write_yaml
from crawler.opportunity_monitor import atomic_json, output_lock

VERSION = 'new-official-policy-v7-context-and-scope'
CST = timezone(timedelta(hours=8))
HEADINGS = {
    'eligibility': ('申请条件', '报考条件', '报名条件', '申请资格', '招生对象', '基本条件', '报名基本条件'),
    'materials': ('申请材料', '报名材料', '提交材料', '材料要求', '提交申请材料清单', '提交报名材料'),
    'application_method': ('申请方式', '报名方式', '报名程序', '报名流程', '申请流程', '报名办法', '报名申请', '网上报名'),
    'timeline': ('报名时间', '申请时间', '受理时间', '网报时间'),
    'contact': ('联系方式', '咨询方式', '联系咨询', '招生咨询'),
    'exams': ('选拔方式', '考核方式', '考核程序', '考核与评价', '录取', '思想政治素质和品德考核', '体检',
              '违规处理', '诚信要求', '信息公开与监督机制'),
    'tuition': ('学费与学制', '学制与学费', '奖学金', '奖助金', '其它事项', '其他事项'),
    'quota': ('招生人数及专业方向', '招生规模', '招生计划'),
}


def reason_code(reason, status):
    if status == 'budget_wait':
        return 'ai_budget_wait'
    if reason in ('公告为已结束招生周期，不新增为当前政策', '申请窗口已过，不作为当前新政策自动入库', '已到具体申请截止时点'):
        return 'historical_window'
    for terms, code in [
        (('DOC/XLS/ZIP', 'XLS/ZIP', '附件类型'), 'unsupported_attachment'),
        (('图片', '扫描', '附件未', '附件中', '嵌入', '动态附件', 'PDF表格'), 'incomplete_evidence'),
        (('相同招生范围', '标识冲突'), 'existing_policy_conflict'),
        (('版本变化', '目录在核验期间'), 'source_changed'),
        (('缺少完整', '未找到明确', '截止不唯一'), 'incomplete_fields'),
        (('渠道', '学位对象', '专项', '批次', '标题', '机构', '院系', '年度'), 'ambiguous_scope'),
        (('AI',), 'ai_review'),
    ]:
        if any(term in reason for term in terms):
            return code
    return 'network_error' if status == 'retry' else 'manual_review'


NEXT_ACTION = {
    'awaiting_evidence': '按已发现时间排队，取得完整官方正文后核验',
    'ai_budget_wait': '等待共享AI额度恢复后继续，不重置调用账本',
    'unsupported_attachment': '核对并提取官方附件的受支持文本版本',
    'incomplete_evidence': '补齐图中信息、扫描件或缺失的官方附件',
    'existing_policy_conflict': '确认是补充、替代还是独立政策，保留已有事实',
    'source_changed': '按最新正文及附件重新取证，旧审核不复用',
    'historical_window': '保留历史依据，发现新一届正式公告后另行核验',
    'incomplete_fields': '补齐具名申请对象、材料、步骤及各自截止的官方出处',
    'ambiguous_scope': '按明确年度、学位、渠道及适用对象拆分核验',
    'ai_review': '根据AI错误或证据冲突原因继续核验，未通过不发布',
    'network_error': '按退避时间回源；持续失效需核对替代官方来源',
    'manual_review': '检查对应原文片段，确认完整适用范围后处理',
}
PROPOSAL_REVISION = 2


def sections(lines):
    aliases = {name: key for key, names in HEADINGS.items() for name in names}
    pattern = re.compile(r'^(?:[一二三四五六七八九十\d]+[、.．]|[（(][一二三四五六七八九十\d]+[）)])?\s*'
                         r'(' + '|'.join(aliases) + r')(?:\s*[：:（(]\s*(.*))?$')
    result, spans, names = {}, {}, {}
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line.strip().rstrip('：:').strip())
        if match:
            key = aliases[match[1]]
            if key in spans and spans[key][0] <= index < spans[key][1]:
                continue  # A named subsection inside the complete parent procedure.
            if key in spans and (key not in ('exams', 'tuition') or match[1] in names[key]):
                raise ValueError('同页重复申请栏目，须区分批次或对象')
            major = bool(re.match(r'^[一二三四五六七八九十]+[、.．]', line.strip()))
            stop = re.compile(r'^[一二三四五六七八九十]+[、.．]' if major else r'^(?:[一二三四五六七八九十]+[、.．]|\d+[、.．])')
            end = next((j for j in range(index + 1, len(lines)) if stop.match(lines[j].strip())), len(lines))
            spans[key] = (index, end)
            # Preserve section boundaries, especially when assessment and integrity
            # requirements are later grouped under the same public field.
            part = '\n'.join(lines[index:end]).strip()
            result[key] = '\n'.join(filter(None, (result.get(key), part)))
            names.setdefault(key, set()).add(match[1])
    return result


def deadline_events(parts):
    """Keep online registration and physical-delivery deadlines as separate events."""
    lines = (parts.get('timeline', '') + '\n' + parts['application_method']).splitlines()
    events = []
    for line in lines:
        if not re.search(r'^\s*[-—•]?\s*(?:网上报名时间|网报时间|报名(?:时间|截止)|申请(?:时间|截止)|接收截止时间|材料.{0,8}截止)', line):
            continue
        tight = extract.compact(line)
        if not re.search(r'至|截止|截至|日\d{0,2}[:：]?\d{0,2}[-—~～]\d{1,2}月', tight):
            continue
        if re.search(r'UTC|GMT|当地时间|时区', tight, re.I):
            raise ValueError('截止时区不明确，不能按北京时间推断')
        # One explicitly dated same-year range; no year inferred from publication.
        ranged = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日(?:\d{1,2}[:：]\d{2})?[至\-—~～](\d{1,2})月(\d{1,2})日(.*)$', tight)
        if ranged:
            start = datetime(int(ranged[1]), int(ranged[2]), int(ranged[3]))
            end = datetime(int(ranged[1]), int(ranged[4]), int(ranged[5]))
            if end < start:
                raise ValueError('跨年报名范围未明确结束年，不推断截止')
            tail = ranged[6]
            value = end.date().isoformat()
            time = re.match(r'(\d{1,2})(?:[:：时点])(\d{1,2})?分?', tail)
            if time:
                value = end.replace(hour=int(time[1]), minute=int(time[2] or 0), tzinfo=CST).isoformat()
            remaining = tail[time.end():] if time else tail
            if re.search(r'\d|上午|下午|中午|晚上|北京时间|点|时|秒', remaining):
                raise ValueError('范围截止含未完整解析的时刻或其他日期，不能只保留日期')
        else:
            normalized = re.sub(r'中午(?=12[:：])', '', tight)
            dates = list(extract.DATE.finditer(normalized))
            if len(dates) not in (1, 2) or re.search(r'下午|晚上|上午|中午', normalized):
                raise ValueError('截止日期或时刻有歧义，需保留原文核对')
            tail = normalized[dates[-1].end():]
            if re.search(r'至|到|[-—~～]|\d{1,2}[:：]\d{2}[:：]\d{2}', tail):
                raise ValueError('截止范围或秒精度尚未完整解析，不能丢弃')
            value = extract.date_value(dates[-1], normalized, with_time=True)
            if value and 'T' not in value and re.search(r'\d\s*[:：时点]|北京时间|点|时|秒', tail):
                raise ValueError('截止含未完整解析的时刻，不能只保留日期')
        if not value:
            raise ValueError('未取得有效截止日期')
        label = ('申请材料送达截止' if '接收' in tight or '材料' in tight else
                 '网上报名截止' if '网上' in tight else '申请报名截止')
        event = dict(label=label, kind='deadline', at=value, quote=line)
        if event not in events:
            events.append(event)
    if not events or len({e['label'] for e in events}) != len(events):
        raise ValueError('缺少明确截止或同一步骤有多个截止，须核对批次')
    return events


def candidates(root):
    """Only registered public columns, never arbitrary user or AI URLs."""
    root = Path(root)
    configs = []
    for filename, key in [('notices.yaml', 'targets'), ('opportunities.yaml', 'targets')]:
        path = root / 'sites' / filename
        if path.exists():
            configs.extend(yaml.safe_load(path.read_text(encoding='utf-8')).get(key, []))
    enabled = {(c['url'], c.get('school'), c.get('dept', '')) for c in configs if c.get('enabled') is not False}
    result = {}
    notices = root / 'data/notices.json'
    rows = json.loads(notices.read_text(encoding='utf-8')).get('notices', []) if notices.exists() else []
    queue = root / 'cache/opportunity_review.json'
    if queue.exists():
        rows += [dict(url=d['source_url'], source=d['listing_url'], school=d['item']['school_id'],
                      dept=d['item'].get('dept_id', ''), title=d['item']['title'], publication_date=None,
                      first_seen=d.get('first_seen'))
                 for d in review.read_queue(queue)['drafts'] if not d.get('manual_edit')]
    for row in rows:
        if (row.get('source'), row.get('school'), row.get('dept', '')) not in enabled:
            continue
        if not re.search(r'招生|招收|接收', row['title']) or not re.search(r'硕士|博士|推免|推荐免试', row['title']):
            continue
        if re.search(r'公示|名单|结果|冬令营|夏令营|目录|报考点|考点', row['title']):
            continue
        if any(urlsplit(row[key]).scheme != 'https' for key in ('url', 'source')):
            continue
        try:
            if review.institution(row['url']) != review.institution(row['source']):
                continue
        except ValueError:
            continue
        result.setdefault(row['url'], row)
    return list(result.values())


def discovered_at(row, previous, now):
    """A listing's discovery date is not its publication date or a new retry clock."""
    observed = []
    for value in (row.get('first_seen'), previous.get('first_seen')):
        try:
            stamp = datetime.fromisoformat(value)
            stamp = stamp.replace(tzinfo=CST) if stamp.tzinfo is None else stamp
            if stamp <= now:
                observed.append(stamp.astimezone(timezone.utc))
        except (TypeError, ValueError):
            pass
    return min(observed, default=now).isoformat()


def source_hints(row, raw, now):
    """Cheap source-bound routing before fetching attachments; never a publication gate."""
    try:
        doc = extract.document(raw, row['url'])
    except ValueError:
        return {}
    title, text = row['title'], doc['text']
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, 'html.parser')
    headings = [node.get_text(' ', strip=True) for node in soup.select('title,h1,h2,.news_title,.article-title,.article_title')]
    if not any(extract.compact(title) in extract.compact(heading) for heading in headings):
        return {}
    value = dict(source_sha256=hashlib.sha256(raw).hexdigest(), checked_at=now.isoformat())
    years = set(re.findall(r'(20\d{2})\s*年', title))
    if len(years) == 1:
        year = int(next(iter(years)))
        target = now.astimezone(CST).year + (1 if now.astimezone(CST).month >= 9 else 0)
        if re.search(r'推免|推荐免试', title):
            target = now.astimezone(CST).year + (2 if now.astimezone(CST).month >= 11 else 1)
        # A reused old title with a newly stated year must be reread, not archived.
        if year < target and not any(int(y) > year for y in re.findall(r'(20\d{2})\s*年', text)):
            return dict(value, classification='historical', reason_code='historical_window',
                        reason='官方正文标题明确为已结束招生周期，保留历史依据',
                        evidence=[dict(quote=title, locator='官方文章标题')])
    try:
        parts = sections(doc['lines'])
        events = deadline_events(dict(timeline=parts.get('timeline', ''), application_method=parts.get('application_method', '')))
        future = [event for event in events if (datetime.fromisoformat(event['at']) > now if 'T' in event['at'] else event['at'] >= now.astimezone(CST).date().isoformat())]
        if future:
            value['deadline_hint'] = min(future, key=lambda event: event['at'])
    except ValueError:
        pass
    return value


def register_candidates(root, pool, state, now):
    """Persist the whole discovered queue before this round's bounded network work."""
    queue_path = Path(root) / 'cache/opportunity_review.json'
    drafts = {d['source_url']: d for d in review.read_queue(queue_path)['drafts']}
    for row in pool:
        prior = state['records'].get(row['url'], {})
        first = discovered_at(row, prior, now)
        record = dict(prior, title=row['title'], source_url=row['url'], listing_url=row['source'], first_seen=first,
                      registered_at=prior.get('registered_at', now.isoformat()))
        if not prior:
            record.update(status='queued', reason='已从登记官方来源发现，等待取得完整证据', reason_code='awaiting_evidence',
                          next_action=NEXT_ACTION['awaiting_evidence'], pending_since=first)
        elif prior.get('title') != row['title']:
            record.update(status='queued', reason='同一官方地址的公告标题变化，重新核验', reason_code='source_changed',
                          next_action=NEXT_ACTION['source_changed'], pending_since=now.isoformat(), next_attempt_at=now.isoformat())
            record.pop('source_hints', None)
        elif prior.get('listing_url') and prior['listing_url'] != row['source']:
            record.update(status='queued', reason='已登记的官方公告栏目变化，重新核验', reason_code='source_changed',
                          next_action=NEXT_ACTION['source_changed'], next_attempt_at=now.isoformat())
        elif prior.get('pending_since') in (None, prior.get('first_seen')) and prior.get('status') not in ('published', 'historical'):
            record['pending_since'] = first
        draft = drafts.get(row['url'], {})
        fetched = draft.get('fetch', {})
        try:
            checked = datetime.fromisoformat(fetched['checked_at'])
            sha = fetched['sha256']
            if draft.get('listing_url') != row['source'] or checked.tzinfo is None or not 0 <= (now-checked).total_seconds() <= 86400 or not re.fullmatch('[a-f0-9]{64}', sha):
                raise ValueError('unbound or stale cache')
            evidence = Path(root) / 'cache/opportunity_evidence' / (sha + '.html')
            if evidence.is_symlink() or evidence.parent.is_symlink():
                raise ValueError('unsafe cache')
            raw = evidence.read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ValueError('changed cache')
            # A complete observation can detect attachment-only changes without
            # assigning publication trust to the opportunity monitor's cache.
            observed = dict(source_sha256=sha)
            if fetched.get('status') == 'ok' and fetched.get('evidence_mode') == 'complete' and fetched.get('content_sha256'):
                observed['content_sha256'] = fetched['content_sha256']
            changed = any(prior.get(key) and prior[key] != value for key, value in observed.items())
            if changed and prior.get('observed_evidence') != observed and prior.get('status') != 'published':
                record.update(status='queued', reason='官方正文或附件版本已变化，重新核验', reason_code='source_changed',
                              next_action=NEXT_ACTION['source_changed'], next_attempt_at=now.isoformat())
            record['observed_evidence'] = observed
            hints = source_hints(row, raw, now)
            if hints:
                record['source_hints'] = hints
                if hints.get('classification') == 'historical' and prior.get('status') not in ('published', 'eligible'):
                    record.update(status='historical', reason_code='historical_window', reason=hints['reason'],
                                  next_action=NEXT_ACTION['historical_window'], next_attempt_at=(now+timedelta(days=7)).isoformat())
                    record.pop('pending_since', None)
        except (OSError, KeyError, TypeError, ValueError):
            pass
        state['records'][row['url']] = record


def candidate_priority(row, state, now):
    record = state['records'][row['url']]
    hint = record.get('source_hints', {}).get('deadline_hint', {}).get('at', '')
    urgent = bool(hint and now.astimezone(CST).date().isoformat() <= hint[:10] <= (now+timedelta(days=7)).astimezone(CST).date().isoformat())
    day = now.astimezone(CST).date()
    classification = notice_util.classify_notice(row, day=day)
    cycle = classification['cycle']
    target = day.year + (day.month >= 9)
    year = classification['admission_year']
    if year is None:
        professional_years = set(re.findall(r'(20\d{2})\s*年[^，。；\d]{0,40}博士专业学位', row['title']))
        if len(professional_years) == 1:
            year = int(next(iter(professional_years)))
    # Display metadata can leave a dated doctoral or specialist application
    # without a route. Prioritize collecting its actual current evidence.
    current = cycle in ('current', 'preparation') or cycle == 'unknown' and year is not None and year >= target
    old = cycle == 'historical' or year is not None and year < target
    return (0 if urgent else 1 if current else 3 if old else 2,
            hint if urgent else '', record.get('checked_at', ''), record['first_seen'], row['url'])


def collect(raw, row, folder, pdf_fetcher, docx_fetcher):
    return automatic_evidence.collect(raw, row['url'], pdf_fetcher=pdf_fetcher,
        docx_fetcher=docx_fetcher, folder=folder)


def prepare(root, row, raw, doc, now):
    title, text = row['title'], doc['text']
    if extract.compact(title) not in extract.compact(text):
        raise ValueError('正式招生标题未在完整正文中确认')
    years = set(re.findall(r'(20\d{2})\s*年', title))
    if len(years) != 1:
        raise ValueError('招生年度不唯一或未明确，不由发布日期推断')
    year = int(next(iter(years)))
    # A named discipline before an explicit doctoral degree category is narrower
    # than the whole department. Keep that scope instead of widening applicability.
    named_program = re.search(r'20\d{2}\s*年([\u4e00-\u9fff]{2,20}?)(?:(?:工学|理学|管理学|经济学|法学|医学)博士研究生|博士专业学位研究生)', title)
    program = named_program[1] if named_program else ''
    degrees = [key for word, key in [('硕士', 'master'), ('博士', 'phd')] if word in title]
    if len(degrees) != 1:
        raise ValueError('学位对象不唯一，须拆分招生范围')
    recommend = bool(re.search(r'推免|推荐免试', text))
    assessment = bool(re.search(r'申请\s*[—－-]?\s*考核', text))
    exam = bool(re.search(r'统考|全国硕士研究生招生考试', text))
    if sum((recommend, assessment, exam)) != 1:
        raise ValueError('招生渠道缺失或同页多渠道，须核验各自适用范围')
    route = 'recommend' if recommend else 'assessment' if assessment else 'exam'
    current_year = now.astimezone(CST).year + ((2 if now.astimezone(CST).month >= 11 else 1)
        if route == 'recommend' else (1 if now.astimezone(CST).month >= 9 else 0))
    if year < current_year:
        raise ValueError('公告为已结束招生周期，不新增为当前政策')
    # A requirement to have worked on a national project is still an ordinary
    # eligibility clause. Keep its exact language in the proposed fields.
    scope_text = re.sub(r'(主持或作为关键技术骨干参与)国家重大专项(?=[^。；\n]{0,80}(?:的经历|经验))',
                        r'\1国家重大项目', text)
    if re.search(r'第一批|第二批|分批|更正|调整为|专项', scope_text):
        raise ValueError('涉及批次、变更或专项对象，需独立划分政策范围')
    schools = yaml.safe_load((Path(root) / 'data/schools.yaml').read_text(encoding='utf-8'))['schools']
    school = next((s for s in schools if s['id'] == row['school']), None)
    dept = row.get('dept', '')
    if not school:
        raise ValueError('招生机构尚未登记')
    if dept:
        path = Path(root) / 'sites' / row['school'] / (dept + '.yaml')
        config = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        if config.get('school') != row['school'] or config.get('dept') != dept or not config.get('dept_name') or config['dept_name'] not in text:
            raise ValueError('未取得登记院系的正文身份依据')
    elif school['name'] not in text:
        raise ValueError('未取得学校统一政策的正文身份依据')
    parts = sections(doc['lines'])
    automatic_evidence.supplement_materials(doc, parts, sections)
    if any(not parts.get(key) for key in HEADINGS if key not in ('timeline', 'exams', 'tuition', 'quota')):
        raise ValueError('缺少完整条件、材料、申请流程、报名时间或联系方式栏目')
    intro = []
    for line in doc['lines']:
        if re.match(r'^[一二三四五六七八九十]+[、.．]', line.strip()):
            break
        if re.search(r'必须|仅限|不得|须', line):
            intro.append(line)
    if intro:
        parts['eligibility'] = '\n'.join([*intro, parts['eligibility']])
    events = deadline_events(parts)
    parts['timeline'] = '\n'.join(event['quote'] for event in events)
    covered = extract.compact('\n'.join(parts.values()))
    for line in doc['lines']:
        if re.search(r'必须|仅限|不得|不接受|须|需提交|英语|绩点|排名|截止', line) and extract.compact(line) not in covered:
            raise ValueError('关键限制位于提取栏目之外，须核验全部适用条件')
    application_url = automatic_evidence.application_entry(doc, parts['application_method'], row['url'])
    if not extract.EMAIL.search(parts['contact']) and not re.search(r'\d[\d\s-]{6,}', parts['contact']):
        raise ValueError('未找到明确公开咨询联系方式')
    if all(event['at'][:10] < now.astimezone(CST).date().isoformat() for event in events):
        raise ValueError('申请窗口已过，不作为当前新政策自动入库')
    if all('T' in event['at'] and datetime.fromisoformat(event['at']) <= now for event in events):
        raise ValueError('已到具体申请截止时点')
    ident = 'auto-' + hashlib.sha256(row['url'].encode()).hexdigest()[:16]
    source_id = ident + '-page'
    # Include the page title in the policy version; it carries the explicit intake year.
    sources = {source_id: dict(url=row['url'], format='html', selector='html', label=title)}
    texts, hashes = {source_id: doc['html_text']}, {source_id: admissions_util.fingerprint(raw, sources[source_id])}
    for index, document in enumerate(doc['documents']):
        sid = ident + '-file-' + str(index)
        sources[sid] = dict(url=document['url'], format=document['format'], selector='', label=title + ' 官方附件')
        hashes[sid], texts[sid] = document['sha256'], document['text']
    def evidence(value):
        matches = [sid for sid, body in texts.items() if policy_revalidation.quote_match(value, body)]
        if not matches:
            raise ValueError('字段未能在完整单份官方正文/附件中定位')
        body = texts[matches[0]]
        positions = [i for i, char in enumerate(body) if not char.isspace()]
        normalized, cursor, begin = extract.compact(body), 0, None
        for line in value.splitlines():
            needle = extract.compact(line)
            if not needle:
                continue
            index = normalized.find(needle, cursor)
            if index < 0:
                raise ValueError('组合字段无法保留连续完整出处')
            begin = index if begin is None else begin
            cursor = index + len(needle)
        quote = body[positions[begin]:positions[cursor - 1] + 1]
        return dict(text=value, quote=quote, locator='完整官方栏目；自动联合证据核验', source_ids=[matches[0]])
    fields = {key: evidence(parts[key]) for key in ('eligibility', 'materials', 'timeline', 'contact')}
    for optional in ('exams', 'tuition', 'quota'):
        if parts.get(optional):
            fields[optional] = evidence(parts[optional])
    for event in events:
        proof = evidence(event['quote'])
        event.update(quote=proof['quote'], locator=proof['locator'], source_ids=proof['source_ids'])
    instruction = parts['application_method']
    if parts['materials'] not in instruction:
        combined = parts['materials'] + '\n' + instruction
        if any(policy_revalidation.quote_match(combined, body) for body in texts.values()):
            instruction = combined
    action = dict(id='submit-application-materials', label='按官方要求准备并提交申请材料', stage='application',
                  instruction=evidence(instruction), event_indexes=list(range(len(events))))
    if program and not dept:
        raise ValueError('具名专业政策必须登记真实院系，不能作为学校通用政策')
    policy = dict(id=ident, school=row['school'], dept=dept, level='program' if program else 'dept' if dept else 'school', title=title,
        year=year, degree=degrees[0], route=route, program=program, program_code='', track='ordinary',
        published_at=row.get('publication_date'), reviewed_at=now.astimezone(CST).date().isoformat(), review_method='automatic_evidence',
        source_id=source_id, review_hashes=hashes, fields=fields, material_actions=[action], events=events)
    checks = {key: dict(value=value['text'], quote=value['quote']) for key, value in fields.items()}
    checks['scope'] = dict(value=dict(title=title, year=year, degree=degrees[0], route=route, school=school['name'], dept=dept), quote=title)
    if program:
        checks['scope']['value']['program'] = program
    # Each displayed field is checked explicitly. A nested materials/instruction
    # object previously made the reviewer demand all process rules in each child.
    checks['application_requirements'] = dict(value=action['instruction']['text'], quote=action['instruction']['quote'])
    for index, event in enumerate(events):
        checks['deadline_' + str(index)] = dict(value=dict(label=event['label'], at=event['at']), quote=event['quote'])
    if application_url:
        checks['application_entry'] = dict(value=application_url, quote=evidence(parts['application_method'])['quote'])
    for index, document in enumerate(doc['documents']):
        checks['attachment_' + str(index)] = dict(value=document['text'], quote=document['text'])
    return dict(policy=policy, sources=sources, checks=checks, application_url=application_url)


def validate_display_checks(prepared):
    """The AI proposal must include the values that the applicant will actually see."""
    policy, checks = prepared['policy'], prepared['checks']
    expected = {key: dict(value=field['text'], quote=field['quote']) for key, field in policy['fields'].items()}
    actions = policy['material_actions']
    if len(actions) != 1:
        raise ValueError('申请材料动作尚未全部进入核验，未发布')
    instruction = actions[0]['instruction']
    expected['application_requirements'] = dict(value=instruction['text'], quote=instruction['quote'])
    expected.update({'deadline_' + str(index): dict(value=dict(label=event['label'], at=event['at']), quote=event['quote'])
                     for index, event in enumerate(policy['events'])})
    if any(checks.get(key) != value for key, value in expected.items()):
        raise ValueError('实际展示的条件、材料、流程或截止未完整绑定AI核验值，未发布')
    if prepared['application_url'] and checks.get('application_entry', {}).get('value') != prepared['application_url']:
        raise ValueError('实际报名入口未完整绑定AI核验值，未发布')
    scope = checks.get('scope', {}).get('value', {})
    if any(scope.get(key) != policy[key] for key in ('title', 'year', 'degree', 'route', 'dept')) or (
            policy['program'] and scope.get('program') != policy['program']):
        raise ValueError('实际适用范围未完整绑定AI核验值，未发布')


def run(root, *, limit=2, publish=True, now=None, fetcher=None, checker=None, pdf_fetcher=None, docx_fetcher=None, source_urls=()):
    root, now = Path(root), now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    if not 1 <= limit <= 5:
        raise ValueError('新政策每轮核验上限须为1至5')
    fetcher, checker = fetcher or review.fetch_source, checker or ai_review.check
    pdf_fetcher, docx_fetcher = pdf_fetcher or review.fetch_pdf, docx_fetcher or opportunity_attachments.fetch_docx
    folder, path = root / 'cache/policy_intake/evidence', root / 'cache/policy_intake/state.json'
    folder.mkdir(parents=True, exist_ok=True)
    with output_lock(path):
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'records': {}}
        data_path = root / 'data/admissions.yaml'
        data = yaml.safe_load(data_path.read_text(encoding='utf-8'))
        urls = {s['url'] for s in data['sources'].values()}
        pool = [row for row in candidates(root) if row['url'] not in urls and (not source_urls or row['url'] in source_urls)]
        register_candidates(root, pool, state, now)
        atomic_json(path, state)
        pool.sort(key=lambda row: candidate_priority(row, state, now))
        results = []
        for row in pool:
            if len(results) >= limit:
                break
            previous = state['records'].get(row['url'], {})
            updated_rule = (
                previous.get('status') == 'manual_required' and previous.get('proposal_revision') != PROPOSAL_REVISION
                and previous.get('reason') in (
                    '涉及批次、变更或专项对象，需独立划分政策范围',
                    '缺少完整条件、材料、申请流程、报名时间或联系方式栏目',
                )
            )
            if (not updated_rule and not (publish and previous.get('status') == 'eligible') and
                    previous.get('next_attempt_at', '') > now.isoformat() and previous.get('title') == row['title'] and
                    (previous.get('policy_version') == VERSION or previous.get('status') in ('retry', 'budget_wait', 'historical'))):
                continue
            record = dict(title=row['title'], source_url=row['url'], listing_url=row['source'],
                          checked_at=now.isoformat(), policy_version=VERSION, proposal_revision=PROPOSAL_REVISION,
                          first_seen=previous['first_seen'], registered_at=previous['registered_at'],
                          first_attempt_at=previous.get('first_attempt_at', now.isoformat()))
            for key in ('observed_evidence', 'manual_review', 'verified_review'):
                if key in previous:
                    record[key] = copy.deepcopy(previous[key])
            try:
                raw = fetcher({'url': row['url']})
                raw = raw.encode() if isinstance(raw, str) else raw
                digest = hashlib.sha256(raw).hexdigest()
                (folder / (digest + '.html')).write_bytes(raw)
                record['source_sha256'] = digest
                hints = source_hints(row, raw, now)
                record['source_hints'] = hints
                if hints.get('classification') == 'historical':
                    raise ValueError('公告为已结束招生周期，不新增为当前政策')
                doc = collect(raw, row, folder, pdf_fetcher, docx_fetcher)
                record['content_sha256'] = doc['content_sha256']
                prepared = prepare(root, row, raw, doc, now)
                validate_display_checks(prepared)
                record['input_text_sha256'] = hashlib.sha256(doc['text'].encode()).hexdigest()
                record['proposal_sha256'] = policy_revalidation.digest(prepared['checks'])
                policy = prepared['policy']
                scope = lambda p: tuple(p[k] for k in ('school', 'dept', 'year', 'degree', 'route', 'program'))
                if any(scope(old) == scope(policy) for old in data['policies']):
                    raise ValueError('已有相同招生范围政策，须核对补充或替代关系，不自动覆盖旧事实')
                if prepared['application_url']:
                    automatic_evidence.verify_application_entry(prepared['application_url'], row['url'], fetcher=fetcher)
                saved = previous.get('verified_review') or previous.get('manual_review') or previous
                cached = saved.get('ai', {})
                bindings = ('policy_version', 'source_sha256', 'content_sha256', 'input_text_sha256', 'proposal_sha256')
                unchanged = bool(cached and all(saved.get(key) == record[key] for key in bindings))
                if unchanged:
                    try:
                        ai_review.validate_bound(cached, doc['text'], prepared['checks'])
                    except ValueError:
                        unchanged = False
                ai = copy.deepcopy(cached) if unchanged else checker(root, row['url'], doc['text'], prepared['checks'])
                record['ai_reused'] = bool(unchanged)
                record['ai'] = ai  # Keep real timing, decisions and issues even when publication is refused.
                ai_review.validate_bound(ai, doc['text'], prepared['checks'])
                record.pop('verified_review', None)
                if ai['decision'] != 'consistent':
                    record['manual_review'] = {key: copy.deepcopy(record[key]) for key in (*bindings, 'ai')}
                    ai = ai_review.recheck(root, row['url'], doc['text'], prepared['checks'], ai, checker, version=VERSION)
                    record['ai'] = ai
                if ai['decision'] != 'consistent':
                    record['manual_review']['ai'] = copy.deepcopy(ai)
                    raise ValueError('AI建议人工判断：' + '；'.join(ai['issues']))
                validate_display_checks(prepared)
                record.pop('manual_review', None)
                record.update(ai=ai, proposed_policy=policy, proposed_sources=prepared['sources'], status='eligible')
                record['verified_review'] = {key: copy.deepcopy(record[key]) for key in (*bindings, 'ai')}
                if publish:
                    live = fetcher({'url': row['url']})
                    live = live.encode() if isinstance(live, str) else live
                    fresh = collect(live, row, folder, pdf_fetcher, docx_fetcher)
                    if hashlib.sha256(live).hexdigest() != digest or fresh['content_sha256'] != doc['content_sha256']:
                        raise ValueError('发布前正文或附件版本变化，不采用旧审核结果')
                    with output_lock(data_path), output_lock(root / 'data/admissions_checks.json'):
                        current = yaml.safe_load(data_path.read_text(encoding='utf-8'))
                        if policy_revalidation.digest(current) != policy_revalidation.digest(data):
                            raise ValueError('政策目录在核验期间变化，本轮未写入')
                        updated = copy.deepcopy(current)
                        if set(prepared['sources']) & set(updated['sources']):
                            raise ValueError('新政策来源标识冲突，未覆盖')
                        updated['sources'].update(prepared['sources'])
                        updated['policies'].append(policy)
                        units = {s['id']: {p.stem for p in (root / 'sites' / s['id']).glob('*.yaml')} for s in yaml.safe_load((root / 'data/schools.yaml').read_text(encoding='utf-8'))['schools']}
                        admissions_util.validate(updated, units)
                        checks_path = root / 'data/admissions_checks.json'
                        observed = json.loads(checks_path.read_text(encoding='utf-8')) if checks_path.exists() else {}
                        day = now.astimezone(CST).date().isoformat()
                        observed.update({sid: dict(status='ok', hash=sha, last_attempt=day, last_success=day, cached=False)
                                         for sid, sha in policy['review_hashes'].items()})
                        admissions_util.validate_checks(observed, updated['sources'])
                        # Missing checks after interruption hide a policy until the next refresh.
                        write_yaml(data_path, updated)
                        atomic_json(checks_path, observed)
                        data = updated
                    record['status'] = 'published'
            except (ValueError, OSError, requests.RequestException) as error:
                retryable = getattr(error, 'retryable', isinstance(error, (OSError, requests.RequestException)))
                record.update(status='retry' if retryable else 'manual_required', reason=str(error)[:700])
                if '每日调用上限' in str(error):
                    record['status'] = 'budget_wait'
                if getattr(error, 'code', None):
                    record['error_code'] = error.code
                if getattr(error, 'transport', None):
                    record['transport'] = error.transport
            record['reason_code'] = reason_code(record.get('reason', ''), record['status']) if record['status'] not in ('published', 'eligible') else record['status']
            if record['reason_code'] == 'historical_window':
                record['status'] = 'historical'
            failures = previous.get('failure_count', 0)
            record['failure_count'] = failures + 1 if record['status'] == 'retry' else failures if record['status'] == 'budget_wait' else 0
            hours = (168 if record['status'] == 'historical' else
                     min(24, 2 ** min(record['failure_count'], 5)) if record['status'] == 'retry' else 24)
            next_attempt = now + timedelta(hours=hours)
            if record['status'] == 'budget_wait':
                next_attempt = (now.astimezone(timezone.utc) + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
            record['next_attempt_at'] = next_attempt.isoformat()
            record['next_action'] = NEXT_ACTION.get(record['reason_code'], '证据审核通过，等待统一发布' if record['status'] == 'eligible' else '已入库，交由来源监测与政策续核')
            if record['status'] not in ('published', 'historical'):
                record['pending_since'] = previous.get('pending_since', record['first_seen'])
            history = copy.deepcopy(previous.get('history', []))
            keys = ('checked_at', 'status', 'reason_code', 'source_sha256', 'content_sha256')
            if previous and any(previous.get(k) != record.get(k) for k in keys if k != 'checked_at'):
                history.append({k: previous.get(k) for k in keys})
            record['history'] = history
            state['records'][row['url']] = record
            results.append(record)
            atomic_json(path, state)
        published = sum(row['status'] == 'published' for row in results)
        state['checked_at'] = now.isoformat()
        atomic_json(path, state)  # A healthy empty discovery round still has observable state.
        report = dict(checked_at=now.isoformat(), attempted=len(results), candidate_total=len(pool),
                      pending=sum(state['records'].get(row['url'], {}).get('status') not in ('published', 'historical') for row in pool),
                      published=published, changed=published, manual_required=sum(r['status'] == 'manual_required' for r in results),
                      retry=sum(r['status'] == 'retry' for r in results), budget_wait=sum(r['status'] == 'budget_wait' for r in results),
                      counts=dict(Counter(row['status'] for row in results)),
                      results=[{k: v for k, v in r.items() if k not in ('ai', 'manual_review', 'verified_review', 'proposed_policy', 'proposed_sources')} for r in results])
        atomic_json(root / 'cache/policy_intake/latest.json', report)
        return report
