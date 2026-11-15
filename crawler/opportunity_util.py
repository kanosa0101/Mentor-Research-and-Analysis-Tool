"""Public camp opportunities and explicit, atomic saves to the local workspace."""
import copy
import json
import os
import re
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
import requests

from crawler import project_util as projects, contact_util as contact, workflow_util as core

KINDS = {'winter_camp': '冬令营', 'summer_camp': '夏令营', 'recommend': '预推免', 'research_program': '科研实践'}
TEXT = {'id', 'title', 'school_id', 'school_name', 'dept_id', 'unit', 'kind',
        'published_at', 'verified_at', 'source_url', 'application_url', 'application_method',
        'registration_start', 'deadline', 'deadline_note', 'event_start', 'event_end',
        'admission_note', 'contact', 'source_state', 'source_note', 'cycle', 'source_sha256', 'checked_at'}
YEARS = {'camp_year', 'graduation_year', 'admission_year'}
LISTS = {'eligibility', 'materials', 'evidence'}
OPTIONAL = {'research_directions', 'source_content_sha256', 'source_documents',
            'application_window', 'source_attachments', 'content_classification',
            'mentor_ids', 'mentor_identity_evidence'}
CONTENT_SCOPES = {'institutional_activity', 'mentor_recruitment', 'admission_notice', 'pending'}
INSTITUTIONS = {'school_department', 'research_institute', 'university_research_institute'}
PERSONAL = {'individual_team', 'individual_lab'}


def content_scope(item):
    """One public admission gate; absent or invalid classification always fails closed."""
    try:
        validate_classification(item)
    except (ValueError, TypeError, KeyError):
        return 'pending'
    return item.get('content_classification', {}).get('scope', 'pending')


def validate_classification(item, source_text=None, require_publishable=False):
    classification = item.get('content_classification')
    if classification is None:
        if require_publishable:
            raise ValueError('须先核对内容归类、实际组织者及官方依据，未发布')
        return
    keys = {'scope', 'organizer_level', 'organizer_name', 'source_url', 'quote', 'verified_at'}
    if not isinstance(classification, dict) or set(classification) != keys or any(not isinstance(v, str) for v in classification.values()):
        raise ValueError('内容归类字段不完整')
    scope, level = classification['scope'], classification['organizer_level']
    if scope not in CONTENT_SCOPES or level not in INSTITUTIONS | PERSONAL | {'unknown'}:
        raise ValueError('内容归类或组织层级无效')
    if scope == 'pending':
        if require_publishable:
            raise ValueError('内容仍待核验，不能发布为活动或导师招募')
        return
    if (not all(classification[k].strip() for k in keys) or classification['source_url'] != item.get('source_url') or
            scope in ('institutional_activity', 'admission_notice') and level not in INSTITUTIONS or
            scope == 'mentor_recruitment' and level not in PERSONAL):
        raise ValueError('内容归类与实际组织者或原文依据不一致')
    if scope == 'institutional_activity' and item.get('kind') == 'recommend':
        raise ValueError('正式招生通知不能归为营或机构活动')
    if date.fromisoformat(classification['verified_at']) > today():
        raise ValueError('归类核验日期不能在未来')
    if source_text is not None and ''.join(classification['quote'].split()) not in ''.join(source_text.split()):
        raise ValueError('内容归类依据不能在当前官方正文中定位')


def public_catalog(catalog):
    """Keep stable IDs reachable while only institution activities enter activity results."""
    result = copy.deepcopy(catalog)
    records = {item['id']: item for item in result.get('opportunities', []) + result.get('other_contents', [])}
    result['opportunities'] = [item for item in records.values() if content_scope(item) == 'institutional_activity']
    result['other_contents'] = [item for item in records.values() if content_scope(item) != 'institutional_activity']
    result['content_scope_version'] = 1
    monitoring = result.get('monitoring')
    if isinstance(monitoring, dict):
        # Unreviewed discoveries remain maintenance leads, never counted as activity opportunities.
        monitoring['candidates'] = [c for c in monitoring.get('candidates', []) if content_scope(c) == 'institutional_activity']
    return result


def validate_mentor_links(root, item, source_text):
    """Publishing a personal tag requires the actual directory identity, never a name match alone."""
    import yaml
    for evidence in item.get('mentor_identity_evidence', []):
        parts = evidence['mentor_id'].split('-', 2)
        if len(parts) != 3:
            raise ValueError('导师关联ID无法定位现有目录')
        path = Path(root) / 'data/professors' / parts[0] / parts[1] / (parts[2] + '.yaml')
        if not path.is_file():
            raise ValueError('关联导师尚未入库，保留待关联招募')
        mentor = yaml.safe_load(path.read_text(encoding='utf-8'))
        quote = ''.join(evidence['quote'].split())
        if (evidence['source_url'] != item['source_url'] or quote not in ''.join(source_text.split()) or
                mentor.get('school') != item['school_id'] or mentor.get('dept') != item['dept_id'] or
                not mentor.get('name') or not mentor.get('email') or
                any(''.join(value.split()) not in quote for value in (mentor['name'], mentor['email'], item['school_name']))):
            raise ValueError('导师身份须有同校、院系、姓名及本人公开邮箱的当前原文依据')


def today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def validate(item):
    if not isinstance(item, dict) or set(item) - OPTIONAL != TEXT | YEARS | LISTS:
        raise ValueError('活动资料字段不完整')
    if any(not isinstance(item[k], str) for k in TEXT) or not all(item[k].strip() for k in ('id', 'title', 'unit', 'source_url', 'verified_at')) or item['kind'] not in KINDS:
        raise ValueError('活动名称、类别或来源错误')
    for key in YEARS:
        if item[key] is not None and (type(item[key]) is not int or not 2000 <= item[key] <= 2100):
            raise ValueError('活动、毕业及入学年份须独立登记')
    for key in ('published_at', 'verified_at', 'checked_at', 'registration_start', 'event_start', 'event_end'):
        if item[key]:
            date.fromisoformat(item[key])
    if item['deadline']:
        if len(item['deadline']) == 10:
            date.fromisoformat(item['deadline'])
        elif datetime.fromisoformat(item['deadline']).tzinfo is None:
            raise ValueError('精确截止时间必须含时区')
    for key in ('source_url', 'application_url'):
        if item[key]:
            url = urlsplit(item[key])
            if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
                raise ValueError('活动来源或报名地址错误')
    for key in LISTS:
        if not isinstance(item[key], list) or any(not isinstance(v, str) or not v.strip() for v in item[key]):
            raise ValueError('活动条件、材料与依据须为文字列表')
    if not item['evidence']:
        raise ValueError('活动须保留核对依据')
    if item['source_state'] not in ('verified', 'unavailable'):
        raise ValueError('活动来源状态错误')
    if item['cycle'] not in ('current', 'historical'):
        raise ValueError('活动轮次状态错误')
    validate_classification(item)
    ids, identities = item.get('mentor_ids', []), item.get('mentor_identity_evidence', [])
    if (not isinstance(ids, list) or
            any(not isinstance(v, str) or not re.fullmatch(r'[a-z0-9_-]+', v) for v in ids) or len(ids) != len(set(ids)) or
            not isinstance(identities, list)):
        raise ValueError('导师关联字段无效')
    if any(not isinstance(v, dict) or set(v) != {'mentor_id', 'source_url', 'quote', 'verified_at'} or
           any(not isinstance(s, str) or not s.strip() for s in v.values()) for v in identities):
        raise ValueError('导师关联须保留官方身份依据')
    if set(ids) != {v['mentor_id'] for v in identities} or len(ids) != len(identities):
        raise ValueError('导师关联与身份依据不一致')
    for evidence in identities:
        if urlsplit(evidence['source_url']).scheme not in ('https', 'http'):
            raise ValueError('导师身份来源无效')
        date.fromisoformat(evidence['verified_at'])
    window = item.get('application_window')
    if window is not None:
        if (not isinstance(window, dict) or set(window) != {'mode', 'end_month', 'quote'} or
                any(not isinstance(value, str) for value in window.values()) or
                window['mode'] not in ('rolling', 'month') or not window['quote'].strip() or item['deadline']):
            raise ValueError('持续申请或月份截止须有独立的官方原文依据，不能与具体截止混用')
        if window['mode'] == 'rolling' and window['end_month']:
            raise ValueError('长期招募不得臆造截止月份')
        if window['mode'] == 'month':
            if not re.fullmatch(r'(?:20\d{2}|2100)-(?:0[1-9]|1[0-2])', window['end_month']) or not item['registration_start']:
                raise ValueError('月份截止须明确年月与开始日期')
            if item['registration_start'][:7] > window['end_month']:
                raise ValueError('申请开始不能晚于截止月份')
    if 'source_attachments' in item:
        from crawler.opportunity_attachments import validate_metadata
        validate_metadata(item['source_attachments'], item['source_url'])
    if 'source_content_sha256' in item and not re.fullmatch(r'[a-f0-9]{64}', item['source_content_sha256']):
        raise ValueError('正文核验摘要错误')
    documents = item.get('source_documents', [])
    if not isinstance(documents, list) or len(documents) > 5:
        raise ValueError('PDF来源须为至多5个文件的列表')
    seen_documents = set()
    for document in documents:
        if not isinstance(document, dict) or set(document) != {'url', 'sha256', 'page_count', 'checked_at', 'field_evidence'}:
            raise ValueError('PDF来源字段不完整')
        url = urlsplit(document['url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or document['url'] in seen_documents:
            raise ValueError('PDF来源地址错误或重复')
        seen_documents.add(document['url'])
        if not isinstance(document['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', document['sha256']) or type(document['page_count']) is not int or not 1 <= document['page_count'] <= 100:
            raise ValueError('PDF版本或页数错误')
        date.fromisoformat(document['checked_at'])
        fields = document['field_evidence']
        if not isinstance(fields, dict) or not fields or set(fields) - (TEXT | YEARS | LISTS):
            raise ValueError('PDF字段证据错误')
        for evidence in fields.values():
            if not isinstance(evidence, dict) or set(evidence) != {'quote', 'pages'} or not isinstance(evidence['quote'], str) or not evidence['quote'].strip():
                raise ValueError('PDF摘录错误')
            pages = evidence['pages']
            if not isinstance(pages, list) or not pages or any(type(p) is not int or not 1 <= p <= document['page_count'] for p in pages) or pages != sorted(set(pages)):
                raise ValueError('PDF证据页码错误')
    directions = item.get('research_directions', [])
    if not isinstance(directions, list) or len(directions) > 500:
        raise ValueError('研究方向须为有出处的列表')
    for row in directions:
        fields = {'department', 'direction', 'contact', 'email', 'source_url', 'source_locator', 'verified_at'}
        if not isinstance(row, dict) or set(row) != fields or any(not isinstance(row[k], str) for k in fields):
            raise ValueError('研究方向字段不完整')
        if not all(row[k].strip() for k in ('department', 'direction', 'source_url', 'source_locator', 'verified_at')):
            raise ValueError('研究方向需要明确出处')
        url = urlsplit(row['source_url'])
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password:
            raise ValueError('研究方向来源错误')
        if row['email'] and not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", row['email']):
            raise ValueError('联系人邮箱格式错误')
        date.fromisoformat(row['verified_at'])


def load(root):
    path = Path(root) / 'data/opportunities.json'
    if not path.exists():
        return {'version': 1, 'checked_at': '', 'coverage_note': '尚未接入活动资料', 'opportunities': []}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('opportunities'), list):
        raise ValueError('活动目录结构错误')
    seen = set()
    for item in data['opportunities']:
        validate(item)
        if item['id'] in seen:
            raise ValueError('活动 ID 重复')
        seen.add(item['id'])
    return data


def observed(root):
    """Read the server catalog and monitoring health; never fetch a client mirror."""
    catalog = load(root)
    path = Path(root) / 'cache/opportunities_live.json'
    try:
        monitoring = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    except (OSError, ValueError):
        monitoring = {'status': 'error', 'error': '监测记录无法读取，请重新运行监测'}
    catalog['monitoring'] = monitoring
    overdue = False
    if monitoring:
        try:
            overdue = datetime.fromisoformat(monitoring['next_check_at']) < datetime.now(timezone.utc)
        except (KeyError, ValueError, TypeError):
            overdue = True
    for item in catalog['opportunities']:
        check = (monitoring or {}).get('opportunity_checks', {}).get(item['id'], {})
        if check.get('status') in ('changed', 'error', 'unbased'):
            item['source_state'] = 'unavailable'
            item['source_note'] += ' 最近监测发现页面变化或无法确认，原有摘要需重新核对。'
        elif check.get('status') == 'unchanged' and item['source_state'] == 'verified':
            item['checked_at'] = check.get('last_success', '')[:10]
        if overdue:
            item['source_state'] = 'unavailable'
            item['source_note'] += ' 监测已超过应检时间，不能确认当前报名状态。'
    return catalog


def remote_catalog(root, url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('更新服务地址无效')
    cache = Path(root) / 'cache/opportunities_remote.json'
    if cache.exists() and 0 <= time.time() - cache.stat().st_mtime < 300:
        data = json.loads(cache.read_text(encoding='utf-8'))
    else:
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(url, timeout=8)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('opportunities'), list):
            raise ValueError('更新服务资料结构错误')
        for item in data['opportunities'] + data.get('other_contents', []):
            validate(item)
        # Only retain public links in the discovery queue; never execute URL schemes.
        monitoring = data.get('monitoring')
        if monitoring and isinstance(monitoring, dict):
            monitoring['candidates'] = [c for c in monitoring.get('candidates', []) if isinstance(c, dict)
                and all(isinstance(c.get(k), str) for k in ('url', 'title', 'unit', 'first_seen'))
                and urlsplit(c['url']).scheme in ('http', 'https')]
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=cache.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False)
            os.replace(name, cache)
        finally:
            Path(name).unlink(missing_ok=True)
    # Public feeds separate display destinations; local saves still resolve every stable ID.
    merged = dict(data, opportunities=data['opportunities'] + data.get('other_contents', []), mode='local', feed_url=url)
    merged.pop('other_contents', None)
    return merged


def state(item, day=None):
    day = day or today()
    if item['cycle'] == 'historical':
        return 'closed'
    deadline = item['deadline']
    if deadline and (date.fromisoformat(deadline[:10]) < day or
                     len(deadline) > 10 and datetime.fromisoformat(deadline) < datetime.now(timezone.utc)):
        return 'closed'
    if item['event_end'] and date.fromisoformat(item['event_end']) < day:
        return 'closed'
    window = item.get('application_window', {})
    if not deadline and window.get('mode') == 'month' and day.isoformat()[:7] > window['end_month']:
        return 'closed'
    if item['source_state'] != 'verified' or not item['checked_at'] or not 0 <= (day - date.fromisoformat(item['checked_at'])).days <= 7 or not 0 <= (day - date.fromisoformat(item['verified_at'])).days <= 30:
        return 'review'
    if item['registration_start'] and date.fromisoformat(item['registration_start']) > day:
        return 'upcoming'
    if not deadline and window.get('mode') == 'rolling':
        return 'rolling'
    if not deadline and window.get('mode') == 'month' and item['registration_start'] and day.isoformat()[:7] < window['end_month']:
        return 'open_month'
    return 'open' if deadline and item['registration_start'] else 'unknown'


def save(data, body, known_ids, context, catalog):
    if not isinstance(body, dict) or set(body) != {'opportunity_id', 'name', 'reminder_date'} or any(not isinstance(v, str) for v in body.values()):
        raise ValueError('请提供活动、项目名称和可选提醒日期')
    item = next((x for x in catalog['opportunities'] if x['id'] == body['opportunity_id']), None)
    if item is None:
        raise KeyError('活动已不存在，请刷新核对')
    if not body['name'].strip():
        raise ValueError('请填写项目名称')
    if body['reminder_date']:
        core.iso_date(body['reminder_date'])
        if body['reminder_date'] < today().isoformat():
            raise ValueError('提醒日期不能早于今天')
        if state(item) == 'open' and body['reminder_date'] > item['deadline'][:10]:
            raise ValueError('报名准备提醒不能晚于已登记截止日期')
    existing = next((p for p in data['projects'].values() if p.get('opportunity', {}).get('id') == item['id']), None)
    if existing:
        return data, {'project_id': existing['id'], 'duplicate': True}
    if content_scope(item) != 'institutional_activity':
        raise ValueError('此记录已归入导师招募、招生通知或待核验线索，请先查看新去向；已有申请记录保持不变')
    school = item['school_id'] if item['school_id'] in context['units'] else ''
    dept = item['dept_id'] if school and item['dept_id'] in context['units'][school] else ''
    # A camp is an activity, not proof of formal degree/route eligibility.
    context = dict(context, opportunities=catalog['opportunities'])
    data, project = projects.update(data, dict(name=body['name'].strip(), school=item['school_name'], college=item['unit'],
        application_type=KINDS[item['kind']], school_id=school, dept_id=dept, year=item['admission_year'],
        opportunity=copy.deepcopy(item)), known_ids, context)
    if body['reminder_date']:
        notes = '\n'.join(['个人安排的报名准备提醒，不代表报名成功。', item['title'],
                           '官方登记截止：' + item['deadline'], item['deadline_note'],
                           '核对日期：' + item['verified_at'], '官方来源：' + item['source_url']])
        base, _ = core.update_entry(contact.core_view(data), 'reminders', dict(project_id=project['id'],
            title=('准备报名' if state(item) == 'open' else '核对活动信息') + ' · ' + item['title'], due_date=body['reminder_date'], notes=notes), known_ids)
        data = contact.merge_core(data, base, known_ids)
    return data, {'project_id': project['id'], 'duplicate': False}
