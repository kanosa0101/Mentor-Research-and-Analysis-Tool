"""Complete, bounded public evidence for automatic review; no OCR or form submission."""
import hashlib
import io
import re
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import opportunity_attachments as attachments, opportunity_extract as extract


class EvidenceError(ValueError):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def attachment_links(raw, source_url):
    soup = BeautifulSoup(raw, 'html.parser')
    for node in soup.select('nav,header,footer'):
        node.decompose()
    body = next((soup.select_one(s) for s in extract.BODY_SELECTORS if soup.select_one(s)), soup.body or soup)
    found = {url: 'pdf' for url in extract.embedded_pdf_urls(raw, source_url)}
    for tag in soup.select('a[href]'):
        value = tag['href'] + ' ' + tag.get_text(' ', strip=True)
        match = re.search(r'\.(pdf|docx?|xlsx?|zip)(?:\b|[?#])', value, re.I)
        if match:
            found[urljoin(source_url, tag['href'])] = match[1].lower()
        elif re.search(r'download\.jsp|/file/(?:common/)?download/', tag['href'], re.I):
            raise ValueError('附件类型不明确，需核对官方下载文件')
    for url in attachments.linked_docx(raw, source_url):
        found[url] = 'docx'
    if len(found) > 5:
        raise ValueError('官方附件超过5份，需人工核对适用范围')
    if any(kind not in ('pdf', 'docx', 'doc', 'xlsx') for kind in found.values()):
        raise EvidenceError('unsupported_attachment', '官方附件含尚不支持的XLS/ZIP格式，不能忽略后发布')
    return found


def attachment_icon(image, links, source_url):
    """Recognize the CMS's file-type icon only when it labels an actual bound download."""
    src = urlsplit(urljoin(source_url, image.get('src', '')))
    anchor = image.find_parent('a', href=True)
    if (src.hostname != urlsplit(source_url).hostname or src.query or src.fragment or
            not re.fullmatch(r'/system/resource/images/fileTypeImages/icon_(?:docx?|pdf|xlsx?)\.gif', src.path) or
            image.get('alt', '').strip() or image.get('title', '').strip() or image.get('usemap') or image.find_parent('figure') or not anchor):
        return False
    target = urljoin(source_url, anchor['href'])
    return target in links and bool(re.search(r'\.' + links[target] + r'\s*$', anchor.get_text(' ', strip=True), re.I))


def inspect_html(raw, source_url):
    """Only explicitly decorative, non-linked images can be ignored."""
    if len(raw) > 3_000_000:
        raise ValueError('官方页面超过自动核验大小上限')
    soup = BeautifulSoup(raw, 'html.parser')
    for node in soup.select('nav,header,footer'):
        node.decompose()
    body = next((soup.select_one(s) for s in extract.BODY_SELECTORS if soup.select_one(s)), soup.body or soup)
    links = attachment_links(raw, source_url)
    image_checks = []
    for image in body.select('img'):
        if attachment_icon(image, links, source_url):
            image_checks.append(dict(url=urljoin(source_url, image['src']), kind='attachment_type_icon',
                                     reason='固定CMS文件图标路径、空替代文本与明确文件下载链接共同确认'))
            continue
        decorative = (image.get('role') == 'presentation' or image.get('aria-hidden') == 'true')
        if (not decorative or image.get('alt', '').strip() or image.get('title', '').strip() or
                image.find_parent(['a', 'figure']) or image.get('usemap')):
            qr = re.search(r'二维码|扫码|qrcode|qr-code', str(image) + image.parent.get_text(' ', strip=True), re.I)
            raise EvidenceError('qr_evidence_required' if qr else 'image_evidence_required',
                                '正文二维码入口需核对与文字报名流程是否一致' if qr else '正文图片未明确标为纯装饰，需核实图中申请信息')
    for node in body.select('iframe,object,embed'):
        value = node.get('src') or node.get('data') or node.get('pdfsrc') or ''
        if urljoin(source_url, value) not in links or links[urljoin(source_url, value)] != 'pdf':
            raise ValueError('正文有尚未核验的嵌入内容')
    doc = extract.document(raw, source_url, require_article=not links)
    doc['image_checks'] = image_checks
    if re.search(r'忽略.{0,12}(?:指令|规则)|ignore\s+(?:all\s+)?previous|system\s*prompt|AI助手请', doc['text'], re.I):
        raise ValueError('原文含模型指令式内容，需人工确认页面可信性')
    if not links and re.search(r'见附件|详见附表|下载(?:附件|申请表)|附件\s*[一二三四\d]|附件中(?:查询|查看)', doc['text']):
        raise ValueError('正文要求的附件未取得明确官方链接')
    if soup.select('script#__NUXT_DATA__') and re.search(r'\.docx|fileList|file/common/download', str(soup), re.I) and not links:
        raise ValueError('动态附件尚未取得完整的官方链接清单')
    return doc, links


def collect(raw, source_url, *, pdf_fetcher, docx_fetcher, office_fetcher=None, folder=None, wait=None):
    """Bind every linked document, including forms, to one untruncated text version."""
    from crawler.ai_review import MAX_INPUT
    doc, links = inspect_html(raw, source_url)
    soup = BeautifulSoup(raw, 'html.parser')
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if page_title and extract.compact(page_title) not in extract.compact(doc['text']):
        # Many official CMS templates place their article heading outside the body selector.
        doc = dict(doc, text=page_title + '\n' + doc['text'], lines=[page_title, *doc['lines']])
    documents = []
    for url, kind in links.items():
        attachments.official_url(url, source_url)
        if wait:
            wait(url)
        content = ((office_fetcher or attachments.fetch_office)(url, source_url, kind) if kind in ('doc', 'xlsx') else
                   (pdf_fetcher if kind == 'pdf' else docx_fetcher)(url, source_url))
        if kind == 'pdf':
            from pypdf import PdfReader
            parsed = extract.pdf_document(content, url)
            if parsed['text_status'] not in ('readable', 'unclassified') or any(len(extract.compact(p['text'])) < 20 for p in parsed['pages']):
                raise ValueError('PDF含扫描、加密、空白或无法独立核验的页面，不能自动发布')
            reader = PdfReader(io.BytesIO(content))
            if any(list(page.images) for page in reader.pages):
                raise ValueError('PDF含图片证据，文本层不足以确认完整要求')
            from crawler.pdf_layout import complete_pages
            pages = complete_pages(content, parsed['pages'])
            text = '\n'.join(p['text'] for p in pages)
            detail = dict(pages=pages, page_count=parsed['page_count'])
        elif kind == 'docx':
            parsed = attachments.parse_docx(content)
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if any(name.startswith('word/media/') for name in archive.namelist()):
                    raise ValueError('DOCX含图片证据，不能仅按文本自动发布')
            text, detail = parsed['text'], {}
        else:
            parsed = attachments.parse_office(content, kind)
            text, detail = parsed['text'], {key: value for key, value in parsed.items() if key != 'text'}
        if len(text) > 6000:
            raise ValueError('附件超过逐项完整核验长度，不能截断发布')
        digest = hashlib.sha256(content).hexdigest()
        entry = dict(url=url, format=kind, sha256=digest, text=text, **detail)
        if folder is not None:
            path = Path(folder) / (digest + '.' + kind)
            if path.exists() and path.read_bytes() != content:
                raise ValueError('同SHA证据路径已有不同内容，未覆盖')
            path.write_bytes(content)
            entry['evidence_file'] = str(path.resolve())
        documents.append(entry)
    combined = dict(doc, html_text=doc['text'], documents=documents)
    combined['text'] = '\n'.join([doc['text'], *(d['text'] for d in documents)])
    # A form following the article is not part of its last (often deadline) section.
    has_sections = any(re.search(r'申请条件|报名条件|报考条件|申请材料|报名材料', line) for line in doc['lines'])
    combined['lines'] = doc['lines'] if has_sections else doc['lines'] + [
        line for d in documents for line in d['text'].splitlines() if line.strip()]
    if len(combined['text']) > MAX_INPUT:
        raise ValueError('完整正文及附件超过AI核验长度，不截断后发布')
    if re.search(r'忽略.{0,12}(?:指令|规则)|ignore\s+(?:all\s+)?previous|system\s*prompt|AI助手请', combined['text'], re.I):
        raise ValueError('官方附件含模型指令式内容，需人工确认可信性')
    pdfs = [d for d in documents if d['format'] == 'pdf']
    docxs = [d for d in documents if d['format'] != 'pdf']
    content_hash = extract.pdf_source_version(raw, source_url, pdfs) if pdfs else doc['content_sha256']
    combined['content_sha256'] = attachments.source_version(content_hash, docxs)
    return combined


def metadata(doc, checked_at):
    pdfs, docxs = [], []
    for document in doc.get('documents', []):
        value = dict(url=document['url'], sha256=document['sha256'], checked_at=checked_at)
        if document['format'] == 'pdf':
            value.update(page_count=document['page_count'], field_evidence={'evidence': dict(
                quote=document['text'], pages=[p['page'] for p in document['pages']])})
            pdfs.append(value)
        else:
            kind = document['format']
            if kind != 'docx':
                value['format'] = kind
            value['field_evidence'] = {'materials': dict(quote=document['text'], locator='官方' + kind.upper() + '完整正文（含表格定位）')}
            docxs.append(value)
    return pdfs, docxs


def application_entry(doc, method, source_url):
    """An official notice must explicitly name the HTTPS registration link and steps."""
    if not re.search(r'系统|平台|在线|链接|网站|网报', method):
        if not extract.EMAIL.search(method):
            raise ValueError('申请方式缺少明确提交入口')
        return ''
    from crawler.opportunity_review import institution
    candidates = set()
    explicit = set()
    for link in doc['links']:
        if link['url'] in method or link['label'] and link['label'] in method and re.search(r'报名|申请|系统|平台', link['label']):
            if re.search(r'登录|登陆|提交|填写|注册|报名|申请', method):
                institution(link['url'])
                if urlsplit(link['url']).scheme != 'https':
                    raise ValueError('报名系统仅支持官方正文指向的HTTPS公开入口')
                candidates.add(link['url'])
                if any(link['url'] in line and re.search(r'报名网址|报名入口|申请入口|申请网址', line)
                       for line in method.splitlines()):
                    explicit.add(link['url'])
    if explicit:
        candidates = explicit
    if len(candidates) != 1:
        raise ValueError('报名系统入口不唯一或不是明确官方链接，需核对完整步骤')
    return next(iter(candidates))
