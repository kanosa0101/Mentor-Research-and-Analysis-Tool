from pathlib import Path
import importlib.util

import pytest

from crawler.model import Professor, Provenance
from sites import related_v7

FIXTURES = Path(__file__).parent / 'fixtures' / 'hust_v14'
PEOPLE = [('hanshoudong', '韩守东', 'http://faculty.hust.edu.cn/hanshoudong'),
          ('zouxu', '邹旭', 'http://faculty.hust.edu.cn/zx'),
          ('zhoujiaxi', '周家喜', 'http://faculty.hust.edu.cn/ZHOUJIAXI/zh_CN/index.htm')]


@pytest.mark.parametrize('ref,name,url', PEOPLE)
def test_hust_official_personal_modules(ref, name, url):
    html = (FIXTURES / (ref + '.html')).read_text(encoding='utf-8')
    result = related_v7.parse_detail({'_roster_names': {url: name}}, html, url)
    assert result['bio_raw'] and 'No content' not in result['bio_raw']
    assert not result.get('email')
    if ref == 'hanshoudong':
        assert result['title'] == '副教授'
        assert result['supervisor'] == '博导、硕导'
        assert result['research_directions'][0] == '计算机视觉'
        assert len(result['research_directions']) == 5
    elif ref == 'zouxu':
        assert result['research_directions'] == ['计算机视觉与智能感知计算']
        assert not result.get('title') and not result.get('supervisor')
    else:
        assert result['title'] == '教授' and result['supervisor'] == '博导、硕导'
        assert result['research_directions'] == ['空天地一体化信息网络']


@pytest.mark.parametrize('ref,name,url', PEOPLE)
def test_hust_similar_name_rejected(ref, name, url):
    html = (FIXTURES / (ref + '.html')).read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='身份'):
        related_v7.parse_detail({'_roster_names': {url: name + '甲'}}, html, url)


def test_pinyin_and_non_identity_keywords_do_not_confirm_zhouke():
    url = 'http://faculty.hust.edu.cn/zhouke2/'
    html = (FIXTURES / 'zhouke.html').read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='身份'):
        related_v7.parse_detail({'_roster_names': {url: '周可'}}, html, url)


def test_hust_recovered_fields_keep_manual_values():
    spec = importlib.util.spec_from_file_location('crawl_hust_test', Path(__file__).parents[1] / 'scripts' / 'crawl.py')
    crawl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawl)
    ref, name, url = PEOPLE[0]
    manual = Provenance(origin='manual', source='local note', fetched_at='2025-01-01')
    prof = Professor(slug=ref, name=name, school='hust', dept='aia', detail_url=url,
                     bio_raw='人工说明', title='教授', provenance={'bio_raw': manual, 'title': manual})
    parsed = related_v7.parse_detail({'_roster_names': {url: name}},
                                    (FIXTURES / (ref + '.html')).read_text(encoding='utf-8'), url)
    source = Provenance(source=url, fetched_at='2026-10-15')
    for field in ('bio_raw', 'title'):
        crawl._merge(prof, field, parsed[field], source)
        assert prof.provenance[field] == manual
    assert prof.bio_raw == '人工说明' and prof.title == '教授'
