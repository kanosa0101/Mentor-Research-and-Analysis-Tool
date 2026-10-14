"""私人筛选目标与人工核验；不将未知招生信息推断为事实。"""
import copy
import json
from datetime import date
from urllib.parse import urlsplit
from uuid import uuid5, NAMESPACE_URL

MODES = ('research', 'qualification', 'email', 'opportunity', 'eligibility')


def empty():
    return {'version': 1, 'preferences': {'year': None, 'degree': 'any', 'route': 'unknown',
            'topics': [], 'schools': [], 'keep_unknown': True,
            'modes': {'research': 'hard', 'qualification': 'soft', 'email': 'soft', 'opportunity': 'soft', 'eligibility': 'soft'}}, 'reviews': {}}


def validate_preferences(prefs, known_ids):
    if not isinstance(prefs, dict) or set(prefs) != set(empty()['preferences']):
        raise ValueError('筛选条件结构错误')
    if prefs['year'] is not None and (type(prefs['year']) is not int or not 2000 <= prefs['year'] <= 2100):
        raise ValueError('年度须为 2000–2100 或未知')
    if prefs['degree'] not in ('any', 'master', 'phd') or prefs['route'] not in ('unknown', 'recommend', 'exam', 'assessment'):
        raise ValueError('无效学位或申请渠道')
    if type(prefs['keep_unknown']) is not bool:
        raise ValueError('keep_unknown 须为布尔值')
    for key in ('topics', 'schools'):
        values = prefs[key]
        if not isinstance(values, list) or len(values) > 50 or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in values):
            raise ValueError('关键词/学校须为非空字符串列表')
        if len(set(values)) != len(values):
            raise ValueError('条件不可重复')
    if any(s not in {pid.split('-')[0] for pid in known_ids} for s in prefs['schools']):
        raise ValueError('未知学校')
    if not isinstance(prefs['modes'], dict) or set(prefs['modes']) != set(MODES) or any(v not in ('hard', 'soft', 'off') for v in prefs['modes'].values()):
        raise ValueError('条件须为必须/偏好/不限制')


def validate_review(entry, known_ids, stored=False):
    fields = {'mentor_id', 'year', 'degree', 'route', 'opportunity', 'eligibility', 'source_url', 'quote', 'confirmed'}
    if not isinstance(entry, dict) or set(entry) != fields | ({'id', 'checked_at'} if stored else set()):
        raise ValueError('核验记录结构错误')
    if not isinstance(entry['mentor_id'], str) or entry['mentor_id'] not in known_ids:
        raise ValueError('未知导师')
    if type(entry['year']) is not int or not 2000 <= entry['year'] <= 2100 or entry['degree'] not in ('master', 'phd') or entry['route'] not in ('recommend', 'exam', 'assessment'):
        raise ValueError('核验须明确年度、学位和渠道')
    if entry['opportunity'] not in ('pass', 'fail', 'unknown') or entry['eligibility'] not in ('pass', 'fail', 'unknown') or entry['confirmed'] is not True:
        raise ValueError('须明确人工确认与核验状态')
    if not isinstance(entry['source_url'], str) or not isinstance(entry['quote'], str):
        raise ValueError('出处和原文须为字符串')
    if entry['opportunity'] != 'unknown' or entry['eligibility'] != 'unknown':
        link = urlsplit(entry['source_url'])
        if link.scheme not in ('http', 'https') or not link.hostname or not entry['quote'].strip():
            raise ValueError('确认结论须附 HTTP(S) 来源和原文片段')
    if stored:
        if entry['id'] != review_id(entry) or not isinstance(entry['checked_at'], str) or date.fromisoformat(entry['checked_at']).isoformat() != entry['checked_at'] or entry['checked_at'] > date.today().isoformat():
            raise ValueError('核验 ID 或日期错误')


def review_id(entry):
    return uuid5(NAMESPACE_URL, 'admission-review:' + '|'.join(str(entry[k]) for k in ('mentor_id', 'year', 'degree', 'route'))).hex


def validate(data, known_ids):
    if not isinstance(data, dict) or set(data) != {'version', 'preferences', 'reviews'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['reviews'], dict):
        raise ValueError('筛选备份结构错误')
    validate_preferences(data['preferences'], known_ids)
    for key, entry in data['reviews'].items():
        validate_review(entry, known_ids, stored=True)
        if key != entry['id']:
            raise ValueError('核验键不匹配')
    if len(json.dumps(data, ensure_ascii=False).encode()) > 1_000_000:
        raise ValueError('筛选与核验记录最多 1 MB')


def save_review(data, body, known_ids):
    validate_review(body, known_ids)
    data = copy.deepcopy(data)
    entry = {**body, 'id': review_id(body), 'checked_at': date.today().isoformat()}
    data['reviews'][entry['id']] = entry
    validate(data, known_ids)
    return data, entry
