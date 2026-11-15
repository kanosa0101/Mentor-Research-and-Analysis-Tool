import pytest
from sites.nudt.roster import parse_detail, VIEW


def test_public_detail_fields_keep_explicit_unit_and_research():
    html='<table><tr><td>姓名：</td><td>测试教师</td></tr><tr><td>学院：</td><td>计算机学院</td></tr><tr><td>导师层次：</td><td>博导</td></tr><tr><td>基本情况：</td><td>主要研究方向：计算机系统、人工智能。teacher@example.edu.cn</td></tr></table>'
    out=parse_detail({'dept_name':'计算机学院'},html,VIEW+'1')
    assert out['name']=='测试教师'
    assert out['research_direction_raw']=='计算机系统、人工智能'
    assert out['supervisor']=='博导'
    assert out['email']=='teacher@example.edu.cn'
    with pytest.raises(ValueError,match='学院归属'):
        parse_detail({'dept_name':'智能科学学院'},html,VIEW+'1')


def test_no_direction_inference_from_publication_or_discipline():
    html='<p>姓名：</p><p>测试教师</p><p>学院：</p><p>计算机学院</p><p>学科：</p><p>人工智能</p><p>基本情况：</p><p>发表论文20篇，指导学生10人。</p>'
    assert 'research_direction_raw' not in parse_detail({'dept_name':'计算机学院'},html,VIEW+'2')
