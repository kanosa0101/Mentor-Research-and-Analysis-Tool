import hashlib
import io

import pytest
import yaml
from PIL import Image, ImageDraw
import zxingcpp

from crawler import automatic_evidence as evidence

SOURCE = 'https://example.edu.cn/notice/2027.htm'
ENTRY = 'https://wj.qq.com/s2/123456/abcd/'


def qr_bytes(target=ENTRY, poster=False):
    code = zxingcpp.create_barcode(target, zxingcpp.BarcodeFormat.QRCode)
    rendered = Image.fromarray(code.to_image(scale=5)).convert('RGB')
    if poster:
        image = Image.new('RGB', (rendered.width, rendered.height + 45), 'white')
        image.paste(rendered, (0, 45))
        ImageDraw.Draw(image).text((4, 8), 'Requires a separate application', fill='black')
        rendered = image
    output = io.BytesIO()
    rendered.save(output, 'PNG')
    return output.getvalue()


def page(image, caption=None):
    caption = caption or f'点击报名链接（{ENTRY}）或扫描下方二维码，填写个人信息。'
    return (f'<article><h1>2027年大学生冬令营</h1><p>面向本科生报名，完整申请条件及材料以官方通知为准。</p>'
            f'<p>{caption}</p><p><img src="{image}"></p></article>').encode()


def test_duplicate_qr_is_decoded_and_bound(tmp_path):
    raw = qr_bytes()
    doc, _ = evidence.inspect_html(page('/qr.png'), SOURCE, image_fetcher=lambda *_: raw, folder=tmp_path)
    check = doc['image_checks'][0]
    assert check['target'] == ENTRY and check['sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('raw', [qr_bytes('https://wj.qq.com/s2/9999/other/'), qr_bytes(poster=True)])
def test_mismatched_or_poster_qr_blocks(raw):
    with pytest.raises(evidence.EvidenceError):
        evidence.inspect_html(page('/qr.png'), SOURCE, image_fetcher=lambda *_: raw)


def media_root(tmp_path, content, kind='historical_photos'):
    folder = tmp_path / 'cache/opportunity_evidence'
    folder.mkdir(parents=True)
    (tmp_path / 'sites').mkdir()
    record = dict(sha256=hashlib.sha256(content).hexdigest(), kind=kind, source_urls=[SOURCE],
                  reviewer='test-reviewer', reviewed_at='2026-11-17', description='Already inspected image bytes')
    (tmp_path / 'sites/evidence_media.yaml').write_text(yaml.safe_dump({'version': 1, 'images': [record]}), encoding='utf-8')
    return folder


def test_gallery_needs_exact_source_and_previously_reviewed_bytes(tmp_path):
    content = b'test visually reviewed fixture'
    folder = media_root(tmp_path, content)
    raw = page('/past.png', '2026冬季培训班精彩瞬间')
    assert evidence.inspect_html(raw, SOURCE, image_fetcher=lambda *_: content, folder=folder)[0]['image_checks'][0]['kind'] == 'historical_photos'
    for source, body in [(SOURCE, b'changed image'), ('https://other.edu.cn/notice.htm', content)]:
        with pytest.raises(evidence.EvidenceError):
            evidence.inspect_html(raw, source, image_fetcher=lambda *_: body, folder=folder)


@pytest.mark.parametrize('caption', ['2026冬季培训班精彩瞬间', '2027冬季培训班精彩瞬间', '2028冬季培训班精彩瞬间'])
def test_gallery_caption_alone_is_never_sufficient(caption):
    with pytest.raises(evidence.EvidenceError):
        evidence.inspect_html(page('/photo.png', caption), SOURCE, image_fetcher=lambda *_: b'image')


def test_plain_text_registration_link_is_explicit_and_source_bound():
    method = '报名网站：https://admission.example.edu.cn/applications/\n模板下载：https://example.edu.cn/templates/'
    assert evidence.application_entry({'links': [], 'text': method}, method, SOURCE) == 'https://admission.example.edu.cn/applications/'
    assert evidence.application_entry({'links': [], 'text': '点击问卷链接' + ENTRY + '填写报名信息'}, '点击问卷链接' + ENTRY + '填写报名信息', SOURCE) == ENTRY
    with pytest.raises(ValueError):
        evidence.application_entry({'links': [], 'text': '原文没有报名URL'}, method, SOURCE)


@pytest.mark.parametrize('url', ['http://wj.qq.com/s2/123/abc/', 'https://wj.qq.com.evil.test/s2/123/abc/',
    'https://user@wj.qq.com/s2/123/abc/', 'https://wj.qq.com/other', 'https://127.0.0.1/s2/123/abc/'])
def test_arbitrary_external_registration_urls_are_rejected(url):
    with pytest.raises(ValueError):
        evidence.registration_url(url)


def test_publication_date_is_source_metadata_not_fetch_time():
    raw = b'<article><h1>Application notice</h1><div class="date-pageview"><span class="date">2026-11-02</span></div><p>Application materials are required for all students in this admission process.</p></article>'
    # Keep this test about metadata, with a genuine Chinese application body.
    raw = raw.replace(b'Application materials', '申请材料'.encode())
    doc, _ = evidence.inspect_html(raw, SOURCE)
    assert doc['published_at'] == {'value': '2026-11-02', 'quote': '2026-11-02'}


def test_attachment_iteration_order_does_not_change_ai_input(monkeypatch):
    from zipfile import ZipFile
    def attachment(text):
        stream = io.BytesIO()
        with ZipFile(stream, 'w') as z:
            z.writestr('[Content_Types].xml', '<Types/>')
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        return stream.getvalue()
    raw = '<article><p>冬令营申请材料及条件请完整核对，报名须提交个人陈述和申请表。</p></article>'.encode()
    urls = ['https://example.edu.cn/a.docx', 'https://example.edu.cn/b.docx']
    blobs = dict(zip(urls, [attachment('First official form'), attachment('Second official form')]))
    outputs = []
    for order in (urls, list(reversed(urls))):
        monkeypatch.setattr(evidence, 'attachment_links', lambda *_: dict.fromkeys(order, 'docx'))
        outputs.append(evidence.collect(raw, SOURCE, pdf_fetcher=None, docx_fetcher=lambda u, _: blobs[u]))
    assert outputs[0]['text'] == outputs[1]['text']
    assert outputs[0]['content_sha256'] == outputs[1]['content_sha256']
    assert [d['url'] for d in outputs[0]['documents']] == urls
