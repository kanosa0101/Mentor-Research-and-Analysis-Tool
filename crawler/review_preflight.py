"""Source-bound queue triage before AI; never changes applicant facts or publishes."""
import copy
import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from crawler import opportunity_extract as extract, opportunity_review as review
from crawler.opportunity_monitor import atomic_json, output_lock

VERSION = 'official-queue-preflight-v2-evidence-state'
HUMAN_FIELDS = ('item', 'quotes', 'reviewed_fields', 'review', 'manual_edit', 'notes', 'note', 'manual_notes', 'triage')
ACTIVITY = re.compile(r'冬令营|夏令营|暑期(?:学校|研修班)|科研实践|科创计划|推荐免试|推免|Summer School', re.I)
NAVIGATION = re.compile(r'^(?:特色|暑期|大学生|优秀大学生)?(?:夏令营|冬令营)(?:网上报名系统|报名系统|报名)?$|^(?:通知公告|招生信息|招生工作)$')
AMBIGUOUS = re.compile(r'延期|延长|第二批|第三批|多批|分批|滚动|全年|长期|补录|另行通知')


def human_revision(draft):
    return review.item_hash({key: draft.get(key) for key in HUMAN_FIELDS})


def effective(draft):
    value = draft.get('preflight', {})
    if (value.get('version') == VERSION and value.get('source_url') == draft.get('source_url') and
            value.get('source_sha256') == draft.get('fetch', {}).get('sha256') and
            value.get('fetch_status') == draft.get('fetch', {}).get('status') and
            value.get('human_revision') == human_revision(draft)):
        return value
    return {}


def classify(root, draft, configs, *, now=None, queue_path=None):
    """Use verified current HTML bytes, not a listing title or stored AI suggestion."""
    now = now or datetime.now(timezone.utc)
    value = dict(version=VERSION, checked_at=now.isoformat(), as_of_day=now.date().isoformat(),
                 source_url=draft['source_url'], source_sha256=draft.get('fetch', {}).get('sha256'),
                 fetch_status=draft.get('fetch', {}).get('status'), fetched_at=draft.get('fetch', {}).get('checked_at'),
                 human_revision=human_revision(draft), classification='unknown', priority_hint=None,
                 reason_code='unclassified', reason='尚无充分正文证据用于自动分流', evidence=[])
    if any(draft.get(key) for key in ('review', 'manual_edit', 'quotes', 'reviewed_fields', 'notes', 'note', 'manual_notes', 'triage')):
        return dict(value, reason_code='human_protected', reason='保留已有人工内容或分流，不自动改其审核归属')
    fetch = draft.get('fetch', {})
    if fetch.get('status') != 'ok' and not review.evidence_error(fetch):
        return dict(value, reason_code='source_unavailable', reason='当前正文尚不可用，先恢复或核验完整来源')
    try:
        checked = datetime.fromisoformat(fetch.get('html_fetched_at') or fetch['checked_at'])
        if checked.tzinfo is None or not 0 <= (now-checked).total_seconds() <= 86400:
            return dict(value, reason_code='stale_evidence', reason='正文取证超过24小时，先刷新再自动分流')
        review.check_source(draft, configs)
        digest = fetch.get('sha256', '')
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            raise ValueError('missing source hash')
        folder = Path(queue_path).parent if queue_path else Path(root)/'cache'
        path = folder/'opportunity_evidence'/(digest+'.html')
        if path.is_symlink() or path.parent.is_symlink() or folder.is_symlink():
            raise ValueError('unsafe evidence path')
        raw = path.read_bytes()
        if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('source bytes changed')
        doc = extract.document(raw, draft['source_url'], require_article=False)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(value, reason_code='evidence_unverified', reason='来源身份、日期或原文字节无法核对，不自动分流')
    soup = BeautifulSoup(raw, 'html.parser')
    headings = [node.get_text(' ', strip=True) for node in soup.select('h1,h2,.news_title,.article-title,.article_title')]
    if soup.title:
        headings.append(soup.title.get_text(' ', strip=True))
    headings = [text for text in dict.fromkeys(headings) if text and len(text) <= 350]
    compact = extract.compact
    plain_headings = [re.split(r'\s*[|丨｜]\s*|\s*-\s*(?=[\u4e00-\u9fffA-Za-z])', text)[0].strip() for text in headings]
    navigation = next((h for h in plain_headings if NAVIGATION.fullmatch(h)), None)
    if navigation:
        portal_pattern = r'登录|登陆|用户名|注册|共\s*0\s*条'
        portal = ('报名系统' in navigation and re.search(portal_pattern, doc['text']) and
                  not re.search(r'申请对象|报名条件|申请材料|报名时间', doc['text']))
        links = [link for link in doc['links'] if ACTIVITY.search(link['label']) and re.search(r'20\d{2}|报名|通知', link['label'])]
        links = list({link['url']: link for link in links if link['url'] != draft['source_url']}.values())
        listing_count = len(links)
        paginated = re.search(r'共\s*\d+\s*条|总共\s*\d+\s*记录|首页.*上页.*下页.*尾页|First Previous.*Next Last', doc['text'])
        directory = ((listing_count >= 3 or listing_count >= 2 and paginated) and
                     not re.search(r'申请对象|报名条件|申请材料|报名时间|报名截止', doc['text']))
        if portal or directory:
            evidence = [dict(quote=navigation, locator='官方页面标题')]
            evidence += [dict(quote=(re.search(r'.{0,30}(?:'+portal_pattern+r').{0,50}', doc['text'])[0]), locator='系统或空栏目入口')] if portal else [dict(quote=link['label'][:500], url=link['url'], locator='独立公告链接') for link in links[:3]]
            if directory and paginated:
                evidence.append(dict(quote=paginated[0], locator='栏目分页'))
            return dict(value, classification='irrelevant', reason_code='navigation_or_portal',
                        reason='官方标题及正文表明这是栏目或报名系统入口；保留为来源，不作为单条活动消耗AI', evidence=evidence)
    try:
        article = extract.document(raw, draft['source_url'])
        derived = extract.extract(raw, draft['source_url'], '', today=now.date())
    except ValueError:
        return value
    lines = [line for line in article['lines'] if compact(line) not in {compact(h) for h in headings}]
    article_titles = [h for h in headings if ACTIVITY.search(h) and re.search(r'20\d{2}年', h)]
    title_years = {int(y) for title in article_titles for y in re.findall(r'(20\d{2})年', title)}
    dates = [(extract.iso_day(match), line) for line in lines for match in extract.DATE.finditer(compact(line))]
    dates = [(day, line) for day, line in dates if day]
    application_dates = [(day, line) for day, line in dates if
                         re.search(r'报名|申请|截止|活动时间|营期|举办|时间安排|夏令营|冬令营|暑期', line) and
                         not re.search(r'往年|去年|上一[年届期]|参考|历史|例如|示例|以往|上届|此前', line)]
    future = any(day >= now.date().isoformat() for day, _ in dates)
    past_deadlines = [(day, line) for day, line in application_dates if re.search(r'截止|截至|结束时间', line)]
    cohorts = [(int(match[1]), line) for line in lines for match in re.finditer(r'(20\d{2})(?:届|年毕业)', compact(line))
               if re.search(r'本科|申请|招收|报名', line)]
    old_cohort = bool(cohorts) and all(year <= now.year for year, _ in cohorts)
    # "未入选学生不再另行通知" and later arrival arrangements do not reopen an
    # old admission window. An ambiguous application window still needs review.
    uncertain_window = any(AMBIGUOUS.search(sentence) and re.search(r'报名|申请|项目|招收', sentence) and
                           not re.search(r'不再另行通知|不另行通知', sentence)
                           for line in lines for sentence in re.split(r'[。！？]', line))
    if (article_titles and len(title_years) == 1 and not uncertain_window and not future and
            ((max(title_years) < now.year and (old_cohort or any(int(day[:4]) == max(title_years) for day, _ in application_dates))) or
             (max(title_years) in (now.year, now.year+1) and past_deadlines))):
        evidence = [dict(quote=article_titles[0], locator='官方公告标题')]
        evidence += [dict(quote=line[:1500], locator='正文明确的申请或活动日期') for _, line in application_dates[:3]]
        if old_cohort:
            evidence += [dict(quote=line[:1500], locator='正文明确的历史毕业届别') for _, line in cohorts[:2]]
        return dict(value, classification='historical', reason_code='past_activity_dates',
                    reason='官方公告年度与正文日期或毕业届别证据指向已过去的轮次；保留历史，不占当期AI队列', evidence=evidence)
    if (review.evidence_error(fetch) and article_titles and len(title_years) == 1 and
            max(title_years) < now.year and not future and not uncertain_window and
            any(int(day[:4]) == max(title_years) for day, _ in dates)):
        return dict(value, priority_hint='past_activity_evidence', reason_code='past_activity_needs_evidence',
            reason='官方活动标题及页面日期属于往年，但图片或附件正文未完整核验；低优先处理，不自动确认为历史或当期机会',
            evidence=[dict(quote=article_titles[0], locator='官方公告标题'),
                      dict(quote=next(line[:1500] for day, line in dates if int(day[:4]) == max(title_years)), locator='页面明确日期')])
    target_year = now.year + (2 if now.month >= 9 else 1)
    cohort = derived.get('field_evidence', {}).get('graduation_year', {})
    if (derived.get('suggestions', {}).get('graduation_year') == target_year and
            not re.search(r'不接受|不得|不可|以外|以前|之后|其他活动|非20', cohort.get('quote', ''))):
        value.update(priority_hint='target_cohort', reason_code='target_cohort',
                     reason='正文明确提及当前准备毕业届别，优先核验；不代表申请资格成立',
                     evidence=[dict(quote=cohort['quote'][:1500], locator='正文申请对象')])
    elif any('冬令营' in title for title in article_titles) and title_years and title_years <= {now.year, now.year+1}:
        value.update(priority_hint='current_winter', reason_code='current_winter',
                     reason='官方标题指向本年度或下一年度冬令营，优先确认报名窗口与对象',
                     evidence=[dict(quote=article_titles[0], locator='官方公告标题')])
    return value


def classify_old_error(automatic):
    """Annotate known reasons; generic legacy errors remain explicitly unknown."""
    value = copy.deepcopy(automatic)
    failed = value.get('assistance', {})
    reasons = value.get('reasons', []) + [failed.get('reason', '')]
    if value.get('error_code'):
        return value
    if value.get('state') == 'budget_wait' and any('每日调用上限' in reason for reason in reasons):
        value.update(error_code='daily_budget_exhausted', error_phase='budget', retryable=True)
    elif any(reason == 'AI辅助公开证据暂时不可用' for reason in reasons):
        value.update(error_code='legacy_unclassified', error_phase='legacy', retryable=True,
                     error_note='旧记录未保存异常类别，不能断言是接口超时；按原退避时间先复取来源再重试')
        if failed:
            failed.update(error_code='legacy_unclassified', error_phase='legacy', retryable=True)
    elif '官方原文实时获取失败' in reasons:
        value.update(error_code='source_unavailable', error_phase='source_fetch', retryable=True)
    return value


def run(root, queue_path, configs, *, now=None, queue_wait=0):
    now = now or datetime.now(timezone.utc)
    rows = []
    with output_lock(queue_path, wait_seconds=queue_wait):
        queue = review.read_queue(queue_path)
        changed = False
        for draft in queue['drafts']:
            old = effective(draft)
            value = old if (old.get('as_of_day') == now.date().isoformat() and old.get('fetched_at') == draft.get('fetch', {}).get('checked_at')) else classify(root, draft, configs, now=now, queue_path=queue_path)
            if value != draft.get('preflight'):
                history_keys = ('source_sha256', 'human_revision', 'classification', 'reason_code', 'priority_hint')
                if draft.get('preflight') and any(value.get(key) != draft['preflight'].get(key) for key in history_keys):
                    draft.setdefault('preflight_history', []).append(draft['preflight'])
                draft['preflight'] = value
                changed = True
            automatic = draft.get('automatic_review')
            if automatic:
                routed = classify_old_error(automatic)
                if routed != automatic:
                    draft.setdefault('automatic_review_history', []).append(copy.deepcopy(automatic))
                    draft['automatic_review'] = routed
                    changed = True
            rows.append(dict(id=draft['id'], source_url=draft['source_url'], title=draft['item']['title'],
                             classification=review.triage(draft).get('classification', 'unknown'),
                             machine_classification=value['classification'], reason_code=value['reason_code'],
                             evidence=value['evidence'], error_code=draft.get('automatic_review', {}).get('error_code')))
        if changed:
            atomic_json(queue_path, queue)
    report = dict(checked_at=now.isoformat(), version=VERSION, changed=changed,
                  counts=dict(Counter(row['classification'] for row in rows)), rows=rows)
    atomic_json(Path(root)/'cache/review-preflight.json', report)
    return report
