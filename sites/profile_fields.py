"""Extract explicit personal research statements, never infer interests or degree eligibility."""
import re

from crawler.email_util import normalize_email

HEADINGS = re.compile(r'^(?:主要)?(?:研究方向|研究领域|研究兴趣|科研方向|Research Interests?|Research Areas?)\s*[:：]?\s*(.*)$',re.I)
BOUNDARY = re.compile(r'^(?:承担科研项目情况|科研项目|资助项目|代表论著|代表性论文|发表论文|论文发表|教育背景|教育经历|工作经历|个人简历|个人简介|社会任职|专利成果|专利|奖励荣誉|招生信息|招生要求|联系方式|主要著作|教授课程|Research Projects?|Publications?|Education|Experience)\s*[:：]?\s*$',re.I)


def research(text):
    lines=[re.sub(r'\s+',' ',line).strip() for line in text.splitlines() if line.strip()]
    for i,line in enumerate(lines):
        match=HEADINGS.fullmatch(line)
        if not match:continue
        parts=[match[1]] if match[1] else []
        for following in lines[i+1:]:
            if BOUNDARY.match(following) or HEADINGS.match(following):break
            if len(' '.join(parts))+len(following)>500:break
            parts.append(following)
        value=' '.join(parts).strip(' ：:')
        if value and not re.fullmatch(r'暂无(?:内容)?|未知|待补充|无|None',value,re.I):return value
    # A personal biography can state a direction without a separate heading.
    # Stop at its sentence end; never derive topics from publication titles.
    biography=[]
    for line in lines:
        if BOUNDARY.match(line) and line not in ('个人简介','个人简历'):break
        biography.append(line)
    match=re.search(r'(?:主要)?研究(?:方向|领域|兴趣)(?:为|是|包括|包含|集中在|聚焦于|[：:])\s*([^。]{2,300})',' '.join(biography))
    if match:return match[1].strip(' ：:；;')
    return None


def qualification(text,name):
    """Only a named person's opening self-description establishes supervision."""
    if not name:return None
    name=re.sub(r'\s+','',name)
    value=re.sub(r'\s+','',text).removeprefix('个人简介').removeprefix('个人简历')
    opening=re.split(r'[。；;]',value,maxsplit=1)[0][:180]
    if not opening.startswith(name) or re.search(r'曾|原任|历任|退休|(?:未|不|没有|无|非).{0,6}(?:博士(?:研究)?生导师|硕士(?:研究)?生导师|博导|硕导|导师资格)|取消|撤销|待定|师从|导师为|导师是|合作导师|团队|学生',opening[len(name):]):return None
    kinds=[]
    for pattern,label in ((r'博士(?:研究)?生导师|博导','博导'),(r'硕士(?:研究)?生导师|硕导','硕导')):
        if re.search(pattern,opening):kinds.append(label)
    return '、'.join(kinds) or None


def own_labelled_email(text):
    """One explicitly labelled address in a verified person's biography is usable."""
    candidates=set()
    for match in re.finditer(r'(?:电子邮箱|电子邮件|邮箱|E-?mail)\s*[：:]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',text,re.I):
        prefix=text[max(0,match.start()-18):match.start()]
        if re.search(r'学生|助理|秘书|行政|合作|团队|联系老师|推荐|他人',prefix):continue
        email=normalize_email(match[1])
        if email:candidates.add(email)
    return next(iter(candidates)) if len(candidates)==1 else None
