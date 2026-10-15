"""Read explicit English personal modules; never infer identity from pinyin."""
import re


def identity_names(soup):
    head = soup.select_one('.js-top .info h2')
    keywords = soup.select_one('meta[name="keywords"]')
    description = soup.select_one('meta[name="description"]')
    if not all((head, keywords, description, soup.title)):
        return []
    name = keywords.get('content', '').split(',', 1)[0].strip()
    english = head.get_text(' ', strip=True)
    if (re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name)
            and description.get('content', '').startswith(name + ',')
            and re.fullmatch(r'[A-Za-z ]+', english)
            and soup.title.get_text(strip=True).startswith('华中科技大学主页平台管理系统 ' + english + '--')):
        return [name]
    return []


def parse(soup):
    out = {}
    sections = []
    for box in soup.select('.blockwhite'):
        head = box.select_one('.title .info h2')
        content = box.select_one('.cont')
        if head and content:
            sections.append((head.get_text(' ', strip=True).lstrip('· ').strip(), content))
    for box in soup.select('dl.itempub'):
        head = box.select_one('dt .intit li')
        content = box.find('dd', recursive=False)
        if head and content:
            sections.append((head.get_text(' ', strip=True), content))
    for label, content in sections:
        if label == 'Personal Profile':
            text = content.get_text(' ', strip=True)
            text = re.sub(r'\s*More\+\s*$', '', text)
            if text and text != 'No content':
                out['bio_raw'] = text
        elif label == 'Research Focus':
            values = list(dict.fromkeys(p.get_text(' ', strip=True) for p in content.select('li')))
            values = [value for value in values if value and value != 'No content']
            if values:
                out['research_directions'] = values
    identity = soup.select_one('.dft-side .Psl-info .cont')
    if identity:
        values = set(identity.get_text('\n', strip=True).splitlines())
        for title, chinese in [('Professor', '教授'), ('Associate professor', '副教授'), ('Lecturer', '讲师')]:
            if title in values:
                out['title'] = chinese
                break
        bits = [chinese for title, chinese in [('Supervisor of Doctorate Candidates', '博导'),
                                              ("Supervisor of Master's Candidates", '硕导')] if title in values]
        if bits:
            out['supervisor'] = '、'.join(bits)
    return out
