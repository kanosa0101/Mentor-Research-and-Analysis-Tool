"""北航网安现行官方目录：只读取页面中的静态 JSON 名册。"""
from urllib.parse import urljoin

from crawler import fetch
from crawler.mentor_recovery import allowed, directory_fields, inline_rows
from sites.related_roster import parse_detail as parse_person


def iter_roster(cfg):
    records = {}
    for url in cfg['list']['urls']:
        html, meta, _ = fetch.fetch_text('GET', url)
        for row in inline_rows(html):
            name = row.get('title') or row.get('showTitle')
            if not name:
                continue
            fields, href = directory_fields(cfg, html, name)
            target = urljoin(url, href or '')
            if fields and allowed(target, cfg['base_url']):
                fields.pop('_verified_roster_name', None)
                records[name] = dict(fields, url=target, profile_url=target, institutes=[],
                                     roster_source=url, roster_fetched_at=meta['fetched_at'])
    if not records:
        raise ValueError('现行北航网安官方目录未返回可核对教师，保留已有名册')
    return list(records.values()), meta


def parse_detail(cfg, html, url):
    if cfg.get('_expected_name'):
        fields, _ = directory_fields(cfg, html, cfg['_expected_name'])
        if fields:
            return fields
    return parse_person(cfg, html, url)
