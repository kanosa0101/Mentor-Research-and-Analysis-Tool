"""Bounded official DOCX evidence. Parsing never executes or extracts files."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path
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


def linked_docx(raw, source_url):
    """Read public DOCX links without executing site scripts."""
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
    return urls


def linked_office(raw, source_url):
    soup = BeautifulSoup(raw, 'html.parser')
    result = {url: 'docx' for url in linked_docx(raw, source_url)}
    for tag in soup.select('a[href]'):
        match = re.search(r'\.(docx?|xlsx)(?:\b|[?#])', tag['href'] + ' ' + tag.get_text(' ', strip=True), re.I)
        if match:
            result[urljoin(source_url, tag['href'])] = match[1].lower()
    return result


def validate_links(value, raw, source_url):
    """Require the reviewed attachments to remain linked by the official notice."""
    if value and linked_office(raw, source_url) != {a['url']: a.get('format', 'docx') for a in value}:
        raise AttachmentChanged('Office附件链接或格式变化，须重新核验')


def official_url(url, source_url):
    from crawler.opportunity_review import institution
    if not isinstance(url, str) or urlsplit(url).scheme != 'https' or institution(url) != institution(source_url):
        raise ValueError('DOCX须为同机构HTTPS官方链接')


def validate_metadata(value, source_url):
    if not isinstance(value, list) or len(value) > 5:
        raise ValueError('DOCX附件须为至多5份文件的列表')
    urls = set()
    for attachment in value:
        if not isinstance(attachment, dict) or set(attachment) - {'url', 'sha256', 'checked_at', 'field_evidence', 'format'} or not {'url', 'sha256', 'checked_at', 'field_evidence'} <= set(attachment):
            raise ValueError('DOCX附件字段不完整')
        if attachment.get('format', 'docx') not in ('docx', 'doc', 'xlsx'):
            raise ValueError('Office附件格式尚不支持')
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


def parse_xlsx(raw):
    """Read every visible sheet/cell; hidden, calculated or embedded content is not silently dropped."""
    from openpyxl import load_workbook
    if not isinstance(raw, bytes) or not raw.startswith(b'PK') or len(raw) > MAX_BYTES:
        raise ValueError('XLSX文件无效或超过3MB上限')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files = archive.infolist()
            if len(files) > 512 or sum(f.file_size for f in files) > MAX_EXPANDED or len({f.filename for f in files}) != len(files) or any(f.flag_bits & 1 for f in files):
                raise ValueError('XLSX包含加密、重复或超量内容')
            names = archive.namelist()
            if any(re.search(r'vbaProject|externalLinks/|embeddings/|drawings/|media/|pivot|queryTable|connections', name, re.I) for name in names):
                raise ValueError('XLSX含宏、外部数据、图形或嵌入对象，需补充核验')
            if any(b'TargetMode="External"' in archive.read(name) or b"TargetMode='External'" in archive.read(name) for name in names if name.endswith('.rels')):
                raise ValueError('XLSX含外部链接，需核对关联证据')
        workbook = load_workbook(io.BytesIO(raw), data_only=False, keep_links=True)
        if len(workbook.worksheets) > 20 or workbook.defined_names:
            raise ValueError('XLSX工作表过多或含命名表达式，需核对完整范围')
        output, sheets = [], []
        for sheet in workbook:
            if sheet.sheet_state != 'visible' or any(d.hidden for d in sheet.row_dimensions.values()) or any(d.hidden for d in sheet.column_dimensions.values()):
                raise ValueError('XLSX含隐藏工作表、行或列，不能忽略后发布')
            if sheet.max_row * sheet.max_column > 20000 or sheet.auto_filter.ref:
                raise ValueError('XLSX范围过大或有筛选条件，需核验完整表格')
            lines, cells = [], []
            for row in sheet:
                for cell in row:
                    if cell.data_type in ('f', 'e') or cell.hyperlink:
                        raise ValueError('XLSX含公式、错误值或外链，不能用缓存结果替代条件')
                    if cell.value is None and not cell.comment:
                        continue
                    value = str(cell.value) if cell.value is not None else ''
                    merged = next((str(area) for area in sheet.merged_cells.ranges if cell.coordinate in area), cell.coordinate)
                    text = f'{merged}：{value}'
                    if cell.comment:
                        text += '\n批注：' + cell.comment.text
                    cells.append(dict(locator=merged, text=value, comment=cell.comment.text if cell.comment else ''))
                    lines.append(text)
            output.append('工作表：' + sheet.title + '\n' + '\n'.join(lines))
            sheets.append(dict(name=sheet.title, cells=cells))
        text = '\n'.join(output)
        if not any(sheet['cells'] for sheet in sheets):
            raise ValueError('XLSX未取得可核对单元格')
        return dict(text=text, sheets=sheets)
    except (zipfile.BadZipFile, KeyError, RuntimeError, UnicodeError) as error:
        raise ValueError('XLSX文件损坏或无法解析') from error


def _formatting_data_only(data):
    """Accept complete MS-DOC PrcData paragraph/table properties, not arbitrary Data streams."""
    offset = 0
    while offset < len(data) and any(data[offset:]):
        if offset + 2 > len(data):
            return False
        length = int.from_bytes(data[offset:offset+2], 'little', signed=True)
        offset += 2
        if not 0 < length <= 0x3FA2 or offset + length > len(data):
            return False
        end = offset + length
        while offset < end:
            if offset + 2 > end:
                return False
            modifier = int.from_bytes(data[offset:offset+2], 'little')
            offset += 2
            # Character/picture modifiers and unknown long table definitions remain unsupported.
            if (modifier >> 10) & 7 not in (1, 5) or modifier in (0xD606, 0xD608):
                return False
            size = (1, 1, 2, 4, 2, 2, None, 3)[modifier >> 13]
            if size is None:
                if offset >= end:
                    return False
                size = data[offset] + 1
            offset += size
            if offset > end:
                return False
    return True


def parse_doc(raw):
    """Use the distribution antiword reader; never start Word or execute macros."""
    import olefile
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or not raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        raise ValueError('旧DOC不是受支持的Word二进制文件或超过3MB上限')
    with olefile.OleFileIO(io.BytesIO(raw)) as document:
        streams = document.listdir()
        if any(any(re.search(r'VBA|Macros|ObjectPool|EncryptionInfo|EncryptedPackage', part, re.I) for part in parts) for parts in streams):
            raise ValueError('旧DOC含宏、加密或嵌入对象，不能自动核验')
        if not document.exists('WordDocument'):
            raise ValueError('旧DOC未找到Word正文流')
        header = document.openstream('WordDocument').read(32)
        if len(header) < 12 or header[:2] != b'\xec\xa5' or int.from_bytes(header[10:12], 'little') & 0x8100:
            raise ValueError('旧DOC正文无效、加密或混淆，不能自动核验')
        data = document.openstream('Data').read() if document.exists('Data') else b''
        if int.from_bytes(header[10:12], 'little') & 8 or not _formatting_data_only(data):
            raise ValueError('旧DOC含图片或附加对象流，文本不足以证明完整内容')
        body = document.openstream('WordDocument').read()
        if re.search(r'\b(?:INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|HYPERLINK)\b', body.decode('utf-16-le', errors='ignore') + body.decode('latin1'), re.I):
            raise ValueError('旧DOC含外部域或链接，需核对关联证据')
    executable = shutil.which('antiword')
    limiter = shutil.which('prlimit')
    if not executable or not limiter:
        raise ValueError('缺少antiword或受限转换工具，等待后台安装后重试')
    with tempfile.TemporaryDirectory(prefix='official-doc-') as folder:
        path = Path(folder) / 'source.doc'
        path.write_bytes(raw)
        outputs = []
        try:
            for option in ([], ['-s'], ['-r']):
                output = Path(folder) / 'text.xml'
                with output.open('wb') as stdout, (Path(folder) / 'error.log').open('wb') as stderr:
                    subprocess.run([limiter, '--as=268435456', '--cpu=5', '--fsize=16777216', '--nofile=32', '--',
                                    executable, '-m', 'UTF-8.txt', '-x', 'db', *option, str(path)],
                                   stdout=stdout, stderr=stderr, timeout=6, check=True)
                outputs.append(output.read_bytes())
        except (subprocess.SubprocessError, OSError) as error:
            raise ValueError('旧DOC转换失败或超时，未取得完整可核验文本') from error
    if len(outputs[0]) > MAX_EXPANDED:
        raise ValueError('旧DOC提取内容超过上限')
    if any(value != outputs[0] for value in outputs[1:]):
        raise ValueError('旧DOC含隐藏文字或修订删除内容，需核对生效版本')
    xml = re.sub(br'<!DOCTYPE[^>]*>', b'', outputs[0])
    try:
        doc = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ValueError('旧DOC转换输出不完整') from error
    if any(node.tag.lower() in ('graphic', 'imagedata', 'inlinegraphic', 'mediaobject') for node in doc.iter()):
        raise ValueError('旧DOC仍有未提取的图片证据')
    # DocBook book/bookinfo titles are legacy file properties, not visible pages.
    # Body chapter titles and all body paragraphs retain their original order.
    paragraphs = [''.join(node.itertext()).strip() for chapter in doc.findall('chapter')
                  for node in chapter.iter() if node.tag in ('para', 'title')]
    text = '\n'.join(value for value in paragraphs if value)
    if len(''.join(text.split())) < 2:
        raise ValueError('旧DOC未取得可核对正文')
    return dict(text=text, paragraphs=paragraphs, extraction='antiword-docbook')


def parse_office(raw, kind):
    if kind not in ('docx', 'doc', 'xlsx'):
        raise ValueError('不支持的Office附件格式')
    return {'docx': parse_docx, 'doc': parse_doc, 'xlsx': parse_xlsx}[kind](raw)


def fetch_office(url, source_url, kind='docx'):
    return _fetch(url, source_url, kind)


def fetch_docx(url, source_url):
    return _fetch(url, source_url, 'docx')


def _fetch(url, source_url, kind):
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
                parse_office(raw, kind)
                return raw
        raise ValueError('DOCX重定向次数过多')


def verify(value, source_url, fetcher=None):
    validate_metadata(value, source_url)
    results = []
    for attachment in value:
        kind = attachment.get('format', 'docx')
        raw = fetcher(attachment['url'], source_url) if fetcher else fetch_office(attachment['url'], source_url, kind)
        if hashlib.sha256(raw).hexdigest() != attachment['sha256']:
            raise AttachmentChanged('DOCX版本变化，须重新核验附件SHA和字段摘录')
        parsed = parse_office(raw, kind)
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
