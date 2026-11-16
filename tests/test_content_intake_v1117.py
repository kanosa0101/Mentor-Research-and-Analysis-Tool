import hashlib
import io
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import Workbook

from crawler import automatic_evidence as evidence, opportunity_attachments as attachments
from crawler import policy_intake as intake, quality_status

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
URL = 'https://cs.example.edu.cn/info/123.htm'


def save(root, path, value):
    path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def row(title='2027年博士研究生招生说明', **kwargs):
    return dict(url=URL, source='https://cs.example.edu.cn/list.htm', title=title,
                school='example', dept='cs', first_seen='2026-11-14', **kwargs)


def test_all_candidates_registered_before_bounded_attempts_and_keep_discovery_clock(tmp_path):
    state = {'records': {}}
    pool = [dict(row(), url=URL + str(n)) for n in range(161)]
    intake.register_candidates(tmp_path, pool, state, NOW)
    assert len(state['records']) == 161
    assert {r['status'] for r in state['records'].values()} == {'queued'}
    assert {r['first_seen'] for r in state['records'].values()} == {'2026-11-13T16:00:00+00:00'}
    save(tmp_path, 'cache/policy_intake/state.json', state)
    result = quality_status.refresh(tmp_path, NOW)
    assert result['summary']['new_policies'] == result['summary']['overdue'] == 161
    intake.register_candidates(tmp_path, pool, state, NOW + timedelta(days=1))
    assert {r['pending_since'] for r in state['records'].values()} == {'2026-11-13T16:00:00+00:00'}


def test_current_sha_bound_old_title_archives_without_attachment_fetch(tmp_path):
    source = row('2025年博士研究生招生说明')
    raw = ('<title>' + source['title'] + '</title><article><h1>' + source['title'] +
           '</h1><p>本校2025年博士研究生招生，报名条件与材料见附件。</p></article>').encode()
    digest = hashlib.sha256(raw).hexdigest()
    folder = tmp_path / 'cache/opportunity_evidence'
    folder.mkdir(parents=True)
    (folder / (digest + '.html')).write_bytes(raw)
    save(tmp_path, 'cache/opportunity_review.json', {'version': 1, 'drafts': [{
        'id': 'a', 'source_url': URL, 'listing_url': source['source'],
        'fetch': {'checked_at': NOW.isoformat(), 'sha256': digest}}]})
    state = {'records': {}}
    intake.register_candidates(tmp_path, [source], state, NOW)
    assert state['records'][URL]['status'] == 'historical'
    (folder / (digest + '.html')).write_bytes(b'changed')
    state = {'records': {}}
    intake.register_candidates(tmp_path, [source], state, NOW)
    assert state['records'][URL]['status'] == 'queued'


def test_title_change_reopens_but_preserves_original_discovery(tmp_path):
    state = {'records': {}}
    intake.register_candidates(tmp_path, [row()], state, NOW)
    first = state['records'][URL]['first_seen']
    state['records'][URL]['status'] = 'historical'
    intake.register_candidates(tmp_path, [row('2028年博士研究生招生说明')], state, NOW + timedelta(days=1))
    assert state['records'][URL]['status'] == 'queued'
    assert state['records'][URL]['first_seen'] == first
    assert state['records'][URL]['pending_since'] == (NOW + timedelta(days=1)).isoformat()


def test_proven_deadline_precedes_current_cycle_and_hyphen_does_not_drop_time():
    parts = {'application_method': '报名时间：2026年10月26日9:00-11月25日17:00\n接收截止时间：2026年11月27日中午12:00'}
    assert [e['at'] for e in intake.deadline_events(parts)] == ['2026-11-25T17:00:00+08:00', '2026-11-27T12:00:00+08:00']
    with pytest.raises(ValueError):
        intake.deadline_events({'application_method': '报名时间：2026年10月26日至11月25日下午5:00'})
    a, b = row(), dict(row(), url=URL+'2')
    state = {'records': {r['url']: {'first_seen': NOW.isoformat()} for r in (a,b)}}
    state['records'][b['url']]['source_hints'] = {'deadline_hint': {'at': '2026-11-20T17:00:00+08:00'}}
    assert intake.candidate_priority(b,state,NOW) < intake.candidate_priority(a,state,NOW)


def test_only_bound_filetype_icon_is_decorative_and_qr_has_distinct_reason():
    raw = b'<article><p>Official application notice with complete materials.</p><a href="form.doc"><img src="/system/resource/images/fileTypeImages/icon_doc.gif">form.doc</a></article>'
    doc, links = evidence.inspect_html(raw, URL)
    assert links and doc['image_checks'][0]['kind'] == 'attachment_type_icon'
    with pytest.raises(evidence.EvidenceError) as err:
        evidence.inspect_html(raw.replace(b'icon_doc.gif', b'poster.gif'), URL)
    assert err.value.code == 'image_evidence_required'
    with pytest.raises(evidence.EvidenceError) as err:
        evidence.inspect_html(b'<article><p>Application details</p><img src="qrcode.png"></article>', URL)
    assert err.value.code == 'qr_evidence_required'


def xlsx(change=None):
    book = Workbook(); sheet = book.active
    sheet['A1'] = '申请表'; sheet['A2'] = '姓名'; sheet.merge_cells('A1:C1')
    if change: change(book, sheet)
    output = io.BytesIO(); book.save(output)
    return output.getvalue()


def test_xlsx_keeps_coordinates_and_merged_ranges():
    doc = attachments.parse_xlsx(xlsx())
    assert 'A1:C1' in doc['text'] and '申请表' in doc['text']
    assert doc['sheets'][0]['cells']


def test_real_whu_form_preserves_source_cells():
    raw=(Path(__file__).parent/'fixtures/policy_intake/whu-language-form.xlsx').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='b72c8034bd0289ab1bdafc317387eb21475b1827c103958049c3fbdf34e97e36'
    doc=attachments.parse_xlsx(raw)
    assert 'B1：姓名' in doc['text'] and '一作只认排在第一的作者' in doc['text']
    assert len(doc['text'])==645


def test_real_doc_rejects_no_hidden_content_and_retains_template_year():
    if not shutil.which('antiword') or not shutil.which('prlimit') or getattr(os,'geteuid',lambda:0)()==0:
        pytest.skip('real legacy DOC conversion requires unprivileged Linux with antiword/prlimit')
    raw=(Path(__file__).parent/'fixtures/policy_intake/xmu-linked-self-statement.doc').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='2756040d77883ea124909660bb8afca055fe2e5c8b3d20f4b1a85cf44c2f10a6'
    doc=attachments.parse_doc(raw)
    assert doc['text'].startswith('厦门大学2025年考生自述表')
    assert '考生签名' in doc['text']


@pytest.mark.parametrize('change', [lambda b,s: s.__setitem__('B2','=1+2'),
    lambda b,s: setattr(s.row_dimensions[2],'hidden',True),
    lambda b,s: setattr(s['A2'],'hyperlink','https://example.com')])
def test_xlsx_rejects_hidden_formula_or_external_link(change):
    with pytest.raises(ValueError): attachments.parse_xlsx(xlsx(change))


def test_doc_data_only_accepts_complete_paragraph_table_properties():
    assert attachments._formatting_data_only(b'\x03\x00\x00\x24\x01' + b'\x00'*5)
    assert not attachments._formatting_data_only(b'\x03\x00\x00\x24')
    assert not attachments._formatting_data_only(b'\x03\x00\x00\x2c\x01')
    with pytest.raises(ValueError): attachments.parse_doc(b'<html>challenge</html>')


def test_xlsx_complete_evidence_and_metadata_bind_file_version(tmp_path):
    raw = b'<title>Application notice</title><article><p>Complete official application details.</p><a href="/form.xlsx">form.xlsx</a></article>'
    content = xlsx()
    doc = evidence.collect(raw, URL, pdf_fetcher=lambda *a: pytest.fail(), docx_fetcher=lambda *a: pytest.fail(),
                           office_fetcher=lambda *a: content, folder=tmp_path)
    _, office = evidence.metadata(doc, '2026-11-17')
    attachments.validate_metadata(office, URL)
    attachments.validate_links(office, raw, URL)
    assert office[0]['format'] == 'xlsx' and office[0]['sha256'] == hashlib.sha256(content).hexdigest()
    changed = evidence.collect(raw, URL, pdf_fetcher=lambda *a: pytest.fail(), docx_fetcher=lambda *a: pytest.fail(),
                               office_fetcher=lambda *a: xlsx(lambda b,s: s.__setitem__('B3','新增条件')))
    assert changed['content_sha256'] != doc['content_sha256']
    with pytest.raises(attachments.AttachmentChanged):
        attachments.validate_links(office, raw.replace(b'form.xlsx',b'new.xlsx'), URL)


def test_field_gap_monitoring_counts_fields_and_does_not_nag_waiting_source(tmp_path):
    opened = (NOW-timedelta(days=10)).isoformat()
    waiting = dict(status='waiting_source', reason_code='not_found_in_checked_source', first_seen=opened,
                   pending_since=opened, checked_at=NOW.isoformat(), next_check_at=(NOW+timedelta(days=30)).isoformat())
    save(tmp_path,'cache/mentor_quality/field-gaps.json',{'records': {
        'a': {'name':'甲','unit':'school/cs','fields': {'email':waiting, 'title':dict(waiting,status='resolved')}},
        'b': {'name':'乙','unit':'school/cs','fields': {'email':dict(waiting,status='pending'), 'supervisor':waiting}}}})
    value = quality_status.refresh(tmp_path,NOW)
    assert value['summary']['missing_fields'] == 3 and value['summary']['mentor_field_gaps'] == 2
    by_id = {r['id']: r for r in value['active']}
    assert by_id['mentor_fields:a']['overdue'] is False and by_id['mentor_fields:a']['due_at'] is None
    assert by_id['mentor_fields:b']['overdue'] is True
    assert value['mentor_field_breakdown']['by_unit'] == {'school/cs':3}


def test_field_inventory_has_age_but_sla_starts_after_first_check(tmp_path):
    first = (NOW-timedelta(days=100)).isoformat()
    path='cache/mentor_quality/field-gaps.json'
    record={'name':'甲','fields':{'email':dict(status='pending',reason_code='not_checked',first_seen=first,pending_since=first)}}
    save(tmp_path,path,{'records':{'a':record}})
    result=quality_status.refresh(tmp_path,NOW)
    row=result['active'][0]
    assert row['status']=='queued' and row['priority']==3 and not row['overdue']
    assert row['discovered_at']==first and not result['incomplete'] and result['breakdown']['never_attempted']==1
    record['fields']['email'].update(status='waiting_source',checked_at=NOW.isoformat(),next_check_at=(NOW-timedelta(hours=1)).isoformat())
    save(tmp_path,path,{'records':{'a':record}})
    assert not quality_status.refresh(tmp_path,NOW)['active'][0]['overdue']
    later=quality_status.refresh(tmp_path,NOW+timedelta(hours=2))['active'][0]
    assert later['status']=='maintenance_overdue' and later['overdue']
