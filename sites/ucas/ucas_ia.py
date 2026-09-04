from sites.ucas import cas_lists


def iter_roster(cfg):
    return cas_lists.walk_and_collect(cfg, cfg["list"]["urls"])


def parse_detail(cfg, html, url):
    return cas_lists.parse_generic_detail(cfg, html, url)
