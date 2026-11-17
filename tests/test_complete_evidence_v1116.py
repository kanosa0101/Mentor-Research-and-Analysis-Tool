import copy
import hashlib
import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from crawler import automatic_evidence as evidence, automatic_review as automatic, opportunity_review as review
from crawler import opportunity_util as util, policy_intake
from test_automatic_review_v18 import CONFIGS, HTML, NOW, URL, accepted, setup


def docx(text='申请表：姓名、所读专业、本人签名。', picture=False):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr(zipfile.ZipInfo('[Content_Types].xml'), '<Types/>')
        archive.writestr(zipfile.ZipInfo('word/document.xml'), '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
        if picture:
            archive.writestr(zipfile.ZipInfo('word/media/figure.png'), b'not-decoded')
    return out.getvalue()


def test_docx_and_online_entry_can_publish_with_complete_bound_evidence(setup):
    root, queue, _ = setup
    raw = HTML.replace('请将全部申请材料合并PDF发送至 camp@example.edu.cn。'.encode(),
        '<a href="https://apply.example.edu.cn/registration">网上报名系统</a>：请注册并填写报名信息，上传全部申请材料。'.encode())
    raw = raw.replace(b'</article>', '<a href="/form.docx">下载申请表.docx</a></article>'.encode())
    calls = []
    def fetch(config):
        calls.append(config['url'])
        return b'<html>Login</html>' if config['url'].endswith('/registration') else raw
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=accepted, fetcher=fetch, docx_fetcher=lambda *a: docx())
    assert result['state'] == 'published', result
    item = util.load(root)['opportunities'][0]
    assert item['application_url'] == 'https://apply.example.edu.cn/registration'
    assert item['source_attachments'][0]['sha256'] == hashlib.sha256(docx()).hexdigest()
    assert len(item['materials']) == 1  # Forms remain in expandable source details.
    assert calls.count(item['application_url']) == 1
    assert review.status(review.read_queue(queue)['drafts'][0]) == 'published'


def test_attachment_change_between_ai_and_publish_never_publishes(setup):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', '<a href="/form.docx">申请表.docx</a></article>'.encode())
    count = 0
    def attachment(*args):
        nonlocal count
        count += 1
        return docx() if count == 1 else docx('申请表：须提供新材料和签章。')
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=accepted, fetcher=lambda _: raw, docx_fetcher=attachment)
    assert result['state'] == 'manual_required' and '版本' in result['reasons'][0]
    assert not (root / 'data/opportunities.json').exists()


def test_changed_attachment_does_not_reuse_previous_ai_decision(setup):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', '<a href="/form.docx">申请表.docx</a></article>'.encode())
    calls = []
    def checker(*args):
        calls.append(1)
        return accepted(*args)
    for content in (docx(), docx('申请表：姓名、身份证号码、本人签名。')):
        result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
            publish=False, now=NOW, checker=checker, fetcher=lambda _: raw, docx_fetcher=lambda *a: content)
        assert result['state'] == 'eligible', result
    assert len(calls) == 2


@pytest.mark.parametrize('addition', [
    '<img src="requirements.png">', '<img role="presentation" alt="报名条件" src="a.png">',
    '<a href="/x"><img role="presentation" alt="" src="a.png"></a>', '<iframe src="/unknown"></iframe>',
    '<a href="/x.xls">申请表.xls</a>', '<p>申请表见附件。</p>',
])
def test_unverified_images_and_documents_stop_before_ai(setup, addition):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', addition.encode() + b'</article>')
    result = automatic.process(root, queue, review.read_queue(queue)['drafts'][0], CONFIGS,
        publish=True, now=NOW, checker=lambda *a: pytest.fail('incomplete source reached AI'), fetcher=lambda _: raw)
    assert result['state'] == 'manual_required'


def test_explicitly_decorative_image_does_not_block_complete_text(setup):
    _, _, process = setup
    raw = HTML.replace(b'</article>', b'<img role="presentation" alt="" src="divider.png"></article>')
    assert process(raw=raw)['state'] == 'published'


def test_docx_embedded_image_is_not_treated_as_complete_text():
    raw = HTML.replace(b'</article>', b'<a href="/form.docx">form.docx</a></article>')
    with pytest.raises(ValueError, match='图片'):
        evidence.collect(raw, URL, pdf_fetcher=lambda *a: pytest.fail(), docx_fetcher=lambda *a: docx(picture=True))


def test_linked_pdf_is_complete_version_evidence(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
    out = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 750 Td (Application materials: CV and signed student registration form.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(out)
    raw = HTML.replace(b'</article>', b'<a href="/form.pdf">application form.pdf</a></article>')
    document = evidence.collect(raw, URL, pdf_fetcher=lambda *a: out.getvalue(), docx_fetcher=lambda *a: pytest.fail(), folder=tmp_path)
    assert document['documents'][0]['page_count'] == 1
    assert document['documents'][0]['sha256'] == hashlib.sha256(out.getvalue()).hexdigest()
    assert document['content_sha256'] != review.extraction.document(raw, URL)['content_sha256']


def test_scan_pdf_is_not_automatic_evidence():
    from pypdf import PdfWriter
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    raw = HTML.replace(b'</article>', b'<a href="/form.pdf">form.pdf</a></article>')
    with pytest.raises(ValueError, match='PDF'):
        evidence.collect(raw, URL, pdf_fetcher=lambda *a: output.getvalue(), docx_fetcher=lambda *a: pytest.fail())


POLICY_TITLE = '示例大学计算机学院2027年博士研究生申请考核招生简章'
POLICY_HTML = HTML.decode().replace('2027年计算机冬令营', POLICY_TITLE).replace(
    '计算机相关专业本科生可申请。', '申请考核面向取得硕士学位的申请人。').replace(
    '仅限本校学生，不接受已毕业申请人。', '须提供硕士学位证明和本科阶段成绩单。').encode()


@pytest.fixture
def policy_setup(setup):
    root, queue, _ = setup
    queue.unlink()
    (root / 'sites/notices.yaml').write_text(yaml.safe_dump({'targets': CONFIGS}), encoding='utf8')
    (root / 'data/notices.json').write_text(json.dumps({'notices': [dict(title=POLICY_TITLE, url=URL,
        source=CONFIGS[0]['url'], school='example', dept='cs', publication_date='2026-11-01')]}), encoding='utf8')
    (root / 'data/admissions.yaml').write_text(yaml.safe_dump(dict(version=1, policies=[], sources={})), encoding='utf8')
    return root


def test_new_policy_creates_conditions_action_and_deadline_then_is_idempotent(policy_setup):
    root = policy_setup
    result = policy_intake.run(root, now=NOW, fetcher=lambda _: POLICY_HTML, checker=accepted)
    assert result['published'] == 1, result
    data = yaml.safe_load((root / 'data/admissions.yaml').read_text(encoding='utf8'))
    policy = data['policies'][0]
    assert policy['year'] == 2027 and policy['route'] == 'assessment' and policy['degree'] == 'phd'
    assert set(policy['fields']) == {'eligibility', 'materials', 'timeline', 'contact'}
    assert policy['events'][0]['at'] == '2026-11-30T17:00:00+08:00'
    assert policy['material_actions'][0]['event_indexes'] == [0]
    assert policy_intake.run(root, now=NOW, fetcher=lambda _: pytest.fail('duplicate fetched'), checker=accepted)['attempted'] == 0


def test_new_policy_rejects_ai_bound_to_other_proposed_values(policy_setup):
    def mismatched(*args):
        ai = accepted(*args)
        ai['input_fields_sha256'] = '0' * 64
        return ai
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=mismatched)
    assert result['published'] == 0 and result['manual_required'] == 1


def test_new_policy_preserves_existing_scope_and_all_manual_values(policy_setup):
    root = policy_setup
    policy_intake.run(root, now=NOW, fetcher=lambda _: POLICY_HTML, checker=accepted)
    path = root / 'data/admissions.yaml'
    data = yaml.safe_load(path.read_text(encoding='utf8'))
    old = copy.deepcopy(data['policies'][0])
    data['sources'][old['source_id']]['url'] = URL + '?old=true'
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf8')
    before = path.read_bytes()
    result = policy_intake.run(root, now=NOW + timedelta(days=2), fetcher=lambda _: POLICY_HTML,
                              checker=lambda *a: pytest.fail('conflicting policy reached AI'))
    assert result['manual_required'] == 1 and path.read_bytes() == before


def test_new_policy_rechecks_original_before_writing(policy_setup):
    calls = 0
    def fetch(_):
        nonlocal calls
        calls += 1
        return POLICY_HTML if calls == 1 else POLICY_HTML.replace(b'17:00', b'18:00')
    result = policy_intake.run(policy_setup, now=NOW, fetcher=fetch, checker=accepted)
    assert result['manual_required'] == 1
    assert yaml.safe_load((policy_setup / 'data/admissions.yaml').read_text())['policies'] == []


def test_new_policy_budget_wait_does_not_publish_or_reset_budget(policy_setup):
    def limited(*a):
        raise ValueError('已达到AI每日调用上限；未发出新请求')
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=limited)
    assert result['budget_wait'] == 1 and result['published'] == 0
    assert yaml.safe_load((policy_setup / 'data/admissions.yaml').read_text())['policies'] == []


@pytest.mark.parametrize('replacement', [
    ('2027年博士', '2026年博士'), ('申请考核面向', '申请考核与推荐免试面向'),
    ('五、报名时间', '五、注意事项'), ('2026年11月30日17:00', '2026年10月30日17:00'),
])
def test_historical_ambiguous_or_missing_policy_stays_unpublished(policy_setup, replacement):
    raw = POLICY_HTML.decode().replace(*replacement).encode()
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: raw,
                              checker=lambda *a: pytest.fail('unclear policy reached AI'))
    expected = 'historical' if replacement[1] == '2026年10月30日17:00' else 'manual_required'
    assert result['counts'][expected] == 1 and result['published'] == 0


def test_real_pku_policy_keeps_nested_materials_both_deadlines_and_external_pdf(tmp_path):
    from crawler import admissions_util, ai_review
    fixture = Path(__file__).parent / 'fixtures/policy_intake'
    provenance = json.loads((fixture / 'provenance.json').read_text(encoding='utf8'))
    raw, pdf = (fixture / 'pku-2027-phd.html').read_bytes(), (fixture / 'pku-2027-institutes.pdf').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == provenance['files'][0]['sha256']
    assert hashlib.sha256(pdf).hexdigest() == provenance['files'][1]['sha256']
    (tmp_path / 'data').mkdir()
    (tmp_path / 'sites/pku').mkdir(parents=True)
    (tmp_path / 'data/schools.yaml').write_text(yaml.safe_dump({'schools': [{'id': 'pku', 'name': '北京大学'}]}, allow_unicode=True), encoding='utf8')
    (tmp_path / 'sites/pku/cs.yaml').write_text(yaml.safe_dump(dict(school='pku', dept='cs', dept_name='计算机学院'), allow_unicode=True), encoding='utf8')
    row = dict(url=provenance['source_url'], title='北京大学计算机学院2027年“申请-考核制” 博士研究生招生说明',
               school='pku', dept='cs', publication_date='2026-10-26')
    doc = evidence.collect(raw, row['url'], pdf_fetcher=lambda url, source: pdf if url == provenance['attachment_url'] else pytest.fail('unbound PDF'), docx_fetcher=lambda *a: pytest.fail())
    proposed = policy_intake.prepare(tmp_path, row, raw, doc, NOW)
    policy = proposed['policy']
    assert policy['review_method'] == 'automatic_evidence'
    assert '四、违规处理' in policy['fields']['exams']['text']
    assert proposed['checks']['attachment_0']['value'] == proposed['checks']['attachment_0']['quote']
    assert [(e['label'], e['at']) for e in policy['events']] == [
        ('网上报名截止', '2026-11-26T17:00:00+08:00'), ('申请材料送达截止', '2026-11-30T12:00:00+08:00')]
    assert '525' in policy['fields']['materials']['text'] and '450' in policy['fields']['materials']['text']
    assert 'EMS' in policy['material_actions'][0]['instruction']['text']
    assert '以寄达时间为准' in policy['material_actions'][0]['instruction']['text']
    assert '昌平区' in policy['fields']['tuition']['text']
    assert proposed['checks']['tuition']['value'] == policy['fields']['tuition']['text']
    assert len(policy['review_hashes']) == 2 and proposed['application_url'] == 'https://admission.pku.edu.cn/applications/'
    admissions_util.validate(dict(version=1, sources=proposed['sources'], policies=[policy]), {'pku': {'cs'}})
    # This validates the protocol only; it does not stand in for a real AI review.
    response = accepted(tmp_path, row['url'], doc['text'], proposed['checks'])
    ai_review.validate({key: response[key] for key in ('decision', 'issues', 'checks')}, doc['text'], proposed['checks'])


@pytest.mark.parametrize('window', [
    '报名时间：2026年10月27日至11月26日下午5:00',
    '报名时间：2026年10月27日至11月26日（北京时间17:00）',
    '报名时间：2026年10月27日至11月26日17:00:30',
    '报名截止：2026年11月26日（北京时间17:00）',
    '报名时间：2026年10月27日至11/26 17:00',
    '报名截止：2026年11月26日17:00 GMT',
])
def test_deadline_never_silently_drops_unsupported_time(window):
    with pytest.raises(ValueError):
        policy_intake.deadline_events(dict(timeline=window, application_method='请按官方系统提交。'))


def test_same_year_range_preserves_chinese_hour_expression():
    rows = policy_intake.deadline_events(dict(timeline='报名时间：2026年10月27日至11月26日17时30分', application_method='请按官方系统提交。'))
    assert rows[0]['at'] == '2026-11-26T17:30:00+08:00'


def test_real_pdf_table_preserves_drawn_rowspans_and_every_character():
    from crawler.pdf_layout import complete_pages
    from crawler.opportunity_extract import pdf_document
    fixture = Path(__file__).parent / 'fixtures/policy_intake/pku-2027-institutes.pdf'
    raw = fixture.read_bytes()
    parsed = pdf_document(raw, 'https://cs.pku.edu.cn/list.pdf')
    pages = complete_pages(raw, parsed['pages'])
    assert [p['page'] for p in pages] == [1, 2]
    assert all(p['text_coverage'] == 'all_nonwhitespace_characters' for p in pages)
    cells = pages[0]['cells']
    institute = next(c for c in cells if c['text'] == '软件研究所')
    code = next(c for c in cells if c['text'] == '101001')
    assert institute['rows'] == code['rows'] == [2, 9]
    assert institute['columns'] == [1, 1] and code['columns'] == [2, 2]
    assert '王捍\n贫' in pages[0]['text']  # Preserve the actual cell wrap; no guessed name normalization.
    corrupt = copy.deepcopy(parsed['pages'])
    corrupt[0]['text'] += '漏字'
    with pytest.raises(ValueError, match='文字覆盖'):
        complete_pages(raw, corrupt)


def test_pdf_table_never_discards_text_outside_cells(monkeypatch):
    from crawler.pdf_layout import complete_pages
    from crawler.opportunity_extract import pdf_document
    import pdfplumber.page
    raw = (Path(__file__).parent / 'fixtures/policy_intake/pku-2027-institutes.pdf').read_bytes()
    parsed = pdf_document(raw, 'https://cs.pku.edu.cn/list.pdf')
    original = pdfplumber.page.Page.find_tables
    def partial(page):
        tables = original(page)
        tables[0].cells.pop()
        return tables
    monkeypatch.setattr(pdfplumber.page.Page, 'find_tables', partial)
    with pytest.raises(ValueError, match='表格外'):
        complete_pages(raw, parsed['pages'])


def test_ai_manual_diagnostic_is_saved_before_refusal(policy_setup):
    def manual(*args):
        value = accepted(*args)
        value.update(decision='manual', issues=['原文内部条件需核对'], elapsed_seconds=5.1)
        value['checks'][0]['consistent'] = False
        return value
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=manual)
    record = json.loads((policy_setup / 'cache/policy_intake/state.json').read_text(encoding='utf8'))['records'][URL]
    assert result['published'] == 0 and record['ai']['decision'] == 'manual'
    assert record['ai']['elapsed_seconds'] == 5.1 and record['ai']['issues'] == ['原文内部条件需核对']


def test_healthy_empty_round_writes_observable_state(policy_setup):
    (policy_setup / 'data/notices.json').write_text('{"notices": []}', encoding='utf8')
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: pytest.fail(), checker=accepted)
    state = json.loads((policy_setup / 'cache/policy_intake/state.json').read_text(encoding='utf8'))
    assert result['attempted'] == 0 and state == dict(version=1, checked_at=NOW.isoformat(), records={})


@pytest.mark.parametrize('status', ['manual_required', 'retry', 'budget_wait'])
def test_version_upgrade_only_reopens_manual_not_cooling_service_calls(policy_setup, status):
    path = policy_setup / 'cache/policy_intake/state.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = dict(status=status, title=POLICY_TITLE, first_seen=NOW.isoformat(), policy_version='old-policy-version',
                    next_attempt_at=(NOW + timedelta(hours=24)).isoformat())
    path.write_text(json.dumps(dict(version=1, records={URL: previous})), encoding='utf8')
    fetcher = (lambda _: POLICY_HTML) if status == 'manual_required' else lambda _: pytest.fail('cooldown bypassed')
    result = policy_intake.run(policy_setup, now=NOW, fetcher=fetcher, checker=accepted)
    assert result['attempted'] == (1 if status == 'manual_required' else 0)


def test_historical_policy_archives_without_sla_and_rechecks_after_seven_days(policy_setup):
    raw = POLICY_HTML.decode().replace('2026年11月30日17:00', '2026年10月30日17:00').encode()
    result = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: raw, checker=lambda *a: pytest.fail())
    assert result['counts'] == {'historical': 1} and result['pending'] == 0
    record = result['results'][0]
    assert record['reason_code'] == 'historical_window' and 'pending_since' not in record
    assert record['next_attempt_at'] == (NOW + timedelta(days=7)).isoformat()
    assert policy_intake.run(policy_setup, now=NOW + timedelta(days=6), fetcher=lambda _: pytest.fail())['attempted'] == 0
    assert policy_intake.run(policy_setup, now=NOW + timedelta(days=7), fetcher=lambda _: raw)['attempted'] == 1


def test_budget_wait_retries_at_shared_utc_reset_not_twenty_four_hours(policy_setup):
    from datetime import timezone
    late = NOW.replace(hour=23, minute=51).astimezone(timezone(timedelta(hours=8)))
    def limited(*args):
        raise ValueError('已达到AI每日调用上限；未发出新请求')
    result = policy_intake.run(policy_setup, now=late, fetcher=lambda _: POLICY_HTML, checker=limited)
    expected = (NOW + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0).isoformat()
    assert result['results'][0]['next_attempt_at'] == expected


def test_retry_progresses_two_four_eight_sixteen_twenty_four_hours(policy_setup):
    now = NOW
    def broken(*args):
        raise OSError('official source temporarily unavailable')
    for count, hours in enumerate([2, 4, 8, 16, 24, 24], 1):
        result = policy_intake.run(policy_setup, now=now, fetcher=broken, checker=lambda *a: pytest.fail())
        record = result['results'][0]
        assert record['status'] == 'retry' and record['failure_count'] == count
        assert record['next_attempt_at'] == (now + timedelta(hours=hours)).isoformat()
        now += timedelta(hours=hours)
    result = policy_intake.run(policy_setup, now=now, publish=False, fetcher=lambda _: POLICY_HTML, checker=accepted)
    assert result['counts'] == {'eligible': 1} and result['results'][0]['failure_count'] == 0


def _manual_result(*args):
    result = accepted(*args)
    result.update(decision='manual', issues=['需人工核对原文适用条件和招生周期'])
    result['checks'][0]['consistent'] = False
    return result


def test_unchanged_complete_manual_decision_refetches_without_ai_even_after_fetch_failure(policy_setup):
    first = policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=_manual_result)
    assert first['manual_required'] == 1 and first['results'][0]['proposal_sha256']
    def unavailable(*args):
        raise OSError('source briefly unavailable')
    second = policy_intake.run(policy_setup, now=NOW + timedelta(days=1), fetcher=unavailable)
    assert second['retry'] == 1
    fetched = []
    def fetch(config):
        fetched.append(config['url'])
        return POLICY_HTML
    third = policy_intake.run(policy_setup, now=NOW + timedelta(days=1, hours=2), fetcher=fetch,
                             checker=lambda *a: pytest.fail('unchanged manual decision consumed AI'))
    assert fetched == [URL] and third['manual_required'] == 1
    assert third['results'][0]['ai_reused'] is True and third['results'][0]['failure_count'] == 0


@pytest.mark.parametrize('changed', ['raw', 'combined', 'input', 'proposal', 'version'])
def test_changed_manual_evidence_or_proposal_requires_new_ai(policy_setup, monkeypatch, changed):
    policy_intake.run(policy_setup, now=NOW, fetcher=lambda _: POLICY_HTML, checker=_manual_result)
    raw = POLICY_HTML
    if changed == 'raw':
        raw += b'\n'
    elif changed in ('combined', 'input'):
        original = policy_intake.collect
        def collect(*args):
            doc = original(*args)
            if changed == 'combined':
                doc['content_sha256'] = 'changed-attachment-hash'
            else:
                doc['text'] += '\n '
            return doc
        monkeypatch.setattr(policy_intake, 'collect', collect)
    elif changed == 'proposal':
        original = policy_intake.prepare
        def prepare(*args):
            proposed = original(*args)
            proposed['checks']['scope']['value']['program'] = ''
            return proposed
        monkeypatch.setattr(policy_intake, 'prepare', prepare)
    else:
        monkeypatch.setattr(policy_intake, 'VERSION', 'new-intake-rule-version')
    calls = []
    def checker(*args):
        calls.append(1)
        return _manual_result(*args)
    result = policy_intake.run(policy_setup, now=NOW + timedelta(days=1), fetcher=lambda _: raw, checker=checker)
    assert calls == [1] and result['manual_required'] == 1 and not result['results'][0]['ai_reused']
