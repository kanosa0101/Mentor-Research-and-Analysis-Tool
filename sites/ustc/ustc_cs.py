from sites.wp import parse_wp_detail, walk_channels


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)
