"""Bounded personal sections in CSU's older tabbed and bilingual templates."""
import re


def sections(soup):
    result = {}
    for panel in soup.select('.TabbedPanels'):
        labels = panel.select('.TabbedPanelsTabGroup > .TabbedPanelsTab')
        contents = panel.select('.TabbedPanelsContentGroup > .TabbedPanelsContent')
        if len(labels) == len(contents):
            for label, content in zip(labels, contents):
                result[label.get_text(strip=True)] = content
    for heading in soup.select('.teacher_mid_midRlanmT'):
        content = heading.find_next_sibling(class_='teacher_mid_midRlanmB')
        if content:
            result[heading.get_text(strip=True)] = content
    for heading in soup.select('.mainRtwo > h1'):
        if heading.get_text(strip=True) == 'Personal Information':
            result['个人简介'] = heading.parent
    for box in soup.select('.itembox'):
        heading = box.select_one('.con-title h3')
        if heading and heading.get_text(strip=True) in ('个人简介', '研究方向'):
            content = box.select_one('.account-con, .direct')
            if content:
                result[heading.get_text(strip=True)] = content
    return result


def identity_names(soup):
    """A bilingual page may name its Chinese identity at the bio opening."""
    bio = sections(soup).get('个人简介')
    if bio is None:
        return []
    text = bio.get_text(' ', strip=True)
    text = re.sub(r'^Personal Information\s*', '', text)
    match = re.match(r'^([\u4e00-\u9fff·]{2,6})[，,]', text)
    return [match.group(1)] if match else []


def parse(soup):
    out = {}
    for label, box in sections(soup).items():
        text = box.get_text(' ', strip=True)
        text = re.sub(r'^Personal Information\s*', '', text)
        if not text or text == '暂无内容':
            continue
        if label == '个人简介':
            out['bio_raw'] = text
            # Only the explicit opening self-description, never past jobs/papers.
            first = text.split('。', 1)[0]
            match = re.match(r'^[\u4e00-\u9fff·]{2,6}，[^。]{0,50}?(副教授|教授|讲师)(?:[，、]|$)', first)
            if match and not re.search(r'曾|原任|历任|退休|前任', match.group(0)):
                out['title'] = match.group(1)
            direction = re.search(r'(?:主要)?研究方向[：:]\s*([^。\n]+)', first)
            # Explicit direction sentence inside the bounded personal bio.
            if direction is None:
                direction = re.search(r'(?:主要)?研究方向[：:]\s*([^。\n]+)', text)
            if direction:
                out['research_directions'] = [direction.group(1).strip()]
        elif label == '研究方向':
            values = [p.get_text(' ', strip=True) for p in box.select('p')]
            values = list(dict.fromkeys(v for v in values if v and v != '暂无内容'))
            if values:
                out['research_directions'] = values
    identity = soup.select_one('#contentscroll2, .teacher_mid_topRin, .mainRthere .mainRline')
    if identity:
        for line in identity.get_text('\n', strip=True).splitlines():
            value = line.strip()
            if value in ('教授', '副教授', '讲师', 'Professor', 'Associate Professor', 'Lecturer'):
                out['title'] = {'Professor': '教授', 'Associate Professor': '副教授', 'Lecturer': '讲师'}.get(value, value)
            if value == "Supervisor of Master's Candidates":
                out['supervisor'] = '硕导'
            elif value == 'Supervisor of Doctorate Candidates':
                out['supervisor'] = '博导'
    return out
