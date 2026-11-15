"""Restricted automatic verification: complete source evidence, AI check, original publisher gates."""
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
from bs4 import BeautifulSoup

from crawler import ai_evidence, ai_review, opportunity_extract as extract, opportunity_review as review, opportunity_util as util
from crawler.opportunity_monitor import atomic_json, output_lock

POLICY_VERSION = 'v1.8-extractive-1'
CST = timezone(timedelta(hours=8))
IDENTITY = {'id', 'title', 'school_id', 'dept_id', 'unit', 'source_url'}
SECTIONS = {
    'eligibility': ('申请条件', '申请对象', '招募对象', '报名条件', '招生对象'),
    'materials': ('申请材料', '报名材料', '材料要求'),
    'application_method': ('申请方式', '报名方式', '申请流程'),
    'contact': ('联系方式', '咨询方式', '联系咨询'),
    'window': ('报名时间', '申请时间', '受理时间'),
}


class NeedsHuman(ValueError):
    pass


def protected(draft):
    """Machine status and freshness may change; human content and review may not."""
    return review.item_hash({key: draft.get(key) for key in
        ('item', 'quotes', 'reviewed_fields', 'review', 'manual_edit', 'notes', 'note', 'manual_notes')})


def sections(lines):
    result, active = {}, None
    aliases = {name: field for field, names in SECTIONS.items() for name in names}
    heading = re.compile(r'^(?:[一二三四五六七八九十\d]+[、.．]|[（(][一二三四五六七八九十\d]+[）)])?'
                         r'(' + '|'.join(aliases) + r')(?:[：:]\s*(.*))?$')
    for line in lines:
        match = heading.fullmatch(line.strip())
        if match:
            active = aliases[match[1]]
            if active in result:
                raise NeedsHuman('存在重复申请条件或材料栏目，可能有不同对象或批次')
            result[active] = [match[2]] if match[2] else []
        elif re.match(r'^[一二三四五六七八九十]+[、.．]', line.strip()):
            active = None
        elif active:
            result[active].append(line)
    return {key: '\n'.join(lines).strip() for key, lines in result.items()}


def inspect_source(raw, source_url):
    if len(raw) > 3_000_000:
        raise NeedsHuman('官方页面超过自动核验大小上限')
    doc = extract.document(raw, source_url)
    if re.search(r'忽略.{0,12}(?:指令|规则)|ignore\s+(?:all\s+)?previous|system\s*prompt|AI助手请', doc['text'], re.I):
        raise NeedsHuman('原文含模型指令式内容，需人工确认页面可信性')
    if len(doc['text']) > ai_review.MAX_INPUT:
        raise NeedsHuman('官方正文超过完整AI核验长度，不能截断发布')
    soup = BeautifulSoup(raw, 'html.parser')
    body = next((soup.select_one(s) for s in extract.BODY_SELECTORS if soup.select_one(s)), soup.body or soup)
    if (extract.embedded_pdf_urls(raw, source_url) or body.select('img,iframe,object,embed') or
        re.search(r'附件|附表|二维码|扫码|扫描件|下载申请表', doc['text']) or
        any(re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)|/file/(?:common/)?download/', link['url'], re.I)
            for link in doc['links']) or soup.select('script#__NUXT_DATA__') and re.search(r'\.docx|fileList|file/common/download', str(soup), re.I)):
        raise NeedsHuman('正文含图片、附件或下载要求，需人工核实完整材料及附件版本')
    return doc


def fields_for_existing(draft, item, text):
    fields = {}
    for key in ('eligibility', 'materials', 'application_method', 'contact'):
        value = item.get(key)
        if not value:
            raise NeedsHuman('既有机会关键字段仍有缺口：' + key)
        quote = draft.get('reviewed_fields', {}).get(key, {}).get('quote', '')
        if not quote:
            pieces = value if isinstance(value, list) else [value]
            matching = [q for q in draft.get('quotes', []) if all(extract.compact(v) in extract.compact(q) for v in pieces)]
            quote = matching[0] if matching else ''
        if not quote or extract.compact(quote) not in extract.compact(text):
            raise NeedsHuman('既有字段缺少同页完整证据：' + key)
        fields[key] = dict(value=value, quote=quote)
    for key in ('registration_start', 'deadline'):
        if item.get(key):
            quote = draft.get('reviewed_fields', {}).get(key, {}).get('quote', '')
            if not quote or extract.compact(quote) not in extract.compact(text):
                raise NeedsHuman('既有日期缺少同页完整证据：' + key)
            fields[key] = dict(value=item[key], quote=quote)
    if item.get('application_window'):
        fields['application_window'] = dict(value=item['application_window'], quote=item['application_window']['quote'])
    if not item.get('deadline') and not item.get('application_window'):
        raise NeedsHuman('既有申请窗口不明确，不能自动续核')
    return fields


def prepare_new(root, draft, doc, now):
    item = copy.deepcopy(draft['item'])
    if draft.get('quotes') or draft.get('reviewed_fields') or any(v for k, v in item.items() if k not in IDENTITY):
        raise NeedsHuman('草稿已有人工或既有字段，自动任务不会覆盖')
    text = doc['text']
    if re.search(r'第一批|第二批|第三批|分批|多批|分阶段|另行通知|另行公布|暂定|待定|更正|调整为|UTC|GMT|当地时间', text, re.I):
        raise NeedsHuman('存在多批次、变更或日期语义歧义')
    if re.search(r'博士|硕士|研究生招生|研究生申请', text):
        raise NeedsHuman('同页涉及不同学位或角色，需人工独立核对本科申请范围')
    if re.search(r'入选名单|录取名单|录取结果|报到须知|活动回顾|圆满|开营安排', item['title']):
        raise NeedsHuman('标题不是明确的申请报名公告')
    title = item['title']
    if extract.compact(title) not in extract.compact(text):
        raise NeedsHuman('栏目标题未在完整公告正文中确认')
    kind = next((kind for label, kind in [('冬令营', 'winter_camp'), ('夏令营', 'summer_camp'),
        ('科研实践', 'research_program'), ('科研实习', 'research_program'), ('科创计划', 'research_program')] if label in title), None)
    if kind is None:
        raise NeedsHuman('活动类别不在自动发布范围；正式推免或学位招生需人工核对')
    parts = sections(doc['lines'])
    if any(not parts.get(key) for key in ('eligibility', 'materials', 'application_method', 'contact', 'window')):
        raise NeedsHuman('缺少独立且完整的申请对象、材料、方式、联系人或报名时间栏目')
    covered = extract.compact('\n'.join(parts.values()))
    for line in doc['lines']:
        if re.search(r'必须|仅限|不得|不接受|须|需提交|英语|绩点|排名|截止', line) and extract.compact(line) not in covered:
            raise NeedsHuman('关键限制出现在已覆盖栏目之外，需人工核对完整适用范围')
    if '本科' not in parts['eligibility']:
        raise NeedsHuman('未明确本科生申请对象，需人工判断适用范围')
    if (not extract.EMAIL.search(parts['application_method']) or not extract.EMAIL.search(parts['contact']) or
        re.search(r'系统|平台|在线|链接|网站|网报', parts['application_method'])):
        raise NeedsHuman('自动发布仅支持明确邮件申请及联系邮箱；其他系统流程需人工核对')
    schools_path = Path(root) / 'data/schools.yaml'
    schools = yaml.safe_load(schools_path.read_text(encoding='utf-8'))['schools'] if schools_path.exists() else []
    school = next((s['name'] for s in schools if s['id'] == item['school_id']), '')
    if not school:
        raise NeedsHuman('学校身份未登记，需先核对来源所属机构')
    item.update(school_name=school, kind=kind, cycle='current', source_state='verified',
                checked_at=now.astimezone(CST).date().isoformat(), verified_at=now.astimezone(CST).date().isoformat(),
                source_sha256=draft['fetch']['sha256'], source_content_sha256=doc['content_sha256'])
    fields = {}
    activity_year = re.findall(r'(20\d{2})年(?:计算机)?(?:冬令营|夏令营|科研实践|科研实习|科创计划)', title)
    if activity_year:
        year = int(activity_year[0])
        if len(set(activity_year)) != 1 or year not in (now.astimezone(CST).year, now.astimezone(CST).year + 1):
            raise NeedsHuman('活动年份与当前申请窗口不一致')
        item['camp_year'] = year
        fields['camp_year'] = dict(value=year, quote=title)
    for key in ('eligibility', 'materials', 'application_method', 'contact'):
        item[key] = [parts[key]] if key in ('eligibility', 'materials') else parts[key]
        fields[key] = dict(value=item[key], quote=parts[key])
    window = parts['window']
    dates = list(extract.DATE.finditer(extract.compact(window)))
    rolling = re.search(r'(?:长期|全年|常年|滚动).{0,30}(?:接受|接收|招收|招募|申请|报名)', extract.compact(window))
    if rolling and not dates and re.search(r'科研|实习', title):
        item['application_window'] = dict(mode='rolling', end_month='', quote=window)
        fields['application_window'] = dict(value=item['application_window'], quote=window)
    elif len(dates) == 2 and re.search(r'至|截止|截至', window):
        start_with_time = extract.date_value(dates[0], extract.compact(window), with_time=True)
        if start_with_time and 'T' in start_with_time:
            raise NeedsHuman('开始时间含具体时分，需人工核对完整开放时点')
        item['registration_start'] = extract.date_value(dates[0], extract.compact(window))
        item['deadline'] = extract.date_value(dates[1], extract.compact(window), with_time=True)
        if not item['registration_start'] or not item['deadline'] or item['deadline'][:10] < item['registration_start'] or item['deadline'][:10] < now.astimezone(CST).date().isoformat():
            raise NeedsHuman('报名窗口已结束或日期顺序无效')
        if 'T' in item['deadline'] and datetime.fromisoformat(item['deadline']) <= now:
            raise NeedsHuman('报名窗口已到具体截止时点')
        for key in ('registration_start', 'deadline'):
            fields[key] = dict(value=item[key], quote=window)
    else:
        raise NeedsHuman('报名窗口没有唯一完整的开始/截止日期或长期科研招募原文')
    # Years are never inferred; explicit years need a separate human applicability check.
    if re.search(r'20\d{2}\s*届|20\d{2}\s*年\s*入学', text):
        raise NeedsHuman('涉及具体毕业或入学届别，需人工确认对象映射')
    item['evidence'] = list(dict.fromkeys(f['quote'] for f in fields.values()))
    item['source_note'] = '自动证据核验：完整原文摘录、AI交叉核对及规则校验；不判断个人资格或保证名额。'
    item['admission_note'] = '科研或营活动不等于正式推免或研究生录取，毕业及入学届别未推断。'
    draft.update(item=item, quotes=item['evidence'], reviewed_fields={key: dict(quote=f['quote'], source_url=item['source_url'],
                 locator='官方公告完整栏目；自动证据核验', content_sha256=doc['content_sha256']) for key, f in fields.items()})
    util.validate(item)
    review.validate_field_evidence(draft, item, text)
    return fields


def _store(queue_path, draft_id, result, expected=None):
    with output_lock(queue_path):
        queue = review.read_queue(queue_path)
        current = next(d for d in queue['drafts'] if d['id'] == draft_id)
        if expected is not None and protected(current) != expected:
            result = dict(result, state='manual_required', reasons=['处理期间人工内容发生变化，结果未采纳'])
        if result.get('state') == 'published' and (current.get('manual_edit') or review.status(current) != 'published'):
            result = dict(result, state='manual_required', reasons=['发布后草稿再次被修改，请人工核对'])
        current['automatic_review'] = copy.deepcopy(result)
        atomic_json(queue_path, queue)
    return result


def _renew(root, queue_path, original, staged, result, now, fetcher):
    # The exact original bytes are fetched again, without treating new counters as unchanged.
    live = fetcher({'url': staged['source_url']})
    live = live.encode() if isinstance(live, str) else live
    if hashlib.sha256(live).hexdigest() != staged['fetch']['sha256']:
        raise NeedsHuman('AI复核后原文版本再次变化，保留旧事实待人工处理')
    with output_lock(queue_path), output_lock(Path(root) / 'data/opportunities.json'):
        queue = review.read_queue(queue_path)
        current = next(d for d in queue['drafts'] if d['id'] == original['id'])
        if protected(current) != protected(original):
            raise NeedsHuman('AI复核期间人工内容变化，未覆盖原记录')
        catalog = util.load(root)
        item = next(i for i in catalog['opportunities'] if i['id'] == original['item']['id'])
        if item != original['item']:
            raise NeedsHuman('已发布目录变化，不能自动覆盖')
        human_review = not current['review']['reviewer'].startswith('自动证据核验/')
        previous_manual = current['review'].get('manual_verified_at', item['verified_at']) if human_review else None
        stamp = now.astimezone(CST).date().isoformat()
        item.update(verified_at=stamp, checked_at=stamp)
        provenance = '自动证据复核于' + stamp + ('；原人工核验日期' + previous_manual if human_review else '') + '，原申请事实未改写。'
        item['source_note'] = re.sub(r'自动证据复核于\d{4}-\d{2}-\d{2}(?:；原人工核验日期\d{4}-\d{2}-\d{2})?，原申请事实未改写。', '', item['source_note']).strip() + '\n' + provenance
        current.update(item=copy.deepcopy(item), fetch=copy.deepcopy(staged['fetch']), automatic_review=result)
        current['review'].update(item_sha256=review.item_hash(item), last_automatic_check_at=now.isoformat())
        if human_review:
            current['review']['manual_verified_at'] = previous_manual
        catalog.setdefault('review_log', []).append(dict(operation='automatic_evidence_recheck',
            opportunity_id=item['id'], reviewed_at=now.isoformat(), source_sha256=item['source_sha256'],
            manual_verified_at=previous_manual, reviewer=current['review']['reviewer'], automation=copy.deepcopy(result)))
        atomic_json(Path(root) / 'data/opportunities.json', catalog)
        atomic_json(queue_path, queue)


def process(root, queue_path, draft, configs, *, publish, now, checker, fetcher):
    original = copy.deepcopy(draft)
    prior = draft.get('automatic_review', {})
    result = dict(id=draft['id'], policy_version=POLICY_VERSION, checked_at=now.isoformat(),
                  source_sha256=draft.get('fetch', {}).get('sha256'), content_sha256=draft.get('fetch', {}).get('content_sha256'),
                  input_revision=protected(draft), attempts=prior.get('attempts', 0), failures=prior.get('failures', 0), reasons=[])
    if prior.get('policy_version') == POLICY_VERSION and prior.get('next_attempt_at') and prior['next_attempt_at'] > now.isoformat() and prior.get('content_sha256') == result['content_sha256'] and prior.get('input_revision') == result['input_revision']:
        return dict(result, state='skipped', reasons=['尚未到下一次处理时间'], next_attempt_at=prior['next_attempt_at'])
    if prior.get('policy_version') == POLICY_VERSION and prior.get('state') == 'manual_required' and prior.get('input_revision') == result['input_revision'] and prior.get('content_sha256') == result['content_sha256']:
        return dict(result, state='skipped', reasons=['同版本仍需人工处理'], blocked_state='manual_required')
    prepared = None
    try:
        if draft.get('manual_edit') or any(draft.get(k) for k in ('notes', 'note', 'manual_notes')):
            raise NeedsHuman('维护者已编辑草稿，自动任务不会覆盖')
        if review.triage(draft).get('classification') in ('historical', 'irrelevant') or draft['item'].get('cycle') == 'historical':
            return dict(result, state='skipped', reasons=['历史或非报名记录不自动发布'])
        review.check_source(draft, configs)
        if any(urlsplit(draft[key]).scheme != 'https' for key in ('source_url', 'listing_url')) or not any(
            c['url'] == draft['listing_url'] and c.get('enabled') is not False for c in configs):
            raise NeedsHuman('自动发布仅接受已启用的HTTPS官方来源')
        if draft.get('fetch', {}).get('status') != 'ok' or draft['item'].get('source_documents') or draft['item'].get('source_attachments'):
            raise NeedsHuman('尚无完整HTML证据，或存在须核验的附件')
        existing = bool(draft.get('review'))
        if existing and review.status(draft) != 'published':
            raise NeedsHuman('已发布事实、人工摘录或官方版本变化，不能自动覆盖')
        if existing and draft['item'].get('verified_at') and 0 <= (now.astimezone(CST).date() - datetime.fromisoformat(draft['item']['verified_at']).date()).days < 14:
            return dict(result, state='skipped', reasons=['已有近期核验，日常来源检查继续运行'])
        staged = copy.deepcopy(draft)
        raw = review.fetch_evidence(staged, queue_path, fetcher, now=now)
        with output_lock(queue_path):
            queue = review.read_queue(queue_path)
            current = next(d for d in queue['drafts'] if d['id'] == draft['id'])
            if protected(current) != protected(original):
                raise NeedsHuman('实时取证期间草稿被人工编辑，未覆盖')
            current['fetch'] = copy.deepcopy(staged['fetch'])
            atomic_json(queue_path, queue)
        result.update(source_sha256=staged['fetch'].get('sha256'), content_sha256=staged['fetch'].get('content_sha256'))
        if raw is None:
            raise ValueError('官方原文实时获取失败')
        doc = inspect_source(raw, draft['source_url'])
        if existing:
            if staged['fetch']['content_sha256'] != draft['review'].get('content_sha256') or staged['fetch']['sha256'] != draft['review']['source_sha256']:
                raise NeedsHuman('已核验原文发生变化，需人工核对新事实')
            catalog_item = next((i for i in util.load(root)['opportunities'] if i['id'] == draft['item']['id']), None)
            if catalog_item != draft['item']:
                raise NeedsHuman('已发布目录与原核验记录不一致')
            fields = fields_for_existing(staged, staged['item'], doc['text'])
            review.validate_field_evidence(staged, staged['item'], doc['text'])
        else:
            fields = prepare_new(root, staged, doc, now)
        result.update(source_sha256=staged['fetch']['sha256'], content_sha256=doc['content_sha256'])
        cached = prior.get('ai')
        if prior.get('policy_version') == POLICY_VERSION and cached and cached.get('decision') == 'consistent' and prior.get('source_sha256') == staged['fetch']['sha256'] and prior.get('input_revision') == protected(original):
            ai = cached
        else:
            result['attempts'] += 1
            ai = checker(root, draft['source_url'], doc['text'], fields)
        ai_review.validate({key: ai[key] for key in ('decision', 'issues', 'checks')}, doc['text'], fields)
        if ai.get('truncated') or not ai.get('validated_extracts') or ai.get('input_text_sha256') != hashlib.sha256(doc['text'].encode()).hexdigest():
            raise NeedsHuman('AI没有完整有效的当前原文核验结果')
        result.update(ai=ai, model=ai.get('model'))
        if ai['decision'] != 'consistent':
            raise NeedsHuman('AI建议人工核对：' + '；'.join(ai['issues']))
        if not publish:
            return _store(queue_path, draft['id'], dict(result, state='eligible', reasons=['证据及AI交叉检查通过；尚未执行发布']), protected(original))
        result.update(state='renewed' if existing else 'published', reasons=['完整原文与关键字段通过自动证据核验'],
                      next_attempt_at=(now + timedelta(days=14)).isoformat())
        if existing:
            _renew(root, queue_path, original, staged, result, now, fetcher)
        else:
            with output_lock(queue_path):
                queue = review.read_queue(queue_path)
                current = next(d for d in queue['drafts'] if d['id'] == draft['id'])
                if protected(current) != protected(original):
                    raise NeedsHuman('AI处理期间草稿被人工编辑，未采纳或发布')
                for key in ('item', 'quotes', 'reviewed_fields', 'fetch'):
                    current[key] = copy.deepcopy(staged[key])
                current['automatic_review'] = dict(result, state='eligible')
                prepared = protected(current)
                revision = review.item_hash(current)
                atomic_json(queue_path, queue)
            try:
                review.publish(queue_path, draft['id'], root, configs, acknowledged_hash=staged['fetch']['sha256'],
                    reviewer='自动证据核验/' + POLICY_VERSION, note='AI交叉核对与确定性证据门禁通过；不判断个人申请资格。',
                    expected_revision=revision, fetcher=fetcher)
            except ValueError as error:
                raise NeedsHuman('发布门禁拒绝：' + str(error)) from None
            _store(queue_path, draft['id'], result)
        return result
    except (NeedsHuman, ValueError, OSError, requests.RequestException) as error:
        reason = str(error) if isinstance(error, ValueError) else '官方证据或本地处理暂时失败'
        if prepared:
            with output_lock(queue_path):
                queue = review.read_queue(queue_path)
                current = next(d for d in queue['drafts'] if d['id'] == draft['id'])
                if protected(current) == prepared:
                    for key in ('item', 'quotes', 'reviewed_fields'):
                        if key in original: current[key] = copy.deepcopy(original[key])
                        else: current.pop(key, None)
                    atomic_json(queue_path, queue)
        transient = any(token in reason for token in ('服务HTTP', '服务连接', '服务网络', '实时获取失败', '未启用', '缺少服务端密钥'))
        if isinstance(error, NeedsHuman) or isinstance(error, ValueError) and not transient and '每日调用上限' not in reason:
            result.update(state='manual_required', reasons=[reason])
        elif '每日调用上限' in reason:
            tomorrow = (now + timedelta(days=1)).astimezone(timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0)
            result.update(state='budget_wait', reasons=[reason], next_attempt_at=tomorrow.isoformat())
        else:
            failures = prior.get('failures', 0) + 1
            result.update(state='retry', reasons=[reason], failures=failures,
                          next_attempt_at=(now + timedelta(hours=min(24, 2 ** min(failures, 5)))).isoformat())
        return _store(queue_path, draft['id'], result, protected(original))


def assist_pending(root, queue_path, draft, configs, result, now, assistant):
    """Offer source-bound suggestions for human review without promoting any facts."""
    if (draft.get('review') or draft['item'].get('cycle') == 'historical' or
        review.triage(draft).get('classification') in ('historical', 'irrelevant') or
        draft.get('fetch', {}).get('status') != 'ok'):
        return result
    digest = draft['fetch'].get('sha256', '')
    previous = draft.get('ai_suggestions', {})
    if previous.get('source_sha256') == digest and previous.get('validated_extracts') and not previous.get('truncated'):
        return result
    failed = draft.get('automatic_review', {}).get('assistance', {})
    if failed.get('state') == 'failed' and failed.get('source_sha256') == digest and draft.get('automatic_review', {}).get('state') == 'manual_required':
        return result
    original = protected(draft)
    result = dict(result, state='manual_required', input_revision=original)
    try:
        review.check_source(draft, configs)
        if not any(c['url'] == draft['listing_url'] and c.get('enabled') is not False for c in configs):
            return result
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            return result
        path = Path(queue_path).parent / 'opportunity_evidence' / (digest + '.html')
        if path.is_symlink() or not path.exists():
            return result
        raw = path.read_bytes()
        if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            return result
        text = extract.document(raw, draft['source_url'])['text']
        if not text.strip() or len(text) > ai_evidence.MAX_INPUT:
            return result
        result['attempts'] = result.get('attempts', 0) + 1
        advice = assistant(root, draft['source_url'], text)
        ai_evidence.validate({'suggestions': advice['suggestions']}, text)
        if advice.get('truncated') or not advice.get('validated_extracts') or advice.get('input_text_sha256') != hashlib.sha256(text.encode()).hexdigest():
            raise NeedsHuman('AI辅助未完整核对当前正文，没有采纳建议')
        advice = dict(advice, source_sha256=digest, published=False,
            scope='仅HTML正文逐字建议；未核验附件、申请届别或资格，不构成可发布结论。')
        result['assistance'] = dict(state='ready', suggestions=len(advice['suggestions']), model=advice.get('model'),
                                    source_sha256=digest, scope=advice['scope'])
        with output_lock(queue_path):
            queue = review.read_queue(queue_path)
            current = next(d for d in queue['drafts'] if d['id'] == draft['id'])
            if protected(current) != original or current.get('fetch', {}).get('sha256') != digest:
                raise NeedsHuman('AI辅助期间人工内容或原文版本变化，建议未采纳')
            current['ai_suggestions'] = advice
            current['automatic_review'] = copy.deepcopy(result)
            atomic_json(queue_path, queue)
        return result
    except (ValueError, OSError, requests.RequestException) as error:
        reason = str(error) if isinstance(error, ValueError) else 'AI辅助公开证据暂时不可用'
        transient = any(s in reason for s in ('HTTP', '网络', '连接', '未启用', '缺少服务端密钥'))
        if '每日调用上限' in reason:
            retry = (now + timedelta(days=1)).astimezone(timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0)
            result.update(state='budget_wait', next_attempt_at=retry.isoformat())
        elif transient or isinstance(error, (OSError, requests.RequestException)):
            failures = draft.get('automatic_review', {}).get('failures', 0) + 1
            result.update(state='retry', failures=failures, next_attempt_at=(now + timedelta(hours=min(24, 2 ** min(failures, 5)))).isoformat())
        result['assistance'] = dict(state='failed', reason=reason, source_sha256=digest)
        result['reasons'] = result.get('reasons', []) + [reason]
        return _store(queue_path, draft['id'], result, original)


def run(root, queue_path=None, configs=None, *, limit=2, publish=False, now=None, checker=ai_review.check, fetcher=review.fetch_source, assistant=ai_evidence.suggest):
    root = Path(root)
    queue_path = Path(queue_path) if queue_path else root / 'cache/opportunity_review.json'
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('自动核验时间须包含时区')
    if not 1 <= limit <= 20:
        raise ValueError('每轮自动核验上限须为1至20条')
    configs = configs if configs is not None else yaml.safe_load((root / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']
    with output_lock(root / 'cache/automatic-review-run'):
        queue = review.read_queue(queue_path)
        from crawler.review_queue import ordered
        by_id = {d['id']: d for d in queue['drafts']}
        results, active, checked = [], 0, 0
        for row in ordered(queue, now=now, root=root):
            result = process(root, queue_path, by_id[row['id']], configs, publish=publish, now=now, checker=checker, fetcher=fetcher)
            if (result['state'] == 'manual_required' or result.get('blocked_state') == 'manual_required') and result.get('attempts', 0) == by_id[row['id']].get('automatic_review', {}).get('attempts', 0):
                fresh = next(d for d in review.read_queue(queue_path)['drafts'] if d['id'] == row['id'])
                result = assist_pending(root, queue_path, fresh, configs, result, now, assistant)
            results.append(result)
            checked += result['state'] != 'skipped'
            if result['state'] not in ('skipped', 'manual_required') or result.get('attempts', 0) > by_id[row['id']].get('automatic_review', {}).get('attempts', 0):
                active += 1
            if active >= limit or checked >= limit * 10:
                break
        report = dict(version=1, started_at=now.isoformat(), completed_at=datetime.now(timezone.utc).isoformat(),
            mode='publish' if publish else 'evaluate', counts=dict(Counter(r['state'] for r in results)), results=results,
            published_ids=[r['id'] for r in results if r['state'] == 'published'], renewed_ids=[r['id'] for r in results if r['state'] == 'renewed'],
            errors=[dict(id=r['id'], reasons=r['reasons']) for r in results if r['state'] in ('retry', 'budget_wait')])
        atomic_json(root / 'cache/automatic-review.json', report)
        return report
