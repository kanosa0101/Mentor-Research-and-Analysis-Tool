from pathlib import Path
import importlib.util

import pytest

from crawler.model import Professor, Provenance
from sites import related_v7

FIXTURES = Path(__file__).parent / 'fixtures' / 'csu_v14'
PEOPLE = [('jiangxia', '姜霞', '副教授'), ('tanaina', '覃爱娜', '教授'),
          ('tangjiawei', '汤嘉伟', '讲师'), ('sudan', '苏丹', '讲师')]


@pytest.mark.parametrize('ref,name,title', PEOPLE)
def test_official_template_personal_fields(ref, name, title):
    url = f'https://faculty.csu.edu.cn/{ref}/zh_CN/index.htm'
    html = (FIXTURES / (ref + '.html')).read_text(encoding='utf-8')
    result = related_v7.parse_detail({'_roster_names': {url: name}}, html, url)
    assert result['title'] == title
    assert result['bio_raw'] and '暂无内容' not in result['bio_raw']
    assert not result.get('email')  # encrypted strings never become addresses
    if ref == 'tanaina':
        assert result['supervisor'] == '硕导'
        assert result['research_directions'] == ['数字信息技术、语音信号处理']
    elif ref == 'sudan':
        assert result['research_directions'] == ['基于神经动力学方法的优化算法与工业应用']
        assert '6afc55eaa59' not in result['bio_raw']
    else:
        assert not result.get('research_directions')


def test_bilingual_bio_requires_exact_opening_identity():
    url = 'https://faculty.csu.edu.cn/tanaina/zh_CN/index.htm'
    html = (FIXTURES / 'tanaina.html').read_text(encoding='utf-8')
    with pytest.raises(related_v7.IdentityMismatch):
        related_v7.parse_detail({'_roster_names': {url: '覃爱纳'}}, html, url)
    # Mentioning the expected person later in an unrelated person's bio is insufficient.
    html = html.replace('覃爱娜，博士', '李四，博士') + '<p>覃爱娜</p>'
    with pytest.raises(related_v7.IdentityMismatch):
        related_v7.parse_detail({'_roster_names': {url: '覃爱娜'}}, html, url)


def test_csu_sections_do_not_promote_past_job_to_current_title():
    html = '''<title>中南大学 张三</title><nav>教授 博士生导师</nav>
    <div class="mainRtwo"><h1>Personal Information</h1>
    <p>张三，曾任教授。论文共同作者paper@csu.edu.cn。</p></div>'''
    url = 'https://faculty.csu.edu.cn/zhangsan/zh_CN/index.htm'
    result = related_v7.parse_detail({'_roster_names': {url: '张三'}}, html, url)
    assert result['bio_raw'].startswith('张三，曾任教授')
    assert not result.get('title') and not result.get('supervisor') and not result.get('email')


def test_recovered_fields_keep_manual_provenance():
    spec = importlib.util.spec_from_file_location('crawl_for_csu_test', Path(__file__).parents[1] / 'scripts' / 'crawl.py')
    crawl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawl)
    manual = Provenance(origin='manual', source='local note', fetched_at='2025-01-01')
    prof = Professor(slug='tanaina', name='覃爱娜', school='csu', dept='auto',
                     detail_url='https://faculty.csu.edu.cn/tanaina/zh_CN/index.htm',
                     bio_raw='人工说明', research_direction_raw='人工方向',
                     provenance={'bio_raw': manual, 'research_direction_raw': manual})
    recovered = related_v7.parse_detail({'_roster_names': {prof.detail_url: prof.name}},
                                      (FIXTURES / 'tanaina.html').read_text(encoding='utf-8'), prof.detail_url)
    source = Provenance(source=prof.detail_url, fetched_at='2026-10-15')
    crawl._merge(prof, 'bio_raw', recovered['bio_raw'], source)
    crawl._merge(prof, 'research_direction_raw', '、'.join(recovered['research_directions']), source)
    assert prof.bio_raw == '人工说明' and prof.research_direction_raw == '人工方向'
    assert prof.provenance['bio_raw'] == manual
    assert prof.provenance['research_direction_raw'] == manual
