"""Recover only named graduate-directory links from UESTC's CS section."""
import pytest

from crawler import mentor_recovery as recovery

DIRECTORY = 'https://yjsjy.uestc.edu.cn/gmis/jcsjgl/dsfc/index/'
TARGET = 'https://yjsjy.uestc.edu.cn/gmis/jcsjgl/dsfc/dsgrjj/20243?yxsh=08'
HTML = '''<table><tr><td class="yx_class" id="08"><b>
08 计算机科学与工程学院（网络空间安全学院）</b></td></tr>
<tr><td><a href="/gmis/jcsjgl/dsfc/dsgrjj/20243?yxsh=08">
<span>20243&nbsp;</span><div>李雄</div></a></td></tr></table>'''


def test_own_numbered_record_is_a_named_link():
    assert recovery.named_link(HTML, DIRECTORY, TARGET, '李雄')
    assert not recovery.named_link(HTML, DIRECTORY, TARGET, '沈复民')


@pytest.mark.parametrize('html,directory,target', [
    (HTML.replace('id="08"', 'id="07"'), DIRECTORY, TARGET),
    (HTML.replace('计算机科学与工程学院（网络空间安全学院）', '信息与通信工程学院'), DIRECTORY, TARGET),
    (HTML.replace('20243&nbsp;', '12151&nbsp;'), DIRECTORY, TARGET),
    (HTML.replace('<span>20243&nbsp;</span>', ''), DIRECTORY, TARGET),
    (HTML.replace('<div>李雄</div>', '<div>李雄</div><div>沈复民</div>'), DIRECTORY, TARGET),
    (HTML.replace('<div>李雄</div>', '<div>李雄 实验室</div>'), DIRECTORY, TARGET),
    (HTML.replace('yxsh=08', 'yxsh=07'), DIRECTORY, TARGET.replace('yxsh=08', 'yxsh=07')),
    (HTML.replace('yxsh=08', 'yxsh=08&amp;yxsh=07'), DIRECTORY, TARGET + '&yxsh=07'),
    (HTML.replace('yxsh=08', 'yxsh=08#other'), DIRECTORY, TARGET + '#other'),
    (HTML.replace('<tr><td><a', '<tr><td class="yx_class" id="09">09 其他学院</td></tr><tr><td><a'), DIRECTORY, TARGET),
    (HTML.replace('<tr><td><a', '</table><table><tr><td><a'), DIRECTORY, TARGET),
    (HTML.replace('class="yx_class" id="08"', 'class="other" id="08"'), DIRECTORY, TARGET),
    (HTML, DIRECTORY.replace('https:', 'http:'), TARGET),
    (HTML, DIRECTORY + '?school=other', TARGET),
])
def test_numbered_other_unit_or_malformed_link_cannot_prove_identity(html, directory, target):
    assert not recovery.named_link(html, directory, target, '李雄')
