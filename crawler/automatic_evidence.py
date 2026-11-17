"""Complete, bounded public evidence for automatic review; no OCR or form submission."""
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import requests
import yaml

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


def fetch_image(url, source_url):
    """Only small, same-institution HTTPS image bytes; never follow an external hop."""
    attachments.official_url(url, source_url)
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(4):
            attachments.official_url(url, source_url)
            with session.get(url, timeout=(10, 15), stream=True, allow_redirects=False) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 2_000_000:
                        raise EvidenceError('image_evidence_required', '正文图片超过2MB，需核验图中信息')
                    chunks.append(chunk)
                return b''.join(chunks)
    raise ValueError('正文图片重定向次数过多')


def qr_target(raw):
    from PIL import Image
    import zxingcpp
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.format not in ('PNG', 'JPEG') or getattr(picture, 'n_frames', 1) != 1 or picture.width * picture.height > 1_000_000:
            raise EvidenceError('qr_evidence_required', '二维码图片格式或尺寸不支持完整自动核验')
        found = zxingcpp.read_barcodes(picture, formats=zxingcpp.BarcodeFormat.QRCode)
        if len(found) != 1 or not found[0].valid:
            raise EvidenceError('qr_evidence_required', '正文二维码未能唯一解码')
        position = found[0].position
        points = [position.top_left, position.top_right, position.bottom_left, position.bottom_right]
        left, top = min(p.x for p in points), min(p.y for p in points)
        right, bottom = max(p.x for p in points), max(p.y for p in points)
        # Reject posters with text alongside the QR, even when their URL matches.
        pixels = picture.convert('RGB')
        for box in [(0, 0, picture.width, top), (0, bottom + 1, picture.width, picture.height),
                    (0, top, left, bottom + 1), (right + 1, top, picture.width, bottom + 1)]:
            if box[2] > box[0] and box[3] > box[1] and any(low < 245 for low, _ in pixels.crop(box).getextrema()):
                raise EvidenceError('qr_evidence_required', '二维码外还有图像内容，不能仅解码后忽略申请信息')
    return found[0].text


def plain_urls(text):
    return set(re.findall(r'https://[^\s<>（）()，。；;"\u201c\u201d\u4e00-\u9fff]+', text))


def reviewed_media(content, source_url, folder, kind):
    """Reuse an explicit visual audit only for identical bytes at the audited source."""
    if folder is None:
        return None
    cache = next((p for p in list(Path(folder).resolve().parents)[:3] if p.name == 'cache'), None)
    path = cache.parent / 'sites/evidence_media.yaml' if cache else None
    if path is None or not path.is_file() or path.is_symlink():
        return None
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise ValueError('图片核验台账版本无效')
    digest = hashlib.sha256(content).hexdigest()
    for entry in data.get('images', []):
        if (entry.get('sha256') == digest and entry.get('kind') == kind and source_url in entry.get('source_urls', [])
                and entry.get('reviewer') and date.fromisoformat(entry['reviewed_at'])):
            return {key: entry[key] for key in ('sha256', 'kind', 'reviewer', 'reviewed_at', 'description')}
    return None


def image_evidence(image, source_url, *, image_fetcher, folder, article_title):
    """A decoded duplicate URL or a separately labelled past-event gallery is not a condition image."""
    parent = image.parent
    previous = parent.find_previous_sibling()
    context = previous.get_text(' ', strip=True) if previous else ''
    url = urljoin(source_url, image.get('src', ''))
    plain = not image.get('alt', '').strip() and not image.get('title', '').strip() and not image.get('usemap') and not image.find_parent(['a', 'figure'])
    # The gallery must be the final article block, with a dedicated retrospective caption.
    title_years = set(re.findall(r'20\d{2}', article_title))
    gallery = (plain and re.fullmatch(r'20\d{2}年?.{0,20}(?:夏令营|冬令营|培训班)精彩瞬间', extract.compact(context))
               and parent.find_next_sibling() is None and len(title_years) == 1
               and int(context.strip()[:4]) < int(next(iter(title_years))))
    qr = plain and re.search(r'扫描下方二维码|扫码', context) and len(plain_urls(context)) == 1
    if not (gallery or qr):
        return None
    content = image_fetcher(url, source_url)
    sha = hashlib.sha256(content).hexdigest()
    if qr:
        target = qr_target(content)
        if target not in plain_urls(context):
            raise EvidenceError('qr_evidence_required', '二维码实际入口与相邻官方文字链接不同，未自动发布')
        result = dict(url=url, sha256=sha, kind='verified_duplicate_qr', target=target, quote=context)
    else:
        audited = reviewed_media(content, source_url, folder, 'historical_photos')
        if not audited:
            raise EvidenceError('image_evidence_required', '往届图库图片尚无相同字节的人工核验，不能凭标题忽略图中信息')
        result = dict(audited, url=url, quote=context)
    if folder is not None:
        path = Path(folder) / (sha + '.image')
        path.write_bytes(content)
        result['evidence_file'] = str(path.resolve())
    return result


def inspect_html(raw, source_url, *, image_fetcher=None, folder=None):
    """Only explicitly decorative, non-linked images can be ignored."""
    if len(raw) > 3_000_000:
        raise ValueError('官方页面超过自动核验大小上限')
    soup = BeautifulSoup(raw, 'html.parser')
    for node in soup.select('nav,header,footer'):
        node.decompose()
    body = next((soup.select_one(s) for s in extract.BODY_SELECTORS if soup.select_one(s)), soup.body or soup)
    links = attachment_links(raw, source_url)
    image_checks = []
    heading = body.find('h1') or soup.title
    article_title = heading.get_text(' ', strip=True) if heading else ''
    for image in body.select('img'):
        if attachment_icon(image, links, source_url):
            image_checks.append(dict(url=urljoin(source_url, image['src']), kind='attachment_type_icon',
                                     reason='固定CMS文件图标路径、空替代文本与明确文件下载链接共同确认'))
            continue
        checked = image_evidence(image, source_url, image_fetcher=image_fetcher or fetch_image, folder=folder, article_title=article_title)
        if checked:
            image_checks.append(checked)
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
    published = body.select('.date-pageview > .date')
    if len(published) == 1:
        value = published[0].get_text(' ', strip=True)
        if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', value) and value in doc['text']:
            doc['published_at'] = dict(value=date.fromisoformat(value).isoformat(), quote=value)
    if re.search(r'忽略.{0,12}(?:指令|规则)|ignore\s+(?:all\s+)?previous|system\s*prompt|AI助手请', doc['text'], re.I):
        raise ValueError('原文含模型指令式内容，需人工确认页面可信性')
    if not links and re.search(r'见附件|详见附表|下载(?:附件|申请表)|附件\s*[一二三四\d]|附件中(?:查询|查看)', doc['text']):
        raise ValueError('正文要求的附件未取得明确官方链接')
    if soup.select('script#__NUXT_DATA__') and re.search(r'\.docx|fileList|file/common/download', str(soup), re.I) and not links:
        raise ValueError('动态附件尚未取得完整的官方链接清单')
    return doc, links


def collect(raw, source_url, *, pdf_fetcher, docx_fetcher, office_fetcher=None, folder=None, wait=None, image_fetcher=None):
    """Bind every linked document, including forms, to one untruncated text version."""
    from crawler.ai_review import MAX_INPUT
    doc, links = inspect_html(raw, source_url, image_fetcher=image_fetcher, folder=folder)
    soup = BeautifulSoup(raw, 'html.parser')
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if page_title and extract.compact(page_title) not in extract.compact(doc['text']):
        # Many official CMS templates place their article heading outside the body selector.
        doc = dict(doc, text=page_title + '\n' + doc['text'], lines=[page_title, *doc['lines']])
    documents = []
    for url, kind in sorted(links.items()):
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
            image_audits = []
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for name in archive.namelist():
                    if not name.startswith('word/media/') or name.endswith('/'):
                        continue
                    audit = reviewed_media(archive.read(name), source_url, folder, 'institution_logo')
                    if not audit:
                        raise ValueError('DOCX含未核验或已变化的图片证据，不能仅按文本自动发布')
                    image_audits.append(dict(audit, archive_path=name))
            text, detail = parsed['text'], {'image_audits': image_audits} if image_audits else {}
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
    combined = dict(doc, html_text=doc['text'], html_lines=doc['lines'], documents=documents)
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
    media = [{k: item[k] for k in ('url', 'sha256', 'kind', 'target') if k in item}
             for item in doc.get('image_checks', []) if item.get('sha256')]
    if media:
        combined['content_sha256'] = hashlib.sha256(json.dumps([combined['content_sha256'], media], sort_keys=True).encode()).hexdigest()
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


MATERIALS_REFERENCE = re.compile(r'(?:申请|报名|提交)?材料(?:清单|要求)?(?:请)?(?:详)?见(?:官方)?附件[。.]?')


def supplement_materials(doc, parts, section_parser):
    """Resolve a bare reference to a uniquely identified linked materials section."""
    def reference(line):
        return MATERIALS_REFERENCE.fullmatch(extract.compact(line))

    if not any(reference(line) for line in doc.get('html_lines', [])):
        return
    materials = parts.get('materials', '').splitlines()
    if materials and not (len(materials) <= 2 and reference(materials[-1]) and (
            len(materials) == 1 or re.fullmatch(r'(?:[一二三四五六七八九十\d]+[、.．])?\s*(?:申请|报名)材料[：:]?', materials[0].strip()))):
        return
    matches = []
    for document in doc.get('documents', []):
        lines = [line for line in document['text'].splitlines() if line.strip()]
        value = section_parser(lines).get('materials')
        # Exact heading alone or another file reference does not close evidence.
        if value and len(extract.compact(value)) >= 12 and not any(reference(line) for line in value.splitlines()):
            matches.append(value)
    if len(matches) != 1:
        raise EvidenceError('materials_attachment_unresolved', '材料仅指向附件，未取得唯一且完整的官方材料栏目')
    parts['materials'] = matches[0]


def application_entry(doc, method, source_url):
    """An official notice must explicitly name the HTTPS registration link and steps."""
    if not re.search(r'系统|平台|在线|链接|网站|网报|问卷', method):
        if not extract.EMAIL.search(method):
            raise ValueError('申请方式缺少明确提交入口')
        return ''
    candidates = set()
    explicit = set()
    links = [*doc['links'], *(dict(url=url, label='') for url in plain_urls(method) if url in doc['text'])]
    for link in links:
        if link['url'] in method or link['label'] and link['label'] in method and re.search(r'报名|申请|系统|平台', link['label']):
            if re.search(r'登录|登陆|提交|填写|注册|报名|申请', method):
                registration_url(link['url'])
                candidates.add(link['url'])
                if any(link['url'] in line and re.search(r'报名网站|报名网址|报名入口|申请网站|申请入口|申请网址', line)
                       for line in method.splitlines()):
                    explicit.add(link['url'])
    if explicit:
        candidates = explicit
    if len(candidates) != 1:
        raise ValueError('报名系统入口不唯一或不是明确官方链接，需核对完整步骤')
    return next(iter(candidates))


def registration_url(url):
    from crawler.opportunity_review import institution
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('报名系统仅支持官方正文指向的HTTPS公开入口')
    if parsed.hostname == 'wj.qq.com' and re.fullmatch(r'/s2/[A-Za-z0-9/_-]+/?', parsed.path):
        return 'official_linked_questionnaire'
    institution(url)
    return 'institution'


def verify_application_entry(url, source_url, *, fetcher):
    """Probe the already source-bound public entry, without registering or submitting."""
    if registration_url(url) == 'institution':
        fetcher({'url': url})
        return
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(4):
            if registration_url(url) != 'official_linked_questionnaire':
                raise ValueError('报名问卷跳转到未核验入口')
            with session.get(url, timeout=(10, 15), allow_redirects=False, stream=True) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('报名问卷未返回可访问入口')
                total = 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 2_000_000:
                        raise ValueError('报名问卷页面超过自动核验大小上限')
                return
    raise ValueError('报名问卷重定向次数过多')
