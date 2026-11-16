from sites.sysu.sysu_cs import parse_detail


def test_current_sysu_profile_uses_contact_card_and_named_sections():
    html = '''<header>教授 roster@sysu.edu.cn</header>
    <article class="node--type-teacher"><div class="teacherinfo"><h1>张老师</h1><p>副教授</p>
    <div class="teacherinfodetail"><p><strong>联系邮箱：</strong> teacher@mail.sysu.edu.cn</p>
    <p><strong>联系地址：</strong> 计算机学院A101</p></div></div>
    <div class="field-body"><h3><strong>教师简介: </strong></h3><p>张老师研究机器学习。</p>
    <h3>研究领域：</h3><p>计算机视觉</p><p>机器学习</p>
    <h3>工作经历:</h3><p>曾任讲师，合作导师李教授。</p></div></article>
    <footer>admin@sysu.edu.cn</footer>'''
    row = parse_detail({}, html, 'https://cse.sysu.edu.cn/teacher/Zhang')
    assert row == dict(name='张老师',title='副教授',email='teacher@mail.sysu.edu.cn',
                       office_address='计算机学院A101',bio_raw='张老师研究机器学习。',
                       research_direction_raw='计算机视觉\n机器学习')


def test_missing_person_email_never_uses_footer_or_other_teacher():
    html = '''<article class="node--type-teacher"><div class="teacherinfo"><h1>张老师</h1><p>副教授</p></div>
    <div class="field-body"><h3>教师简介：</h3><p>与他人 other@sysu.edu.cn 合作</p></div></article>
    <footer>admin@sysu.edu.cn</footer>'''
    assert 'email' not in parse_detail({},html,'https://cse.sysu.edu.cn/teacher/Zhang')


def test_directory_and_challenge_cannot_be_parsed_as_person():
    assert parse_detail({},'<h1>张老师</h1><p>教授 admin@sysu.edu.cn</p>','https://cse.sysu.edu.cn/teacher') == {}
