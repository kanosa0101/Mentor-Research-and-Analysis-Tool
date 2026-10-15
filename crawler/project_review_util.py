"""用户项目核验：目标及两项证据独立适用；不作资格认证。"""
import copy
import hashlib
import json
import re
from datetime import date
from urllib.parse import urlsplit
from uuid import uuid5, NAMESPACE_URL

GOAL_KEYS = ('school_id', 'dept_id', 'year', 'degree', 'route', 'track', 'program_code', 'program_name')
BODY_KEYS = {'project_id', 'mentor_id', 'expected_goal', 'opportunity', 'eligibility',
             'opportunity_evidence', 'eligibility_evidence', 'confirmed'}


class GoalChanged(ValueError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def goal_snapshot(project):
    return {key: (project.get(key) if key == 'year' else project.get(key, '').strip()) for key in GOAL_KEYS}


def validate_goal(goal):
    if not isinstance(goal, dict) or set(goal) != set(GOAL_KEYS):
        raise ValueError('目标快照须包含完整八项字段')
    if any(not isinstance(goal[k], str) or goal[k] != goal[k].strip() for k in GOAL_KEYS if k != 'year'):
        raise ValueError('目标文本须为规范字符串')
    if goal['year'] is not None and (type(goal['year']) is not int or not 2000 <= goal['year'] <= 2100):
        raise ValueError('目标年度错误')
    for key, allowed in [('degree', ('', 'master', 'phd')), ('route', ('', 'recommend', 'exam', 'assessment')), ('track', ('', 'ordinary', 'special'))]:
        if goal[key] not in allowed:
            raise ValueError('目标学位、渠道或范围错误')


def complete(goal):
    return bool(all(goal[k] for k in GOAL_KEYS[:6]) and
                (goal['program_name'] or not goal['program_code'] and goal['track'] == 'ordinary'))


def review_id(entry):
    return uuid5(NAMESPACE_URL, 'project-review:' + json.dumps(
        [entry['project_id'], entry['mentor_id'], entry['goal_snapshot']], sort_keys=True, ensure_ascii=False, separators=(',', ':'))).hex


def valid_date(value):
    return isinstance(value, str) and date.fromisoformat(value).isoformat() == value and value <= date.today().isoformat()


def fresh(value, days=30):
    try:
        return valid_date(value) and (date.today() - date.fromisoformat(value)).days <= days
    except (ValueError, TypeError):
        return False


def validate_evidence(evidence, stored=False):
    if evidence is None:
        return
    if not isinstance(evidence, dict) or evidence.get('kind') not in ('official', 'reply'):
        raise ValueError('证据须为官方来源或已收到回复')
    keys = {'kind', 'quote', 'scope'}
    if evidence['kind'] == 'official':
        keys.add('source_url')
        if 'source_id' in evidence:
            keys.add('source_id')
            if stored:
                keys.add('source_hash')
    else:
        keys.add('communication_id')
        if stored:
            keys.add('communication_hash')
    if set(evidence) != keys or any(not isinstance(evidence[k], str) or not evidence[k].strip() for k in keys):
        raise ValueError('证据字段、原文或适用范围不完整')
    if evidence['kind'] == 'official':
        link = urlsplit(evidence['source_url'])
        if link.scheme not in ('http', 'https') or not link.hostname or link.username or link.password:
            raise ValueError('官方原文须为无凭据 HTTP(S) URL')
        if link.port is not None and link.port == 0:
            raise ValueError('官方原文端口错误')
    for key in ('source_hash', 'communication_hash'):
        if key in evidence and not re.fullmatch('[0-9a-f]{64}', evidence[key]):
            raise ValueError('证据指纹错误')


def validate_stored(entry):
    keys = BODY_KEYS - {'expected_goal'} | {'id', 'goal_snapshot', 'checked_at'}
    if not isinstance(entry, dict) or set(entry) != keys:
        raise ValueError('项目核验记录结构错误')
    if any(not isinstance(entry[k], str) or not entry[k] for k in ('id', 'project_id', 'mentor_id')):
        raise ValueError('项目或导师 ID 错误')
    validate_goal(entry['goal_snapshot'])
    if not complete(entry['goal_snapshot']) or entry['id'] != review_id(entry) or not valid_date(entry['checked_at']):
        raise ValueError('项目核验目标、ID或日期错误')
    if entry['confirmed'] is not True:
        raise ValueError('须明确人工确认')
    for dimension in ('opportunity', 'eligibility'):
        if entry[dimension] not in ('pass', 'fail', 'unknown'):
            raise ValueError('核验状态错误')
        evidence = entry[dimension + '_evidence']
        validate_evidence(evidence, stored=True)
        if entry[dimension] != 'unknown' and evidence is None:
            raise ValueError('已判断结论须有独立证据')


def same_source_url(url, source):
    # JSON 人类阅读页可能用 fragment 标识文章；普通 HTML/PDF 的锚点只定位段落。
    def identity(value):
        link = urlsplit(value)
        return (link.scheme.lower(), link.hostname, link.port or (443 if link.scheme.lower() == 'https' else 80),
                link.path or '/', link.query, link.fragment if source.get('format') == 'json' else '')
    return identity(url) == identity(source['url'])


def matching_sources(url, context):
    return sorted(sid for sid, source in context['sources'].items() if same_source_url(url, source))


def source_state(evidence, context):
    sid = evidence.get('source_id')
    if not sid:
        matches = matching_sources(evidence['source_url'], context)
        if not matches:
            return ['source_unmonitored']
        # 旧未登记证据没有基线指纹：只读时不能自动升级为已监测核验。
        available = any(not source_state(dict(evidence, source_id=match), context) for match in matches)
        return ['source_registered'] + ([] if available else ['source_unavailable'])
    source = context['sources'].get(sid)
    check = context.get('checks', {}).get(sid, {})
    if not isinstance(source, dict) or not same_source_url(evidence['source_url'], source):
        return ['source_missing']
    if not isinstance(check, dict) or check.get('status') != 'ok' or not fresh(check.get('last_success'), days=7) or not re.fullmatch('[0-9a-f]{64}', str(check.get('hash', ''))):
        return ['source_unavailable']
    if 'source_hash' in evidence and evidence['source_hash'] != check['hash']:
        return ['source_changed']
    return []


def reply_for(evidence, entry, workflow):
    event = workflow['communications'].get(evidence['communication_id'])
    if event is None or event.get('kind') != 'replied' or any(event.get(k) != entry[k] for k in ('project_id', 'mentor_id')):
        return None
    return event if evidence['quote'] in event.get('content', '') else None


def save(data, body, workflow, mentors, context):
    from crawler import discovery_util as discovery
    if not isinstance(body, dict) or set(body) != BODY_KEYS:
        raise ValueError('项目核验请求结构错误')
    validate_goal(body['expected_goal'])
    if not isinstance(body['project_id'], str) or body['project_id'] not in workflow['projects']:
        raise GoalChanged('申请项目不存在，请重新载入目标')
    goal = goal_snapshot(workflow['projects'][body['project_id']])
    if body['expected_goal'] != goal:
        raise GoalChanged('申请目标已改变，请重新载入后核对')
    if goal['dept_id'] not in context.get('units', {}).get(goal['school_id'], set()):
        raise ValueError('项目学校院系未登记')
    mentor = mentors.get(body['mentor_id']) if isinstance(body['mentor_id'], str) else None
    if mentor is None or (mentor.get('school'), mentor.get('dept')) != (goal['school_id'], goal['dept_id']):
        raise ValueError('导师登记学校院系与项目不一致')
    entry = {k: copy.deepcopy(v) for k, v in body.items() if k != 'expected_goal'}
    entry.update(goal_snapshot=goal, checked_at=date.today().isoformat())
    entry['id'] = review_id(entry)
    for dimension in ('opportunity', 'eligibility'):
        evidence = entry[dimension + '_evidence']
        validate_evidence(evidence)
        if evidence is None:
            continue
        if evidence['kind'] == 'official':
            if not evidence.get('source_id'):
                matches = matching_sources(evidence['source_url'], context)
                if matches:
                    evidence['source_id'] = next((sid for sid in matches if not source_state(dict(evidence, source_id=sid), context)), matches[0])
            reasons = source_state(evidence, context)
            if any(r != 'source_unmonitored' for r in reasons):
                raise ValueError('登记来源不可用、过时或与URL不符')
            if evidence.get('source_id'):
                evidence['source_hash'] = context['checks'][evidence['source_id']]['hash']
        else:
            event = reply_for(evidence, entry, workflow)
            if event is None:
                raise ValueError('须引用同项目同导师已收到回复的实际原文')
            evidence['communication_hash'] = fingerprint(event)
    validate_stored(entry)
    result = copy.deepcopy(data)
    result.update(version=2)
    result.setdefault('project_reviews', {})[entry['id']] = entry
    discovery.validate(result, mentors)
    return result, entry


def view(data, workflow, mentors, context):
    projects = {}
    for key, project in workflow['projects'].items():
        goal = goal_snapshot(project)
        valid_unit = goal['dept_id'] in context.get('units', {}).get(goal['school_id'], set())
        projects[key] = dict(id=key, name=project['name'], goal_snapshot=goal, complete=complete(goal) and valid_unit)
    replies = {key: {k: e[k] for k in ('id', 'project_id', 'mentor_id', 'subject', 'date', 'content')}
               for key, e in workflow['communications'].items() if e.get('kind') == 'replied'}
    reviews = {}
    for key, entry in data.get('project_reviews', {}).items():
        reasons = []
        project = projects.get(entry['project_id'])
        if project is None:
            reasons.append('project_missing')
        elif project['goal_snapshot'] != entry['goal_snapshot']:
            reasons.append('goal_changed')
        if project is not None and not project['complete']:
            reasons.append('goal_incomplete')
        mentor = mentors.get(entry['mentor_id'], {})
        if (mentor.get('school'), mentor.get('dept')) != (entry['goal_snapshot']['school_id'], entry['goal_snapshot']['dept_id']):
            reasons.append('mentor_mismatch')
        if not fresh(entry['checked_at']):
            reasons.append('expired')
        state = dict(copy.deepcopy(entry), applicable=not reasons, reasons=reasons)
        for dimension in ('opportunity', 'eligibility'):
            evidence = entry[dimension + '_evidence']
            issues = []
            if evidence is None:
                issues.append('evidence_missing')
            elif evidence['kind'] == 'official':
                issues = source_state(evidence, context)
            else:
                event = reply_for(evidence, entry, workflow)
                if event is None:
                    issues.append('evidence_missing')
                elif fingerprint(event) != evidence['communication_hash']:
                    issues.append('evidence_changed')
            state[dimension + '_reasons'] = issues
            state[dimension + '_status'] = entry[dimension] if not reasons and all(i == 'source_unmonitored' for i in issues) else 'unknown'
        reviews[key] = state
    return dict(projects=projects, replies=replies, project_reviews=reviews)
