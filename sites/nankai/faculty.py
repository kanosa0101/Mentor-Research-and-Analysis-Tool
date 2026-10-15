"""南开当前官网分类师资名单；单位语义仅为该院官网收录，不推导招生归属。"""
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from crawler import fetch
from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail


def collect(cfg, page_url, html, fetched_at):
    rows = []
    if cfg['dept'] in ('cs', 'cyber'):
        host = urlsplit(cfg['base_url']).hostname
        for card in BeautifulSoup(html, 'html.parser').select('.img-card'):
            anchor = card.select_one('.img-content a[href]')
            if anchor is None:
                continue
            raw = anchor.get_text(' ', strip=True)
            match = re.fullmatch(r'([\u4e00-\u9fff·]{2,6}(?:[（(][^）)]+[）)])?)\s+(.+)', raw)
            url = urljoin(page_url, anchor['href'])
            if match is None or urlsplit(url).hostname not in (host, host.replace('.nankai.', '-backend.nankai.')):
                raise ValueError('官方卡片姓名或个人链接未识别：' + raw)
            name = re.sub(r'[（(].*?[）)]', '', match[1])
            row = dict(name=name, url=url, profile_url=url, institutes=[], title=match[2], roster_source=page_url, roster_fetched_at=fetched_at)
            if name != match[1]:
                row['aliases'] = [match[1]]
            values = [p.get_text(' ', strip=True) for p in card.select('.img-content p')]
            if len(values) >= 2 and normalize_email(values[1]):
                row['email'] = normalize_email(values[1])
            if len(values) >= 3 and values[2]:
                row['research_direction_raw'] = values[2]
            rows.append(row)
        return rows
    for card in BeautifulSoup(html, 'html.parser').select('.teacher > a[href]'):
        node = card.select_one('.name')
        name = re.sub(r'\s+', '', node.get_text()) if node else ''
        url = urljoin(page_url, card['href'])
        if not re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name) or urlsplit(url).hostname != urlsplit(cfg['base_url']).hostname or not re.search(r'/info/\d+/\d+\.htm$', url):
            continue
        row = dict(name=name, url=url, profile_url=url, institutes=[], roster_source=page_url, roster_fetched_at=fetched_at)
        for node in card.select('.des > div'):
            parts = re.split(r'[:：]', node.get_text(' ', strip=True), maxsplit=1)
            if len(parts) != 2:
                continue
            label, value = re.sub(r'\s+', '', parts[0]), parts[1].strip()
            if label in ('职称', '研究方向') and value:
                row['title' if label == '职称' else 'research_direction_raw'] = value
            if label == '电子邮件' and normalize_email(value):
                row['email'] = normalize_email(value)
        rows.append(row)
    return rows


def iter_roster(cfg):
    if cfg['dept'] in ('cs', 'cyber'):
        people, dates = {}, []
        for url in cfg['list']['urls']:
            html, meta, _ = fetch.fetch_text('GET', url)
            soup = BeautifulSoup(html, 'html.parser')
            if not soup.select('.img-card .img-content a[href]'):
                raise ValueError('当前官网名单未提取到教师：' + url)
            rows = collect(cfg, url, html, meta['fetched_at'])
            if len(rows) != len(soup.select('.img-card .img-content a[href]')):
                raise ValueError('官方卡片数和解析总数不一致')
            for row in rows:
                people.setdefault((row['name'], row['url']), row)
            dates.append(meta['fetched_at'])
        groups = {}
        for row in people.values():
            if row.get('email'):
                groups.setdefault((row['name'], row['email']), []).append(row)
        conflicts = [rows for rows in groups.values() if len({r.get('title') for r in rows}) > 1]
        cfg['_title_conflict_names'] = sorted({row['name'] for rows in conflicts for row in rows})
        for rows in conflicts:
            for row in rows:
                row.pop('title', None)
        return list(people.values()), {'fetched_at': min(dates), 'pages': len(dates)}
    people, dates, seen = {}, [], set()
    for start in cfg['list']['urls']:
        url, category, expected = start, {}, None
        while url:
            if url in seen or len(seen) >= 30 or urlsplit(url).hostname != urlsplit(cfg['base_url']).hostname or not urlsplit(url).path.startswith('/szdw/'):
                raise ValueError('名单分页重复、超限或跨站')
            seen.add(url)
            html, meta, _ = fetch.fetch_text('GET', url)
            soup = BeautifulSoup(html, 'html.parser')
            count = re.search(r'共\s*(\d+)\s*条', soup.get_text(' ', strip=True))
            if count is None:
                raise ValueError('未找到官方名单总数：' + url)
            total = int(count[1])
            if expected is None:
                expected = total
            elif expected != total:
                raise ValueError('分类名单总数在分页间不一致')
            for row in collect(cfg, url, html, meta['fetched_at']):
                category.setdefault((row['name'], row['url']), row)
            dates.append(meta['fetched_at'])
            nxt = next((a for a in soup.select('a[href]') if a.get_text(strip=True) == '下页' and a['href'] and not a['href'].startswith('javascript:')), None)
            url = urljoin(url, nxt['href']) if nxt else None
        if len(category) != expected:
            raise ValueError(f'分类名单总数不符：{start} 官方{expected}，解析{len(category)}')
        people.update(category)
    return list(people.values()), {'fetched_at': min(dates), 'pages': len(seen)}



def _homepage(result, soup, url):
    box = soup.select_one('.wp_articlecontent') or soup.select_one('.v_news_content')
    if box is None:
        return

    def valid(value):
        try:
            parsed = urlsplit(value)
            return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
        except ValueError:
            return False

    label = re.compile(r'主页|homepage', re.I)
    for anchor in box.select('a[href]'):
        if not label.search(anchor.get_text(' ', strip=True)):
            continue
        # 实际href优先于可见文字；错误href不可用另一段文本猜测修补。
        try:
            candidate = urljoin(url, anchor['href'])
        except ValueError:
            candidate = ''
        result.pop('homepage', None)
        if valid(candidate):
            result['homepage'] = candidate
        else:
            result.setdefault('unknown_fields', []).append('个人主页真实href不是有效HTTP(S) URL，原文保留。')
        return
    for paragraph in box.select('p'):
        text = paragraph.get_text(' ', strip=True)
        if not label.search(text):
            continue
        match = re.search(r'\[(https?://[^\]\s]+)\]|\((https?://[^)\s]+)\)', text)
        if match:
            candidate = match[1] or match[2]
            if valid(candidate):
                result['homepage'] = candidate
                return
    if result.get('homepage') and not valid(result['homepage']):
        result.pop('homepage')
        result.setdefault('unknown_fields', []).append('个人主页文本无法确认有效HTTP(S) URL，原文保留。')


def parse_detail(cfg, html, url):
    result = parse_wp_detail(cfg, html, url)
    soup = BeautifulSoup(html, 'html.parser')
    _homepage(result, soup, url)
    if cfg['dept'] in ('cs', 'cyber'):
        form = soup.select_one('.introduce-form .form')
        if form is None:
            raise ValueError('教师详情无可识别基本信息容器；保留名单字段')
        for paragraph in form.select('p'):
            attribute = paragraph.select_one('.attribute')
            if attribute is None:
                continue
            label = re.sub(r'[\s:：]', '', attribute.get_text())
            value = paragraph.get_text(' ', strip=True).split('：', 1)[-1].strip()
            if label == '姓名' and value:
                result['name'] = value
            elif label == '职称' and value:
                result['title'] = value
            elif label == '电子邮件' and normalize_email(value):
                result['email'] = normalize_email(value)
            elif label == '研究方向' and value:
                result['research_directions'] = [value]
            elif label == '所属部门' and value:
                result['institute_from_detail'] = [value]
        if result.get('name') in cfg.get('_title_conflict_names', []):
            result.pop('title', None)
            result['unknown_fields'] = ['同一官方名册同名同邮箱跨分类职称冲突，暂无明确更新依据；职称保持未知，原文保留。']
        return result
    box = BeautifulSoup(html, 'html.parser').select_one('.v_news_content')
    if box is not None:
        # 新版官网将标签、冒号和值分散在多个节点；在正文限定的平文本中读标签。
        text = box.get_text(' ', strip=True)
        labels = r'所属部门|电子邮件|职\s*称|导\s*师|所学专业|研究方向'
        end = r'(?:' + labels + r'|个人主页|电子邮箱)\s*[:：]|个人简介|个人简历|教育.{0,4}经历|工作经历|讲授课程'
        for match in re.finditer(r'(' + labels + r')\s*[:：]\s*(.*?)(?=' + end + r'|$)', text):
            label, value = re.sub(r'\s+', '', match[1]), match[2].strip(' :：')
            if label == '职称' and value:
                result['title'] = value
            elif label == '研究方向' and value:
                result['research_directions'] = [value]
            elif label == '导师':
                bits = [short for full, short in [('博士生导师', '博导'), ('硕士生导师', '硕导')] if full in value]
                if bits:
                    result['supervisor'] = '、'.join(bits)
        for node in box.select('p')[:30]:
            match = re.match(r'^\s*(电子\s*邮件|电子\s*邮箱|职\s*称|研究方向)\s*[:：]\s*(.+)$', node.get_text(' ', strip=True))
            if not match:
                continue
            label, value = re.sub(r'\s+', '', match[1]), match[2].strip()
            if label == '研究方向':
                result['research_directions'] = [value]
            elif label == '职称':
                result['title'] = value
            elif normalize_email(value):
                result['email'] = normalize_email(value)
    return result
