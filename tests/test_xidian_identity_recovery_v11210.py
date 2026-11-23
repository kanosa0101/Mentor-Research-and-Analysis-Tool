"""A named directory link can repair the same Xidian teacher's short entry URL."""
import pytest

from crawler.mentor_recovery import identity


SHORT = 'https://faculty.xidian.edu.cn/TeacherKey'
HOME = SHORT + '/zh_CN/index.htm'


def result(old=SHORT, new=HOME, **parsed):
    original = dict(name='测试导师', detail_url=old, profile_url=old, email='known@xidian.edu.cn')
    evidence = dict(name='测试导师', _identity_profile_home=new)
    evidence.update(parsed)
    return identity(original, evidence, new)


@pytest.mark.parametrize('old', [SHORT, SHORT + '/'])
def test_verified_home_repairs_only_the_same_person_directory(old):
    assert result(old=old) == 'same_xidian_teacher_directory_and_name'


@pytest.mark.parametrize('new', [
    HOME.replace('https:', 'http:'), HOME.replace('faculty.', 'web.'),
    HOME.replace('TeacherKey', 'teacherkey'), HOME.replace('TeacherKey', 'OtherTeacher'),
    HOME.replace('/zh_CN/', '/en/'), HOME.replace('.edu.cn/', '.edu.cn:8443/'),
    HOME + '?id=other', HOME + '#person', HOME.replace('/index.htm', '/research.htm'),
    HOME.replace('.edu.cn/', '.edu.cn.evil.invalid/'),
])
def test_different_identity_or_noncanonical_destination_is_not_a_repair(new):
    assert result(new=new) is None


@pytest.mark.parametrize('old', [
    SHORT.replace('https:', 'http:'), SHORT.replace('faculty.', 'web.'),
    SHORT + '?id=other', SHORT + '#person', SHORT + '/other',
    SHORT.replace('.edu.cn/', '.edu.cn:443/'), SHORT.replace('TeacherKey', '%54eacherKey'),
])
def test_only_a_registered_https_short_entry_is_eligible(old):
    assert result(old=old) is None


@pytest.mark.parametrize('parsed', [
    {'_identity_profile_home': None}, {'_identity_profile_home': SHORT},
    {'name': '另一位导师'}, {'email': 'other@xidian.edu.cn'},
])
def test_missing_person_page_proof_or_conflicting_identity_is_not_a_repair(parsed):
    assert result(**parsed) is None
