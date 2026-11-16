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

VERSION = 'new-official-policy-v2-complete-layout'
CST = timezone(timedelta(hours=8))
HEADINGS = {
    'eligibility': ('申请条件', '报考条件', '报名条件', '申请资格', '招生对象', '基本条件'),
    'materials': ('申请材料', '报名材料', '提交材料', '材料要求', '提交申请材料清单'),
    'application_method': ('申请方式', '报名方式', '报名程序', '报名流程', '申请流程', '报名办法', '报名申请', '网上报名'),
    'timeline': ('报名时间', '申请时间', '受理时间'),
    'contact': ('联系方式', '咨询方式', '联系咨询', '招生咨询'),
    'exams': ('选拔方式', '考核方式', '考核程序'),
    'integrity': ('违规处理', '诚信要求'),
}


def reason_code(reason, status):
    if status == 'budget_wait':
        return 'ai_budget_wait'
    if reason in ('公告为已结束招生周期，不新增为当前政策', '申请窗口已过，不作为当前新政策自动入库', '已到具体申请截止时点'):
        return 'historical_window'
    for terms, code in [
        (('DOC/XLS/ZIP', '附件类型'), 'unsupported_attachment'),
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


def sections(lines):
    aliases = {name: key for key, names in HEADINGS.items() for name in names}
    pattern = re.compile(r'^(?:[一二三四五六七八九十\d]+[、.．]|[（(][一二三四五六七八九十\d]+[）)])?\s*'
                         r'(' + '|'.join(aliases) + r')(?:\s*[：:（(]\s*(.*))?$')
    result, spans = {}, {}
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line.strip().rstrip('：:').strip())
        if match:
            key = aliases[match[1]]
            if key in spans and spans[key][0] <= index < spans[key][1]:
                continue  # A named subsection inside the complete parent procedure.
            if key in spans:
                raise ValueError('同页重复申请栏目，须区分批次或对象')
            major = bool(re.match(r'^[一二三四五六七八九十]+[、.．]', line.strip()))
            stop = re.compile(r'^[一二三四五六七八九十]+[、.．]' if major else r'^(?:[一二三四五六七八九十]+[、.．]|\d+[、.．])')
            end = next((j for j in range(index + 1, len(lines)) if stop.match(lines[j].strip())), len(lines))
            spans[key] = (index, end)
            # Preserve section boundaries, especially when assessment and integrity
            # requirements are later grouped under the same public field.
            result[key] = '\n'.join(lines[index:end]).strip()
    return result


def deadline_events(parts):
    """Keep online registration and physical-delivery deadlines as separate events."""
    lines = (parts.get('timeline', '') + '\n' + parts['application_method']).splitlines()
    events = []
    for line in lines:
        if not re.search(r'^\s*[-—•]?\s*(?:网上报名时间|报名(?:时间|截止)|申请(?:时间|截止)|接收截止时间|材料.{0,8}截止)', line):
            continue
        tight = extract.compact(line)
        if not re.search(r'至|截止|截至', tight):
            continue
        if re.search(r'UTC|GMT|当地时间|时区', tight, re.I):
            raise ValueError('截止时区不明确，不能按北京时间推断')
        # One explicitly dated same-year range; no year inferred from publication.
        ranged = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日(?:\d{1,2}[:：]\d{2})?至(\d{1,2})月(\d{1,2})日(.*)$', tight)
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
                      dept=d['item'].get('dept_id', ''), title=d['item']['title'], publication_date=None)
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
    if re.search(r'第一批|第二批|分批|更正|调整为|专项', text):
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
    if any(not parts.get(key) for key in HEADINGS if key not in ('timeline', 'exams', 'integrity')):
        raise ValueError('缺少完整条件、材料、申请流程、报名时间或联系方式栏目')
    if parts.get('integrity'):
        parts['exams'] = '\n'.join(filter(None, (parts.get('exams'), parts.pop('integrity'))))
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
    if parts.get('exams'):
        fields['exams'] = evidence(parts['exams'])
    for event in events:
        proof = evidence(event['quote'])
        event.update(quote=proof['quote'], locator=proof['locator'], source_ids=proof['source_ids'])
    action = dict(id='submit-application-materials', label='按官方要求准备并提交申请材料', stage='application',
                  instruction=evidence(parts['application_method'] if parts['materials'] in parts['application_method'] else
                                       parts['materials'] + '\n' + parts['application_method']), event_indexes=list(range(len(events))))
    policy = dict(id=ident, school=row['school'], dept=dept, level='dept' if dept else 'school', title=title,
        year=year, degree=degrees[0], route=route, program='', program_code='', track='ordinary',
        published_at=row.get('publication_date'), reviewed_at=now.astimezone(CST).date().isoformat(), review_method='automatic_evidence',
        source_id=source_id, review_hashes=hashes, fields=fields, material_actions=[action], events=events)
    checks = {key: dict(value=value['text'], quote=value['quote']) for key, value in fields.items()
              if key not in ('materials', 'timeline')}
    checks['scope'] = dict(value=dict(year=year, degree=degrees[0], route=route, school=school['name'], dept=dept), quote=title)
    # One check covers related claims in the same full procedure, avoiding repeated
    # long quotations in the model output while retaining every proposed value.
    procedure = evidence(action['instruction']['text'] if all(line in action['instruction']['text'] for line in parts['timeline'].splitlines()) else
                         action['instruction']['text'] + '\n' + parts['timeline'])
    checks['application_procedure'] = dict(value=dict(materials=fields['materials']['text'],
        instruction=action['instruction']['text'], timeline=fields['timeline']['text'],
        deadlines=[dict(label=e['label'], at=e['at']) for e in events], application_url=application_url), quote=procedure['quote'])
    for index, document in enumerate(doc['documents']):
        checks['attachment_' + str(index)] = dict(value=document['text'], quote=document['text'])
    return dict(policy=policy, sources=sources, checks=checks, application_url=application_url)


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
        pool.sort(key=lambda row: (notice_util.classify_notice(row)['cycle'] not in ('current', 'preparation'),
                                  state['records'].get(row['url'], {}).get('checked_at', ''),
                                  -(int((row.get('publication_date') or '2000-01-01').replace('-', '')))))
        results = []
        for row in pool:
            if len(results) >= limit:
                break
            previous = state['records'].get(row['url'], {})
            if (previous.get('next_attempt_at', '') > now.isoformat() and previous.get('title') == row['title'] and
                    (previous.get('policy_version') == VERSION or previous.get('status') in ('retry', 'budget_wait', 'historical'))):
                continue
            record = dict(title=row['title'], source_url=row['url'], listing_url=row['source'],
                          checked_at=now.isoformat(), policy_version=VERSION,
                          first_seen=previous.get('first_seen', now.isoformat()))
            if previous.get('manual_review'):
                # Keep the last complete manual decision through transient fetch failures.
                record['manual_review'] = copy.deepcopy(previous['manual_review'])
            try:
                raw = fetcher({'url': row['url']})
                raw = raw.encode() if isinstance(raw, str) else raw
                digest = hashlib.sha256(raw).hexdigest()
                (folder / (digest + '.html')).write_bytes(raw)
                record['source_sha256'] = digest
                doc = collect(raw, row, folder, pdf_fetcher, docx_fetcher)
                record['content_sha256'] = doc['content_sha256']
                prepared = prepare(root, row, raw, doc, now)
                record['input_text_sha256'] = hashlib.sha256(doc['text'].encode()).hexdigest()
                record['proposal_sha256'] = policy_revalidation.digest(prepared['checks'])
                policy = prepared['policy']
                scope = lambda p: tuple(p[k] for k in ('school', 'dept', 'year', 'degree', 'route', 'program'))
                if any(scope(old) == scope(policy) for old in data['policies']):
                    raise ValueError('已有相同招生范围政策，须核对补充或替代关系，不自动覆盖旧事实')
                if prepared['application_url']:
                    fetcher({'url': prepared['application_url']})
                saved = previous.get('manual_review', previous)
                cached = saved.get('ai', {})
                unchanged = (cached.get('decision') == 'manual' and cached.get('validated_extracts') and
                    not cached.get('truncated') and cached.get('input_text_sha256') == record['input_text_sha256'] and
                    all(saved.get(key) == record[key] for key in
                        ('policy_version', 'source_sha256', 'content_sha256', 'input_text_sha256', 'proposal_sha256')))
                if unchanged:
                    try:
                        ai_review.validate({key: cached[key] for key in ('decision', 'issues', 'checks')}, doc['text'], prepared['checks'])
                    except (KeyError, ValueError):
                        unchanged = False
                ai = copy.deepcopy(cached) if unchanged else checker(root, row['url'], doc['text'], prepared['checks'])
                record['ai_reused'] = bool(unchanged)
                record['ai'] = ai  # Keep real timing, decisions and issues even when publication is refused.
                ai_review.validate({key: ai[key] for key in ('decision', 'issues', 'checks')}, doc['text'], prepared['checks'])
                if ai.get('truncated') or not ai.get('validated_extracts') or ai.get('input_text_sha256') != hashlib.sha256(doc['text'].encode()).hexdigest():
                    raise ValueError('AI未完成全部原文与附件的有效核验')
                if ai['decision'] != 'consistent':
                    record['manual_review'] = {key: copy.deepcopy(record[key]) for key in
                        ('policy_version', 'source_sha256', 'content_sha256', 'input_text_sha256', 'proposal_sha256', 'ai')}
                    raise ValueError('AI建议人工判断：' + '；'.join(ai['issues']))
                record.pop('manual_review', None)
                record.update(ai=ai, proposed_policy=policy, proposed_sources=prepared['sources'], status='eligible')
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
                      results=[{k: v for k, v in r.items() if k not in ('ai', 'manual_review', 'proposed_policy', 'proposed_sources')} for r in results])
        atomic_json(root / 'cache/policy_intake/latest.json', report)
        return report
