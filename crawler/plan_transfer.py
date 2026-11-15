"""Explicit, atomic browser plan to local project conversion; no private schema change."""
import copy
import re
from urllib.parse import urlsplit, parse_qs, unquote
from uuid import uuid5, NAMESPACE_URL

from crawler import project_util as projects, opportunity_util as opportunities
from crawler import workflow_util as core, contact_util as contact


def text(value, limit, label, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(label + '无效')
    return value.strip()


def target(value, context):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'id', 'path', 'year', 'schools', 'interest', 'created_at'}:
        raise ValueError('关注目标结构错误')
    text(value['id'], 96, '目标标识')
    if value['path'] not in ('exam', 'recommend') or type(value['year']) is not int or not 2000 <= value['year'] <= 2100:
        raise ValueError('目标路径或年份无效')
    text(value['interest'], 200, '研究兴趣', True); core.iso_date(value['created_at'])
    if not isinstance(value['schools'], list) or len(value['schools']) > 20:
        raise ValueError('目标学校列表无效')
    seen = set()
    for school in value['schools']:
        if not isinstance(school, dict) or set(school) != {'id', 'name'} or not isinstance(school['id'], str) or school['id'] not in context['units'] or school['id'] in seen:
            raise ValueError('目标学校未知或重复')
        text(school['name'], 100, '学校名称'); seen.add(school['id'])
    return value


def bookmark(value):
    if not isinstance(value, dict) or set(value) != {'id', 'kind', 'title', 'url', 'created_at'} or value['kind'] not in ('mentor', 'notice', 'opportunity'):
        raise ValueError('收藏结构错误')
    text(value['id'], 96, '收藏标识'); text(value['title'], 300, '收藏标题'); core.iso_date(value['created_at'])
    raw = text(value['url'], 3000, '收藏链接')
    if re.search(r'^[a-z][a-z\d+.-]*:|^//|[\\\x00-\x20]', raw, re.I):
        raise ValueError('收藏须为本站页面')
    parsed = urlsplit(raw)
    path = unquote(parsed.path)
    if '\\' in path or '..' in path.split('/') or any(ord(c) < 32 for c in path):
        raise ValueError('收藏路径无效')
    permitted = {'notice': r'notices\.html', 'opportunity': r'opportunities\.html', 'mentor': r'p/[^/\\:.%]+\.html'}
    if not re.fullmatch(permitted[value['kind']], path):
        raise ValueError('收藏页面与类型不符')
    return path, parse_qs(parsed.query)


def save(data, body, known_ids, context, catalog):
    if not isinstance(body, dict) or set(body) != {'kind', 'item', 'target', 'school_id', 'name', 'notes', 'todos'}:
        raise ValueError('转换参数错误')
    if body['kind'] not in ('target', 'bookmark'):
        raise ValueError('转换类型错误')
    name = text(body['name'], 300, '项目名称')
    notes = text(body['notes'], 3000, '备注', True)
    goal = target(body['item'] if body['kind'] == 'target' else body['target'], context)
    if body['kind'] == 'target' and body['target'] is not None:
        raise ValueError('目标转换不能重复指定目标')
    school = body['school_id']
    if not isinstance(school, str) or (school and school not in context['units']):
        raise ValueError('学校无效')
    if goal and goal['schools'] and school not in {s['id'] for s in goal['schools']}:
        raise ValueError('请明确选择关注目标中的一所学校')
    todos = body['todos']
    if not isinstance(todos, list) or len(todos) > 1000:
        raise ValueError('待办列表无效')
    seen = set()
    for todo in todos:
        if not isinstance(todo, dict) or set(todo) != {'id', 'title', 'done', 'due_date', 'target_id', 'created_at'}:
            raise ValueError('待办结构错误')
        text(todo['id'], 96, '待办标识'); text(todo['title'], 300, '待办标题')
        core.iso_date(todo['created_at'])
        if not isinstance(todo['due_date'], str):raise ValueError('个人计划日期须为字符串')
        if todo['due_date']:core.iso_date(todo['due_date'])
        if type(todo['done']) is not bool or todo['id'] in seen or not goal or todo['target_id'] != goal['id']:
            raise ValueError('待办不属于所选关注目标或存在重复')
        seen.add(todo['id'])
    source = body['item']; mentor = ''; activity = None; dept = ''
    if body['kind'] == 'bookmark':
        path, query = bookmark(source)
        if source['kind'] == 'mentor':
            mentor = path[2:-5]
            if mentor not in known_ids:raise ValueError('该导师已不在当前目录，请重新查找')
            mentor_school, mentor_dept, _ = mentor.split('-', 2)
            if school and school != mentor_school:raise ValueError('导师与选择学校不一致，请调整关注目标')
            school, dept = mentor_school, mentor_dept
        elif source['kind'] == 'opportunity':
            activity = next((x for x in catalog['opportunities'] if [x['id']] == query.get('id')), None)
            if activity is None:raise ValueError('该机会已不在当前目录，请重新核对')
            if school and activity['school_id'] != school:raise ValueError('机会与选择学校不一致')
            existing = next((p for p in data['projects'].values() if p.get('opportunity', {}).get('id') == activity['id']), None)
            if existing:return data, {'project_id': existing['id'], 'duplicate': True, 'reminder_count': 0}
        elif source['kind'] == 'notice':
            source_school = query.get('school', [''])[0]
            source_dept = query.get('dept', [''])[0]
            if source_school:
                if source_school not in context['units'] or (source_dept and source_dept not in context['units'][source_school]):
                    raise ValueError('收藏通知的学校院系已不在目录，请重新核对')
                if school and school != source_school:raise ValueError('通知与选择学校不一致')
                school, dept = source_school, source_dept
    identity = source['id'] if body['kind'] == 'target' else source['kind'] + ':' + source['url']
    stable = uuid5(NAMESPACE_URL, 'mentor-browser-plan:' + body['kind'] + ':' + identity + ':' + school + ':' + (goal['id'] if goal else '')).hex
    if stable in data['projects']:
        return data, {'project_id': stable, 'duplicate': True, 'reminder_count': 0}
    result = copy.deepcopy(data)
    lines = ['从浏览器' + ('关注目标' if body['kind'] == 'target' else '收藏') + '建立；未代报名或确认申请资格。']
    if goal:
        lines += [('计划入学年度：' if goal['path'] == 'exam' else '本科毕业届别：') + str(goal['year']), '研究兴趣：' + (goal['interest'] or '未填写')]
    if body['kind'] == 'bookmark':lines += ['收藏标题：' + source['title'], '收藏页面：' + source['url']]
    if notes:lines += ['个人备注：' + notes]
    for todo in todos:lines += [('已完成' if todo['done'] else '待办') + '：' + todo['title'] + ('；个人计划 ' + todo['due_date'] if todo['due_date'] else '；未设日期')]
    if activity:
        result, saved = opportunities.save(result, {'opportunity_id': activity['id'], 'name': name, 'reminder_date': ''}, known_ids, context, catalog)
        project = result['projects'][saved['project_id']]
        project['notes'] = '\n'.join(lines)
    else:
        school_name = next((s['name'] for s in (goal or {}).get('schools', []) if s['id'] == school), school)
        payload = dict(name=name, school=school_name, school_id=school, dept_id=dept, mentor_ids=[mentor] if mentor else [],
            degree='master' if goal else '', route=goal['path'] if goal else '', year=goal['year'] if goal and goal['path']=='exam' else None,
            notes='\n'.join(lines), application_type='统考准备' if goal and goal['path']=='exam' else '保研准备' if goal else '收藏待核对')
        result, project = projects.update(result, payload, known_ids, context)
    old = project['id']; project['id'] = stable
    result['projects'][stable] = result['projects'].pop(old)
    for t in result['targets'].values():
        if t['project_id'] == old:t['project_id'] = stable
    count = 0
    for todo in todos:
        if not todo['due_date']:continue
        base, _ = core.update_entry(contact.core_view(result), 'reminders', dict(project_id=stable, title=todo['title'], due_date=todo['due_date'],
            completed=todo['done'], notes='来自浏览器个人待办；不是官方截止。'), known_ids)
        result = contact.merge_core(result, base, known_ids); count += 1
    contact.validate(result, known_ids); projects.validate(result, context)
    return result, {'project_id': stable, 'duplicate': False, 'reminder_count': count}
