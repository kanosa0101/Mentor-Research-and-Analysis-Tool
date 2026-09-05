"""厦门大学计算机科学与技术系（cs.xmu.edu.cn）。
教师卡片链接混合: faculty.xmu.edu.cn tsites 主页（tsites 解析+邮箱解密）/
informatics.xmu.edu.cn 文章页（wp 解析, 部分为死链→issues 留痕）。
"""
from sites import tsites
from sites.wp import parse_wp_detail, walk_channels


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def parse_detail(cfg, html, url):
    if "faculty.xmu.edu.cn" in url:
        return tsites.parse_detail(cfg, html, url)
    return parse_wp_detail(cfg, html, url)
