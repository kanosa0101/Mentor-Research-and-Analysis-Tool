"""Recover RUC card links without treating research/course text as a name."""
from datetime import timedelta

import pytest

from crawler import mentor_quality as quality, mentor_recovery as recovery
from tests.test_mentor_quality_v1114 import NOW, body, put, root


DIRECTORY='https://info.ruc.edu.cn/jsky/szdw/ajxjgcx/bx/bx1/index.htm'
TARGET='https://info.ruc.edu.cn/jsky/szdw/ajxjgcx/jsjkxyjsx1/js2/'+'a'*32+'.htm'


def card(name='张老师',target=TARGET):
    return (f'<a href="{target}"><div class="research-img"></div><div class="research-text">'
            f'<div class="text1">{name}</div><div class="text2">研究方向</div>'
            '<div class="text3">机器学习、数据库系统和软件工程</div>'
            '<div class="text2">讲授课程</div><div class="text3">程序设计</div></div></a>')


def configure(root):
    cfg=quality.load_yaml(root/'sites/test/cs.yaml')
    cfg.update(base_url='https://info.ruc.edu.cn',profile_lookup_urls=[DIRECTORY])
    put(root/'sites/test/cs.yaml',cfg)
    issue_path=root/'data/issues/test-cs.yaml'
    issues=quality.load_yaml(issue_path)
    issues[0].update(message='HTTP 404',automatic_check=dict(status='error',reason='HTTP 404',
        source_urls={'profile':'https://test.edu.cn/old'}))
    put(issue_path,issues)
    return cfg


def test_directory_card_recovery_uses_current_parent_name_and_existing_email(root):
    cfg=configure(root)
    requested=[]
    def fetch(source):
        url=source['url'];requested.append(url)
        assert not url.endswith('/old')
        return body() if url==TARGET else card() if url==DIRECTORY else '<p>学校首页</p>'
    result=quality.run(root,fetcher=fetch,now=NOW)
    assert result['resolved']==1
    assert result['results'][0]['replacement']['identity_basis']=='name_and_email'
    assert quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')['detail_url']==TARGET
    assert requested.count(DIRECTORY)==1
    assert recovery.named_link(card(),DIRECTORY,TARGET,'张老师')
    assert recovery.named_link(card(),DIRECTORY.replace('index.htm','index4.htm'),TARGET,'张老师')


@pytest.mark.parametrize('change', ['missing_name','two_names','foreign_host','non_roster','non_profile','wrong_name'])
def test_name_cells_are_not_accepted_outside_the_exact_directory_card(change):
    html=card();parent=DIRECTORY;target=TARGET
    if change=='missing_name':html=html.replace('class="text1"','class="text3"')
    elif change=='two_names':html=html.replace('张老师</div>','张老师</div><div class="text1">李老师</div>')
    elif change=='foreign_host':parent=parent.replace('info.ruc.edu.cn','other.edu.cn')
    elif change=='non_roster':parent='https://info.ruc.edu.cn/news/index.htm'
    elif change=='non_profile':target='https://info.ruc.edu.cn/news/123.htm';html=card(target=target)
    elif change=='wrong_name':html=card('李老师')
    assert not recovery.named_link(html,parent,target,'张老师')


@pytest.mark.parametrize('email', ['', 'different@test.edu.cn'])
def test_directory_card_does_not_replace_independent_identity(root,email):
    configure(root)
    path=root/'data/professors/test/cs/teacher.yaml';before=path.read_bytes()
    result=quality.run(root,fetcher=lambda s:body(email=email) if s['url']==TARGET else card(),now=NOW)
    assert result['resolved']==0 and result['error']==1
    assert path.read_bytes()==before


def test_cached_card_cannot_migrate_when_current_directory_names_someone_else(root):
    cfg=configure(root)
    recovery.directory_index(root,cfg,quality.Sources(root,lambda _:card(),NOW.isoformat()))
    path=root/'data/professors/test/cs/teacher.yaml';before=path.read_bytes()
    def fetch(source):
        assert source['url']!=TARGET
        return card('李老师')
    result=quality.run(root,fetcher=fetch,now=NOW+timedelta(hours=1))
    assert result['error']==1 and '不再链接' in result['results'][0]['reason']
    assert path.read_bytes()==before
