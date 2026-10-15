from unittest.mock import patch
import pytest
from sites.nankai import faculty

CFG = {'school':'nankai','dept':'software','base_url':'https://cs.nankai.edu.cn','list':{'urls':['https://cs.nankai.edu.cn/szdw/js.htm']}}

def page(name='张三',total=1,next_url=''):
    return f'''<div class="teacher"><a href="../info/1084/1127.htm"><div class="name">{name}</div><div class="des"><div>职 称: 教授</div><div>研究方向: 软件工程</div></div></a></div>共{total}条<a href="{next_url}">下页</a>'''

def test_collect_name_and_list_fields():
    row=faculty.collect(CFG,CFG['list']['urls'][0],page(),'2026-10-15')[0]
    assert row['name']=='张三' and row['title']=='教授'
    assert row['research_direction_raw']=='软件工程'
    assert row['roster_fetched_at']=='2026-10-15'
    assert row['url']=='https://cs.nankai.edu.cn/info/1084/1127.htm'
    assert 'supervisor' not in row

def test_follow_real_pagination_and_completeness():
    second=page('李四',2).replace('../info/1084/1127.htm','../info/1084/1128.htm')
    with patch.object(faculty.fetch,'fetch_text',side_effect=[(page(total=2,next_url='js/1.htm'),{'fetched_at':'2026-10-15'},False),(second,{'fetched_at':'2026-10-15'},False)]):
        rows,meta=faculty.iter_roster(CFG)
    assert len(rows)==2 and meta['pages']==2

def test_incomplete_pagination_fails():
    with patch.object(faculty.fetch,'fetch_text',return_value=(page(total=2),{'fetched_at':'2026-10-15'},False)):
        with pytest.raises(ValueError,match='总数'):
            faculty.iter_roster(CFG)

def test_cross_host_person_rejected():
    assert faculty.collect(CFG,'https://cs.nankai.edu.cn/szdw/js.htm',page().replace('../info/1084/1127.htm','https://other.example/info/1084/1127.htm'),'2026-10-15')==[]

def test_official_empty_category():
    with patch.object(faculty.fetch,'fetch_text',return_value=('共0条',{'fetched_at':'2026-10-15'},False)):
        rows,meta=faculty.iter_roster(CFG)
    assert rows==[]

def test_detail_split_labels_and_own_email():
    html='''<div class="v_news_content"><p>电子邮件</p><p>: zhangsan@nankai.edu.cn</p><p>职 称</p><p>: 教授</p><p>研究方向</p><p>: 软件工程、人工智能</p><p>导 师：硕士生导师</p></div>'''
    row=faculty.parse_detail(CFG,html,'https://cs.nankai.edu.cn/info/1084/1127.htm')
    assert row['email']=='zhangsan@nankai.edu.cn'
    assert row['title']=='教授'
    assert row['research_directions']==['软件工程、人工智能']
    assert row['supervisor']=='硕导'

def test_current_college_card_retains_qualifier_and_source():
    cfg={**CFG,'dept':'cs','base_url':'https://cc.nankai.edu.cn'}
    html='<div class="img-card"><div class="img-content"><a href="/2021/0323/c13619a548871/page.htm">王刚（计）      教授</a><p></p><p>wg@nankai.edu.cn</p><p>并行计算</p></div></div>'
    row=faculty.collect(cfg,'https://cc.nankai.edu.cn/jswyjy/list.htm',html,'2026-10-15')[0]
    assert row['name']=='王刚' and row['aliases']==['王刚（计）']
    assert row['title']=='教授' and row['research_direction_raw']=='并行计算'
    assert row['roster_source']=='https://cc.nankai.edu.cn/jswyjy/list.htm'


def test_current_profile_structured_fields_override_biography():
    html='<div class="introduce-form"><div class="form"><p><span class="attribute">姓 名：</span><span>张三</span></p><p><span class="attribute">电子邮件：</span><span>zhangsan@nankai.edu.cn</span></p><p><span class="attribute">职 称：</span><span>副教授</span></p><p><span class="attribute">研究方向：</span><span>安全计算</span></p></div></div><div class="wp_articlecontent">张三，曾在某校教授指导下学习。</div>'
    row=faculty.parse_detail({**CFG,'dept':'cs'},html,'https://cc.nankai.edu.cn/2021/0323/c1a2/page.htm')
    assert row['name']=='张三' and row['title']=='副教授'
    assert row['email']=='zhangsan@nankai.edu.cn' and row['research_directions']==['安全计算']


def test_research_stays_in_structured_paragraph_and_email_not_truncated():
    html='<div class="v_news_content"><p>电子 邮箱 ： weiwangorg@163.com</p><p>研究方向：软件工程</p><p>个人主页： https://example.org</p><h2>教育工作经历</h2><p>其他内容</p></div>'
    row=faculty.parse_detail(CFG,html,'https://cs.nankai.edu.cn/info/1/1.htm')
    assert row['email']=='weiwangorg@163.com'
    assert row['research_directions']==['软件工程']


def test_same_email_conflicting_official_cards_clear_title():
    cfg={**CFG,'dept':'cyber','base_url':'https://cyber.nankai.edu.cn','list':{'urls':['https://cyber.nankai.edu.cn/jswyjy/list.htm']}}
    def card(title,url):
        return f'<div class="img-card"><div class="img-content"><a href="{url}">张三      {title}</a><p></p><p>zhangsan@nankai.edu.cn</p><p>安全计算</p></div></div>'
    html=card('教授','/2021/0323/c1a1/page.htm')+card('副教授','/2021/0323/c1a2/page.htm')
    with patch.object(faculty.fetch,'fetch_text',return_value=(html,{'fetched_at':'2026-10-15'},False)):
        rows,meta=faculty.iter_roster(cfg)
    assert len(rows)==2 and all(r.get('title') is None for r in rows)
    assert cfg['_title_conflict_names']==['张三']


@pytest.mark.parametrize(('content','expected'), [
    ('<p>英文主页: [https://example.org]</p>', 'https://example.org'),
    ('<p>个人主页: [我的主页](https://example.org/about)</p>', 'https://example.org/about'),
    ('<p><a href="https://example.org/real/[v1]">英文主页: [https://example.org/text]</a></p>', 'https://example.org/real/[v1]'),
    ('<p><a href="https://[2001:db8::1]/">个人主页</a></p>', 'https://[2001:db8::1]/'),
])
def test_homepage_prefers_declared_href_and_text_delimiters(content,expected):
    html='<div class="v_news_content">'+content+'</div>'
    row=faculty.parse_detail(CFG,html,'https://cs.nankai.edu.cn/info/1/1.htm')
    assert row['homepage']==expected

def test_invalid_real_homepage_href_is_not_guessed_from_text():
    html='<div class="v_news_content"><a href="https://example.org]">个人主页: [https://example.org]</a></div>'
    row=faculty.parse_detail(CFG,html,'https://cs.nankai.edu.cn/info/1/1.htm')
    assert row.get('homepage') is None
