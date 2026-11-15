from sites.wp import parse_wp_detail


def parse(body):
    return parse_wp_detail({}, '<div class="v_news_content">' + body + '</div>', 'https://example.edu.cn/profile.htm')


def test_direction_preferred_over_broad_field():
    result = parse('<p>研究领域：模式识别，机器学习</p><p>研究方向：</p><p>组学大数据，生物信息学</p><p>个人主页：</p><p>https://example.edu.cn/</p>')
    assert result['research_direction_raw'] == '组学大数据，生物信息学'


def test_dom_fragments_kept_and_next_section_excluded():
    result = parse('<p>研究方向：<span>互联网</span><span>+</span><span>软件架构设计</span></p><h3>主要业绩：</h3><p>发表论文20篇</p>')
    assert result['research_direction_raw'] == '互联网 + 软件架构设计'


def test_empty_direction_falls_back_to_explicit_field():
    result = parse('<p>研究领域：</p><p>计算机系统结构及组成</p><p>研究方向：</p><p>个人主页：</p>')
    assert result['research_direction_raw'] == '计算机系统结构及组成'


def test_comma_and_full_stop_are_not_lost():
    result = parse('<p>研究领域：媒体计算、计算机视觉、模式识别，及其产业化应用。</p><p>电子邮件：teacher@example.edu.cn</p>')
    assert result['research_direction_raw'] == '媒体计算、计算机视觉、模式识别，及其产业化应用。'
    assert result['email'] == 'teacher@example.edu.cn'


def test_inline_biography_and_teaching_not_research():
    result = parse('<p>研究方向：人工智能；个人简介张老师担任院长。</p>')
    assert result['research_direction_raw'] == '人工智能'
    result = parse('<p>研究方向/领域：无线传感器网络</p><p>教学情况：</p><p>主讲计算机网络</p>')
    assert result['research_direction_raw'] == '无线传感器网络'
