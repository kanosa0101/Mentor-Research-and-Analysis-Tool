from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import pytest
import yaml

from crawler import mentor_fields, store
from crawler.mentor_recovery import identity
from scripts import crawl
from sites.ruc import ruc_ai


ROSTER = 'https://ai.ruc.edu.cn/szdw/zrjs/index.htm'
CURRENT = 'https://ai.ruc.edu.cn/szdw/zrjs/jia/index.htm'
OLD = 'http://ai.ruc.edu.cn/academicfaculty/szdwn/jia/index.htm'
OTHER = 'https://ai.ruc.edu.cn/szdw/zrjs/second/index.htm'


def profile(*, name='张甲', mailbox='本人(@)ruc.edu.cn', intro='', direction='<p>机器学习</p>'):
    return f'''<title>{name}_中国人民大学高瓴人工智能学院</title>
      <nav>讲师 博士生导师 <a href="mailto:ai@ruc.edu.cn">ai@ruc.edu.cn</a></nav>
      <div class="teaDetailBox"><div class="teaBaseCon">
        <div class="name"><h2>{name} <span>长聘副教授</span></h2></div>
        <div class="lxfs"><p>邮箱：{mailbox}</p><p>个人网页：--</p></div>
        <div class="summary"><p>{intro}</p></div></div>
        <div class="teaContent"><h2>研究方向</h2>{direction}<h2>工作经历</h2>
          <p>清华大学研究员。导师：刘乙教授，博士生导师。</p>
        </div></div><footer>gsai@ruc.edu.cn</footer>'''


def roster(*people):
    cards = ''.join(f'<div class="teaItem"><div class="name"><a href="{url}">{name}</a></div>'
                    f'<div class="detailA"><a href="{url}">中文</a></div></div>' for name, url in people)
    return '<title>专任教师_中国人民大学高瓴人工智能学院</title><div class="teacherBox">'+cards+'</div>'


def original(**values):
    return dict({'name': '张甲', 'detail_url': CURRENT, 'email': 'teacher@ruc.edu.cn', 'title': '副教授'}, **values)


def test_scope_reads_named_direction_and_email_without_footer_or_job_history():
    html = profile(mailbox='teacher (@)ruc.edu.cn', intro='张甲，现任长聘副教授，博士生导师。',
                   direction='<p>机器学习</p><p>强化学习。详见个人主页：https://example.edu.cn/</p><p>更多详细介绍请参考：</p>')
    parsed = ruc_ai.parse_detail({'_expected_name': '张甲', '_original_profile': original()}, html, CURRENT)
    assert parsed['name'] == '张甲' and parsed['title'] == '副教授'
    assert parsed['email'] == 'teacher@ruc.edu.cn' and parsed['supervisor'] == '博导'
    assert parsed['research_direction_raw'] == '机器学习；强化学习'


@pytest.mark.parametrize('intro', ['张甲，曾任博士生导师。', '张甲，导师为刘乙教授，博士生导师。',
                                   '张甲，和刘乙教授（博导）合作。', '张甲，现招收博士研究生。',
                                   '张甲的同事刘乙，博士生导师。'])
def test_supervision_requires_explicit_current_personal_qualification(intro):
    assert 'supervisor' not in ruc_ai.parse_detail({}, profile(intro=intro), CURRENT)


@pytest.mark.parametrize(('shown', 'expected'), [('teacher[@]ruc.edu.cn', 'teacher@ruc.edu.cn'),
                                                ('teacher@ruc.edu.cn other@ruc.edu.cn', 'teacher@ruc.edu.cn'),
                                                ('teacher AT {ruc.edu.cn, gmail.com}', 'teacher@ruc.edu.cn'),
                                                ('teacher at ruc', None), ('ai@ruc.edu.cn', None),
                                                ('other@ruc.edu.cn', None)])
def test_only_current_labelled_email_supports_an_existing_value(shown, expected):
    assert ruc_ai.parse_detail({'_original_profile': original()}, profile(mailbox=shown), CURRENT).get('email') == expected


@pytest.mark.parametrize(('records', 'accepted'), [((('张甲', CURRENT),), True),
                                                   ((('张甲', CURRENT), ('张甲', OTHER)), False),
                                                   ((('张乙', CURRENT),), False)])
def test_recovery_requires_unique_current_roster_name_and_existing_contact(records, accepted):
    person = original(detail_url=OLD)
    official = roster(*records)
    cfg = {'_expected_name': '张甲', '_original_profile': person,
           '_read_source': lambda url: (official.encode(), official), 'list': {'urls': [ROSTER]}}
    if not accepted:
        with pytest.raises(ValueError, match='名册'):
            ruc_ai.parse_detail(cfg, profile(mailbox='teacher@ruc.edu.cn'), CURRENT)
        return
    assert identity(person, ruc_ai.parse_detail(cfg, profile(mailbox='teacher@ruc.edu.cn'), CURRENT), CURRENT) == 'name_and_email'
    assert identity(person, ruc_ai.parse_detail(cfg, profile(mailbox='other@ruc.edu.cn'), CURRENT), CURRENT) is None


def test_protect_registered_and_manual_fields():
    current = original(research_direction_raw='已登记的其它来源方向', supervisor='硕导',
                       provenance={'research_direction_raw': {'origin': 'crawled'}, 'supervisor': {'origin': 'manual'}})
    parsed = ruc_ai.parse_detail({'_original_profile': current}, profile(intro='张甲、副教授、博士生导师。'), CURRENT)
    assert not ({'research_direction_raw', 'supervisor'} & parsed.keys())
    manual_blank = original(provenance={'research_direction_raw': {'origin': 'manual'}})
    assert 'research_direction_raw' not in ruc_ai.parse_detail({'_original_profile': manual_blank}, profile(), CURRENT)


def test_wrong_registered_name_aborts_even_if_title_and_contact_look_valid():
    with pytest.raises(ValueError, match='姓名'):
        ruc_ai.parse_detail({'_expected_name': '张乙'}, profile(), CURRENT)


def test_normal_roster_preserves_manual_profile_and_does_not_duplicate_stale_detail(tmp_path, monkeypatch):
    cfg = yaml.safe_load(Path(ruc_ai.__file__).with_name('ai.yaml').read_bytes())
    folder = tmp_path / 'data/professors/ruc/ai'
    folder.mkdir(parents=True)
    first = dict(name='张甲', slug='zhangjia', school='ruc', dept='ai', detail_url=CURRENT,
                 profile_url='https://author.edu.cn/home', provenance={'profile_url': {
                     'origin': 'manual', 'source': 'https://author.edu.cn/home',
                     'fetched_at': '2026-11-22', 'confidence': 'auto'}})
    second = dict(first, name='张乙', slug='zhangyi', detail_url=OLD)
    for row in (first, second):
        (folder / (row['slug'] + '.yaml')).write_text(yaml.safe_dump(row, allow_unicode=True), encoding='utf8')
    page = roster(('张甲', CURRENT), ('张乙', OTHER))
    monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
    monkeypatch.setattr(ruc_ai.fetch, 'fetch_text', lambda *args, **kw: (page, {'fetched_at': '2026-11-23'}, True))

    assert crawl.phase_roster(cfg, ruc_ai, False)['roster_total'] == 2
    assert len(list(folder.glob('*.yaml'))) == 2
    for row in (first, second):
        after = yaml.safe_load((folder / (row['slug'] + '.yaml')).read_bytes())
        for field in ('profile_url', 'detail_url', 'provenance'):
            assert after[field] == row[field]


@pytest.mark.parametrize(('case', 'printed'), [
    ('fill', 'teacher(@)ruc.edu.cn'),
    ('conflict', 'teacher(@)ruc.edu.cn'),
    ('manual', 'teacher(@)ruc.edu.cn'),
    ('manual_blank', 'teacher(@)ruc.edu.cn'),
    ('owner', 'teacher(@)ruc.edu.cn'),
    ('multiple', 'teacher(@)ruc.edu.cn other(@)ruc.edu.cn'),
    ('recheck', 'teacher(@)ruc.edu.cn other(@)ruc.edu.cn'),
])
def test_normal_field_queue_binds_current_person_and_preserves_ownership(tmp_path, case, printed):
    site = tmp_path / 'sites/ruc'
    site.mkdir(parents=True)
    copyfile(Path(ruc_ai.__file__).with_name('ai.yaml'), site / 'ai.yaml')
    copyfile(ruc_ai.__file__, site / 'ruc_ai.py')
    path = tmp_path / 'data/professors/ruc/ai/primary.yaml'
    path.parent.mkdir(parents=True)
    row = dict(name='张甲', slug='primary', school='ruc', dept='ai', detail_url=CURRENT, title='副教授')
    verified = 'teacher@ruc.edu.cn'
    if case in ('conflict', 'manual', 'manual_blank', 'recheck'):
        proof = dict(origin='manual' if case.startswith('manual') else 'crawled',
                     source=CURRENT, fetched_at='2026-10-01', confidence='auto')
        row['provenance'] = {'email': proof}
        if case != 'manual_blank':
            row['email'] = verified if case == 'recheck' else 'prior@ruc.edu.cn'
    if case == 'owner':
        owner = tmp_path / 'data/professors/other/cs/second.yaml'
        owner.parent.mkdir(parents=True)
        owner.write_text(yaml.safe_dump(dict(row, slug='second', school='other', dept='cs',
                                            detail_url='https://other.edu.cn/person', email=verified),
                                       allow_unicode=True), encoding='utf-8')
    path.write_text(yaml.safe_dump(row, allow_unicode=True), encoding='utf-8')
    body = profile(mailbox=printed).encode()

    def fetcher(source):
        assert source['url'] == CURRENT
        return body

    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    result = mentor_fields.run(tmp_path, units=('ruc/ai',), limit=2, fetcher=fetcher, now=now)
    after = yaml.safe_load(path.read_bytes())
    assert result['attempted'] == 1
    if case == 'fill':
        status = mentor_fields.read(tmp_path)['records']['ruc/ai/primary']['fields']['email']
        assert after['email'] == verified and after['provenance']['email']['source'] == CURRENT
        assert status['source_sha256'] == sha256(body).hexdigest()
    elif case == 'recheck':
        assert after['email'] == verified
        assert after['provenance']['email']['source'] == CURRENT
    else:
        assert after.get('email') == row.get('email')
        assert after.get('provenance', {}).get('email') == row.get('provenance', {}).get('email')
        if case == 'owner':
            assert yaml.safe_load(owner.read_bytes())['email'] == verified
