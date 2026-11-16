"""Conservative official-text suggestions. Suggestions are never published claims."""
import hashlib
import html
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

BODY_SELECTORS = ('.TRS_Editor', '.v_news_content', '#vsb_content', '.article-content', '.article_content', 'article', 'main')
DATE = re.compile(r'(20\d{2})\s*[年./-]\s*(\d{1,2})\s*[月./-]\s*(\d{1,2})\s*日?')
EMAIL = re.compile(r'(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])')
MAX_PDF_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 100


def compact(text):
    return ''.join(text.split())


def embedded_pdf_urls(raw, source_url):
    """Read known literal embed locations; never evaluate page JavaScript."""
    soup = BeautifulSoup(raw, 'html.parser')
    values = [node['pdfsrc'] for node in soup.select('.wp_pdf_player[pdfsrc]')]
    for node in soup.select('nav,header,footer'):
        node.decompose()
    # University CMS attachment lists often sit after the article body container.
    values.extend(node['href'] for node in soup.select('a[href]')
                  if re.search(r'\.pdf(?:[?#]|$)', node['href'], re.I) or
                  re.search(r'\.pdf\s*$', node.get_text(' ', strip=True), re.I))
    for script in soup.select('script'):
        values.extend(match[1] for match in re.findall(r'showVsbpdfIframe\s*\(\s*([\"\'])([^\"\']+\.pdf(?:[?#][^\"\']*)?)\1', script.get_text(), re.I))
    urls = []
    for value in values:
        url = urljoin(source_url, value)
        parsed = urlsplit(url)
        if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password and url not in urls:
            urls.append(url)
    return urls


def pdf_document(raw, source_url, title='', today=None):
    """Extract a bounded PDF text layer by page; no OCR or publication authority."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError as error:
        raise ValueError('缺少pypdf依赖，PDF须稍后提取') from error
    if len(raw) > MAX_PDF_BYTES or not raw.startswith(b'%PDF-'):
        raise ValueError('PDF 超出12MB上限或不是有效PDF文件')
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            return dict(pages=[], page_count=None, text_status='encrypted', suggestions={}, field_evidence={},
                        warnings=['PDF已加密，未尝试解密；需人工核对。'])
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError('PDF 超出100页上限，需人工核对')
        pages = [dict(page=index+1, text=page.extract_text() or '') for index, page in enumerate(reader.pages)]
    except PyPdfError as error:
        raise ValueError('PDF文本解析失败，需人工核对') from error
    text = '\n'.join(page['text'] for page in pages)
    result = dict(pages=pages, page_count=len(pages), text_status='readable', suggestions={}, field_evidence={}, warnings=[])
    if len(compact(text)) < 20:
        result.update(text_status='no_text', warnings=['PDF 未取得足够文本层，可能是扫描件；未执行OCR，需人工核对。'])
        return result
    # Only the actual PDF text enters suggestions; HTML metadata is not a date source.
    markup = '<article>' + ''.join('<p>'+html.escape(line)+'</p>' for line in text.splitlines() if line.strip()) + '</article>'
    try:
        extracted = extract(markup, source_url, title, today)
    except ValueError:
        result.update(text_status='unclassified', warnings=['PDF有文本，但尚不能确认是申请公告正文；需人工核对。'])
        return result
    for evidence in extracted['field_evidence'].values():
        fragments = [compact(line) for line in evidence['quote'].splitlines() if compact(line)]
        evidence['pages'] = [page['page'] for page in pages if any(fragment in compact(page['text']) for fragment in fragments)]
        evidence['locator'] = 'PDF第' + '、'.join(map(str, evidence['pages'])) + '页' if evidence['pages'] else 'PDF标题元数据，须人工确认页码'
    result.update(extracted)
    return result


def pdf_source_version(raw, source_url, documents):
    """Bind an HTML notice and every embedded PDF byte version, including link moves."""
    shell = document(raw, source_url, require_article=False)['content_sha256']
    versions = sorted((doc['url'], doc['sha256']) for doc in documents)
    return hashlib.sha256(json.dumps([shell, versions], ensure_ascii=False).encode('utf-8')).hexdigest()


def document(raw, source_url, *, require_article=True):
    """Keep article meaning and links; strip only known non-article chrome/counters."""
    soup = BeautifulSoup(raw, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if re.search(r'^(?:访问被拒绝|访问验证|安全验证|验证码|Access Denied|Just a moment|403 Forbidden|404 Not Found)', title, re.I):
        raise ValueError('返回的是访问验证或错误页面，不是公告正文')
    for node in soup.select('script,style,noscript,nav,header,footer'):
        node.decompose()
    body = next((soup.select_one(selector) for selector in BODY_SELECTORS if soup.select_one(selector)), soup.body or soup)
    for node in list(body.find_all(True)):
        if node.attrs is None:
            continue
        marker = ' '.join([node.get('id', ''), *node.get('class', [])]).lower()
        if re.search(r'(?:^|[-_\s])(?:clickcount|readcount|visitcount|hits|views)(?:$|[-_\s])', marker):
            node.decompose()
    lines = []
    blocks = body.select('p,li,h1,h2,h3,h4')
    texts = [node.get_text(' ', strip=True) for node in blocks] if blocks else body.get_text('\n', strip=True).splitlines()
    for text in texts:
        text = re.sub(r'\s+', ' ', text).strip()
        if text and not re.fullmatch(r'(?:浏览|访问|阅读|点击)(?:量|次数)?\s*[:：]?\s*\d+\s*(?:次)?', text):
            lines.append(text)
    text = re.sub(r'(?:浏览|访问|阅读|点击)(?:量|次数)\s*[:：]\s*\d+\s*(?:次)?', '', body.get_text(' ', strip=True))
    if require_article and (len(compact(text)) < 20 or not re.search(r'申请|报名|本科生|研究生|材料|招生|科创|冬令营|夏令营', text)):
        raise ValueError('未识别到有效申请公告正文，可能是空页、导航页或访问受限')
    link_text = ''.join(node.get_text(' ', strip=True) for node in body.select('a[href]'))
    if require_article and len(compact(link_text)) >= len(compact(text)) * 0.8:
        raise ValueError('页面主要是导航链接，未取得公告正文')
    links = []
    for node in body.select('a[href]'):
        url = urljoin(source_url, node['href'])
        if urlsplit(url).scheme in ('http', 'https') and not urlsplit(url).username:
            links.append(dict(url=url, label=node.get_text(' ', strip=True)))
    # Links are part of meaning: a changed application or attachment target needs review.
    canonical = compact(title) + '\n' + compact(text) + '\n' + json.dumps(sorted({link['url'] for link in links}), ensure_ascii=False)
    return dict(text=text, lines=lines or [text], links=links,
                content_sha256=hashlib.sha256(canonical.encode('utf-8')).hexdigest())


def iso_day(match):
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def date_value(match, text, with_time=False):
    day = iso_day(match)
    if not day:
        return None
    time = re.match(r'\s*(\d{1,2})\s*[:：时点]\s*(\d{1,2})?\s*分?', text[match.end():]) if with_time else None
    if time and int(time[1]) < 24 and int(time[2] or 0) < 60:
        day += f'T{int(time[1]):02d}:{int(time[2] or 0):02d}:00+08:00'
    return day


def explicit_date_values(text, with_time=False):
    """Full dates plus unambiguous same-month ranges such as 2027年1月10日-14日."""
    text = compact(text)
    values = {date_value(match, text, with_time) for match in DATE.finditer(text)}
    for match in re.finditer(r'(20\d{2})年(\d{1,2})月(\d{1,2})日?[-—–至~](\d{1,2})日', text):
        try:
            start = date(*map(int, match.groups()[:3]))
            end = date(int(match[1]), int(match[2]), int(match[4]))
            if end >= start:
                values.update((start.isoformat(), end.isoformat()))
        except ValueError:
            continue
    return values - {None}


def extract(raw, source_url, title='', today=None):
    doc = document(raw, source_url)
    suggestions, evidence, warnings = {}, {}, []
    def offer(field, value, quote, precision=None):
        suggestions[field] = value
        evidence[field] = dict(quote=quote, source_url=source_url, locator='官方公告正文',
                               precision=precision or 'text', content_sha256=doc['content_sha256'])
    title_text = title or doc['lines'][0]
    kind = next(((token, value) for token, value in [('冬令营', 'winter_camp'), ('夏令营', 'summer_camp'),
                   ('科学营', 'summer_camp'), ('科创计划', 'research_program'), ('科研实践', 'research_program'),
                   ('创新实践', 'research_program'), ('推免', 'recommend'), ('推荐免试', 'recommend')] if token in title_text), None)
    if kind:
        offer('kind', kind[1], kind[0])
    year = re.search(r'(20\d{2})\s*年[^。]{0,20}(?:冬令营|夏令营|科学营|科创计划|创新实践)', title_text)
    if year:
        offer('camp_year', int(year[1]), year[1] + '年', 'year')
    graduation = re.findall(r'(20\d{2})\s*届(?:[^，。；\n]{0,15})(?:本科|毕业生)', compact(doc['text']))
    if len(set(graduation)) == 1:
        quote = next((line for line in doc['lines'] if re.search(r'20\d{2}\s*届[^，。；\n]{0,15}(?:本科|毕业生)', compact(line))), doc['text'])
        offer('graduation_year', int(graduation[0]), quote, 'year')
    admission = re.findall(r'(20\d{2})\s*年\s*入学', compact(doc['text']))
    if len(set(admission)) == 1:
        quote = next((line for line in doc['lines'] if re.search(r'20\d{2}\s*年\s*入学', compact(line))), doc['text'])
        offer('admission_year', int(admission[0]), quote, 'year')
    deadline_candidates, start_candidates = [], []
    registration_context = False
    for line in doc['lines']:
        tight = compact(line)
        if re.match(r'^[一二三四五六七八九十]+[、.．]', tight):
            registration_context = bool(re.search(r'报名.*(?:时间|受理)|受理.*时间', tight))
        dates = [(m, iso_day(m)) for m in DATE.finditer(tight)]
        dates = [(m, day) for m, day in dates if day]
        if (registration_context or re.search(r'报名|申请|受理', tight)) and re.search(r'截止|截至|至', tight):
            if not re.search(r'入选|报到|结题|邮寄|补交|面试', tight):
                for match, day in dates:
                    prefix = tight[max(0, match.start()-15):match.start()]
                    if re.search(r'(?:截止|截至|至)(?:时间为|时间|日期为|日期|为|到|于|：|:)*$', prefix):
                        day = date_value(match, tight, with_time=True)
                        deadline_candidates.append((day, line))
                month = re.search(r'(?:截止|截至|至)\s*(20\d{2})\s*年\s*(\d{1,2})\s*月(?!\s*\d)', tight)
                if month and 1 <= int(month[2]) <= 12:
                    offer('registration_deadline_month', f'{month[1]}-{int(month[2]):02d}', line, 'month')
                    warnings.append('受理截止仅明确到月份，不推算月末日期。')
        if len(dates) == 1 and re.search(r'报名|受理', tight) and re.search(r'开始|启动', tight):
            start_candidates.append((dates[0][1], line))
        if re.search(r'活动时间|营期|举办时间', tight) and len(dates) == 2:
            offer('event_start', dates[0][1], line, 'day')
            offer('event_end', dates[1][1], line, 'day')
    for key, values in [('deadline', deadline_candidates), ('registration_start', start_candidates)]:
        if len({value for value, _ in values}) == 1:
            offer(key, values[0][0], values[0][1], 'minute' if 'T' in values[0][0] else 'day')
        elif values:
            warnings.append('存在多个' + key + '日期，留待人工区分批次或事项。')
    # Preserve whole source paragraphs, including stage qualifiers and exceptions.
    sections = {'eligibility': ('申请条件', '申请对象', '招募对象', '报名条件'),
                'materials': ('申请材料', '报名材料', '材料要求', '报名方式')}
    for field, headings in sections.items():
        selected = []
        active = False
        for line in doc['lines']:
            is_heading = bool(re.match(r'^[一二三四五六七八九十]+[、.．]', compact(line)))
            if re.match(r'^(?:[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十]+[）)])?(?:' + '|'.join(headings) + r')(?:[：:]|$)', compact(line)):
                active = True
                if len(line) > 20:
                    selected.append(line)
                continue
            if is_heading:
                active = False
            if active:
                selected.append(line)
        if selected:
            offer(field, selected, '\n'.join(selected))
    emails = sorted(set(EMAIL.findall(doc['text'])))
    if emails:
        offer('contact', '；'.join(emails), '\n'.join(line for line in doc['lines'] if any(email in line for email in emails)))
    attachments = [link for link in doc['links'] if re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)', link['url'], re.I)]
    if attachments:
        offer('attachments', attachments, '\n'.join(link['label'] or link['url'] for link in attachments))
    day = today or datetime.now(timezone(timedelta(hours=8))).date()
    deadline = suggestions.get('deadline')
    end = suggestions.get('event_end')
    classification = 'pending_review'
    if any(value and date.fromisoformat(value[:10]) < day for value in (deadline, end)):
        classification = 'historical'
    elif deadline or end or suggestions.get('registration_deadline_month', '') >= day.isoformat()[:7]:
        classification = 'current_pending_review'
    return dict(suggestions=suggestions, field_evidence=evidence, warnings=warnings,
                classification=classification, content_sha256=doc['content_sha256'])
