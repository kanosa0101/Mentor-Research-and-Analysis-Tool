"""Bounded official DOCX evidence. Parsing never executes or extracts files."""
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

MAX_BYTES = 3 * 1024 * 1024
MAX_EXPANDED = 16 * 1024 * 1024
FIELDS = {'eligibility', 'materials', 'application_method', 'contact', 'research_directions',
          'deadline', 'registration_start', 'event_start', 'event_end', 'deadline_note'}


class AttachmentChanged(ValueError):
    pass


def validate_links(value, raw, source_url):
    """Require the reviewed attachments to remain linked by the official notice."""
    if not value:
        return
    soup = BeautifulSoup(raw, 'html.parser')
    urls = {urljoin(source_url, a['href']) for a in soup.select('a[href]')
            if '.docx' in a['href'].lower() or '.docx' in a.get_text().lower()}
    # CIBR renders download buttons from public Nuxt data, not ordinary anchors.
    if urlsplit(source_url).hostname == 'cibr.ac.cn':
        node = soup.select_one('script#__NUXT_DATA__')
        if node:
            data = json.loads(node.string or '')
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name, ident = item.get('name'), item.get('id')
                    if type(name) is int and type(ident) is int and 0 <= name < len(data) and 0 <= ident < len(data):
                        if isinstance(data[name], str) and data[name].lower().endswith('.docx') and isinstance(data[ident], str) and re.fullmatch('[a-f0-9]{32}', data[ident]):
                            urls.add('https://cibr.ac.cn/file/common/download/' + data[ident])
    if urls != {a['url'] for a in value}:
        raise AttachmentChanged('DOCX链接列表变化或附件不在当前官方公告中，须重新核验')


def official_url(url, source_url):
    from crawler.opportunity_review import institution
    if not isinstance(url, str) or urlsplit(url).scheme != 'https' or institution(url) != institution(source_url):
        raise ValueError('DOCX须为同机构HTTPS官方链接')


def validate_metadata(value, source_url):
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError('DOCX附件须为至多5份文件的列表')
    urls = set()
    for attachment in value:
        if not isinstance(attachment, dict) or set(attachment) != {'url', 'sha256', 'checked_at', 'field_evidence'}:
            raise ValueError('DOCX附件字段不完整')
        official_url(attachment['url'], source_url)
        if attachment['url'] in urls:
            raise ValueError('DOCX附件地址重复')
        urls.add(attachment['url'])
        if not isinstance(attachment['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', attachment['sha256']):
            raise ValueError('DOCX版本摘要无效')
        if not isinstance(attachment['checked_at'], str):
            raise ValueError('DOCX核验日期无效')
        date.fromisoformat(attachment['checked_at'])
        fields = attachment['field_evidence']
        if not isinstance(fields, dict) or not fields or set(fields) - FIELDS:
            raise ValueError('DOCX字段摘录无效')
        for evidence in fields.values():
            if not isinstance(evidence, dict) or set(evidence) != {'quote', 'locator'}:
                raise ValueError('DOCX字段须提供摘录和定位')
            if any(not isinstance(evidence[k], str) or not evidence[k].strip() or len(evidence[k]) > limit
                   for k, limit in [('quote', 6000), ('locator', 300)]):
                raise ValueError('DOCX摘录或定位长度无效')


def parse_docx(raw):
    if not isinstance(raw, bytes) or not raw.startswith(b'PK') or len(raw) > MAX_BYTES:
        raise ValueError('DOCX文件无效或超过3MB上限')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) > 512 or sum(f.file_size for f in files) > MAX_EXPANDED:
                raise ValueError('DOCX解压内容超出安全上限')
            if len({f.filename for f in files}) != len(files) or any(f.flag_bits & 1 for f in files):
                raise ValueError('DOCX包含重复或加密内容')
            if '[Content_Types].xml' not in archive.namelist() or 'word/document.xml' not in archive.namelist():
                raise ValueError('附件不是DOCX文档')
            xml = archive.read('word/document.xml').decode('utf-8-sig')
            if re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.I):
                raise ValueError('DOCX含不支持的XML实体声明')
            document = ElementTree.fromstring(xml)
            ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = [''.join(t.text or '' for t in node.findall('.//w:t', ns)) for node in document.findall('.//w:p', ns)]
            text = '\n'.join(paragraphs)
            if len(''.join(text.split())) < 2:
                raise ValueError('DOCX未取得可核对正文')
            return dict(text=text, paragraphs=paragraphs)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, RuntimeError, UnicodeError, NotImplementedError) as error:
        raise ValueError('DOCX文件损坏或无法解析') from error


def fetch_docx(url, source_url):
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(5):
            official_url(url, source_url)
            with session.get(url, timeout=25, stream=True, allow_redirects=False,
                             headers={'User-Agent': 'Mozilla/5.0 (admissions attachment review)', 'Referer': source_url}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                if response.status_code != 200 or int(response.headers.get('Content-Length', '0')) > MAX_BYTES:
                    raise ValueError('DOCX请求失败或超过3MB上限')
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise ValueError('DOCX超过3MB上限')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                parse_docx(raw)
                return raw
        raise ValueError('DOCX重定向次数过多')


def verify(value, source_url, fetcher=None):
    validate_metadata(value, source_url)
    results = []
    for attachment in value:
        raw = (fetcher or fetch_docx)(attachment['url'], source_url)
        if hashlib.sha256(raw).hexdigest() != attachment['sha256']:
            raise AttachmentChanged('DOCX版本变化，须重新核验附件SHA和字段摘录')
        parsed = parse_docx(raw)
        text = ''.join(parsed['text'].split())
        for field, evidence in attachment['field_evidence'].items():
            if ''.join(evidence['quote'].split()) not in text:
                raise ValueError(f'DOCX的{field}摘录不在当前附件正文')
        results.append(dict(url=attachment['url'], sha256=attachment['sha256'], **parsed))
    return results


def source_version(content_sha256, value):
    """An attachment change must prevent renewal even when the HTML is unchanged."""
    if not value:
        return content_sha256
    versions = sorted((a['url'], a['sha256']) for a in value)
    return hashlib.sha256((content_sha256 + '\n' + json.dumps(versions)).encode()).hexdigest()
