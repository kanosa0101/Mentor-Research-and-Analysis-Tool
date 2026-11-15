"""Conservative notice cohorts: explicit wording is separate from publication dates."""
import copy
import re
from datetime import date, datetime, timedelta, timezone


ROUTES = {
    'recommend': '推免', 'exam': '全国统考', 'assessment': '申请考核',
    'winter_camp': '冬令营', 'summer_camp': '夏令营', 'research': '科研实践', 'unknown': '通用政策 / 渠道未拆分',
}
STAGES = {'results': '结果 / 名单', 'assessment': '复试 / 考核', 'application': '申请 / 报名通知',
          'policy': '政策 / 招生计划', 'activity': '活动安排', 'confirmation': '网上确认',
          'exam_arrangement': '初试 / 考点安排', 'exam_registration': '网上报名',
          'qualification': '资格 / 材料审核与补正', 'unknown': '阶段待核验'}
CYCLES = {'current': '当前招生周期', 'preparation': '下一届准备',
          'historical': '往届 / 已结束阶段', 'unknown': '届别或周期待核验'}


def today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def year(value):
    return value if type(value) is int and 2000 <= value <= 2100 else None


def _explicit_year(title, pattern, label, basis):
    matches = list(re.finditer(pattern, title))
    values = {int(match.group(1)) for match in matches}
    if len(values) == 1:
        basis.append(label + '依据标题原文：“' + matches[0].group(0) + '”；尚未核验正文。')
        return values.pop()
    if len(values) > 1:
        basis.append(label + '存在多个明确年份，需核验原文。')
    return None


def _stage(title, route):
    # A notice can contain past recommendation results and a current exam quota.
    if route == 'exam':
        mixed = re.search(r'(?:推免|推荐免试).+?((?:统考|统招).+)', title)
        if mixed:
            title = mixed.group(1)
    if route == 'exam' and re.search(r'(?:统考|统招|全国统考).{0,12}(?:计划|名额|目录)', title):
        return 'policy'
    if re.search(r'资格审核|材料审核|不符合.{0,12}(?:名单|条件)|补正|补交材料|补充材料', title):
        return 'qualification'
    if re.search(r'拟录取|录取名单|通过名单|结果|成绩|公示|入营名单|营员名单', title):
        return 'results'
    if route == 'exam':
        if '网上确认' in title or '现场确认' in title:
            return 'confirmation'
        if re.search(r'初试|考点|准考证|考试安排', title):
            return 'exam_arrangement'
        if re.search(r'网报|网上报名', title):
            return 'exam_registration'
    if re.search(r'复试|考核|面试', title) and not re.search(r'申请.{0,3}考核.{0,5}(?:招生|简章|办法)', title):
        return 'assessment'
    if re.search(r'报名|申请|接收|招收|招募', title):
        return 'application'
    if re.search(r'简章|细则|章程|目录|计划|指南|招生|办法|问答|Q\s*&\s*A', title, re.I):
        return 'policy'
    if route in ('winter_camp', 'summer_camp', 'research'):
        return 'activity'
    return 'unknown'


def _cycle(route, stage, admission, graduation, activity, day):
    if route == 'recommend':
        target = admission or graduation
        next_cohort = day.year + (2 if day.month >= 11 else 1)
        if target is None:
            return 'unknown', '未明确推免入学年或毕业届别；不使用公告发布日期补齐。'
        if target < next_cohort:
            return 'historical', '按推免年度阶段归档；11月起，下一年入学的推免作为已结束周期参考。'
        return ('preparation' if day.month >= 11 or target > next_cohort else 'current'), '仅判断申请周期，不表示当前可以报名；具体窗口查官方通知。'
    if route in ('exam', 'assessment'):
        if admission is None:
            return 'unknown', '缺少明确入学年份，不能根据发布年判断招生周期。'
        target = day.year + (1 if day.month >= 9 else 0)
        if admission < target:
            return 'historical', '入学年份已早于当前招生周期。'
        if admission > target:
            return 'preparation', '面向后续入学年份，需另查具体申请窗口。'
        return 'current', ('当前统考周期 / 备考与后续安排；不表示报名中，具体考试与报名时间查官方通知。'
                           if route == 'exam' else '当前入学周期；各校及项目的申请考核窗口不同，需核验具体日期。')
    if route in ('winter_camp', 'summer_camp', 'research'):
        if activity is not None and activity < day.year:
            return 'historical', '活动年份已过去；不由活动年份推导毕业届别或入学年。'
        target = graduation or admission
        if target is None:
            return 'unknown', '活动年份不等于毕业届别或入学年；面向人群仍待核验。'
        next_cohort = day.year + (2 if day.month >= 11 else 1)
        if target < next_cohort:
            return 'historical', '对应毕业届别的推免准备阶段已过去；具体科研活动是否仍接受申请另查原文。'
        return 'preparation', '按明确的面向届别列为准备资料；参加活动不等于推免录取。'
    if route == 'unknown' and stage == 'policy' and admission is not None:
        target = day.year + (1 if day.month >= 9 else 0)
        cycle = 'historical' if admission < target else 'current' if admission == target else 'preparation'
        return cycle, '按明确入学年份整理的通用政策，可查资格、专业与材料；渠道尚未拆分，不表示报名开放。'
    return 'unknown', '可用于查资格、专业与材料要求；渠道尚未拆分，需到正文核对哪些条款适用于自己。'


def classify_notice(notice, day=None, opportunities=None):
    """Return display metadata only; never mark the original notice as reviewed."""
    day = date.fromisoformat(day) if isinstance(day, str) else day or today()
    title = notice.get('title', '')
    basis = []
    graduation = _explicit_year(title, r'(20\d{2})\s*届(?:优秀)?(?:应届)?本科(?:毕业生|生)', '本科毕业届别', basis)
    if graduation is None:
        graduation = _explicit_year(title, r'(20\d{2})\s*年(?:优秀)?应届本科毕业生', '本科毕业届别', basis)
    activity = _explicit_year(title, r'(20\d{2})\s*年(?:度)?[^，。；\d]{0,45}(?:冬令营|夏令营|科研实践|科研实习|创新实践|科创计划)', '活动年份', basis)
    admission = _explicit_year(title, r'(20\d{2})\s*年(?:度)?(?:入学|入校)', '入学年份', basis)
    if admission is None and activity is None:
        # A plain "2027招生" is insufficient; require a graduate admission context.
        admission = _explicit_year(title, r'(20\d{2})\s*(?:年(?:度)?|级)(?![^，。；]{0,8}应届本科毕业生)[^，。；\d]{0,60}(?:研究生招生|硕士招生|博士招生|招收推荐免试研究生|接收推荐免试研究生|招收推免|接收推免|接收推荐免试|硕士研究生|博士研究生|研究生预推免|研究生推免|推免|推荐免试|免试攻读研究生|统考)', '入学年份', basis)
    explicit = dict(admission_year=admission, graduation_year=graduation, activity_year=activity)
    for key, label in (('admission_year', '入学年份'), ('graduation_year', '本科毕业届别'), ('activity_year', '活动年份')):
        if notice.get('reviewed') is True and year(notice.get(key)):
            explicit[key] = notice[key]
            basis.append(label + '来自已核验通知记录。')
    rows = opportunities.get('opportunities', []) if isinstance(opportunities, dict) else opportunities or []
    linked = next((item for item in rows if item.get('source_url') == notice.get('url') and item.get('source_state') == 'verified'), None)
    if linked:
        labels = {'admission_year': '入学年份', 'graduation_year': '本科毕业届别', 'activity_year': '活动年份'}
        for key, source_key in (('admission_year', 'admission_year'), ('graduation_year', 'graduation_year'), ('activity_year', 'camp_year')):
            if year(linked.get(source_key)):
                if explicit[key] and explicit[key] != linked[source_key]:
                    basis.append(labels[key] + '的标题与已核验活动摘要冲突，暂不归入明确届别。')
                    explicit[key] = None
                else:
                    explicit[key] = linked[source_key]
                    basis.append(labels[key] + '来自同一官方网址的已核验活动摘要，核验日期 ' + str(linked.get('verified_at') or '未记录') + '；不代表整条通知已核验。')
    patterns = {'recommend': r'推免|推荐免试|免试攻读', 'exam': r'统考|统招|全国硕士研究生招生考试',
                'assessment': r'申请.?考核', 'winter_camp': r'冬令营', 'summer_camp': r'夏令营',
                'research': r'科研实践|科研实习|科创计划|创新实践|春闱计划|深瞳计划'}
    routes = [key for key, pattern in patterns.items() if re.search(pattern, title)]
    if 'exam' not in routes and re.search(r'硕士|考研', title) and '博士' not in title and re.search(r'初试|网报|网上报名|网上确认|现场确认|考点|准考证', title):
        routes.append('exam')
        basis.append('全国统考渠道依据明确的硕士 / 考研语境及初试、网报、确认或考点安排，仍需核验正文。')
    routes = routes or ['unknown']
    if routes == ['unknown']:
        basis.append('标题未明确拆分申请渠道；通用招生章程可能涉及多渠道，保留供查资格、专业与材料要求。')
    tracks = []
    for route in routes:
        stage = _stage(title, route)
        cycle, note = _cycle(route, stage, explicit['admission_year'], explicit['graduation_year'], explicit['activity_year'], day)
        if stage == 'results':
            note += ' 此条为结果或名单，可跟进已有申请，不能作为仍接受新申请的依据。'
        tracks.append(dict(route=route, route_label=ROUTES[route], stage=stage, stage_label=STAGES[stage], cycle=cycle, cycle_label=CYCLES[cycle], note=note))
    cycles = {track['cycle'] for track in tracks}
    cycle = next(key for key in ('current', 'preparation', 'unknown', 'historical') if key in cycles)
    basis.append('发布日期、抓取日期和栏目仍可见均不作为届别或报名开放依据。')
    return dict(**explicit, routes=routes, tracks=tracks, cycle=cycle, cycle_label=CYCLES[cycle],
                stage='mixed' if len({track['stage'] for track in tracks}) > 1 else tracks[0]['stage'],
                basis=basis, as_of=day.isoformat(), linked_opportunity_id=linked.get('id') if linked else None)


def annotate_notices(rows, day=None, opportunities=None):
    result = []
    for item in rows:
        row = copy.deepcopy(item)
        row['classification'] = classify_notice(item, day=day, opportunities=opportunities)
        result.append(row)
    return result
