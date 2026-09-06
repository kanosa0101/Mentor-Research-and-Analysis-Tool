"""东北大学计算机学院（wp 站）。
wp 解析后处理：页面页脚"邮箱：neucse@cse.neu.edu.cn"是学院公邮不能当作
教师邮箱；教师本人邮箱在简介里以"电子邮件 xxx@cse.neu.edu.cn"出现。
"""
import re

from bs4 import BeautifulSoup

from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail, walk_channels

_DEPT_EMAIL = "neucse@cse.neu.edu.cn"


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def parse_detail(cfg, html, url):
    out = parse_wp_detail(cfg, html, url)
    email = out.get("email")
    if email and "neucse@" in email.lower():
        del out["email"]  # 学院公邮, 非教师本人
    if "email" not in out:
        # 教师邮箱藏在简介文本里。标签变体多(电子邮件/电子邮箱/联系方式/邮件联系…),
        # 且常被 span 等标签隔断, 必须在 get_text 纯文本上搜; 文章正文在页脚之前,
        # 页脚"邮箱：neucse@…"是学院公邮, 由 neucse 过滤兜底
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        m = re.search(r"(?:电子邮件|电子邮箱|E-?mail|联系方式|邮件联系|邮箱|信箱)"
                      r"\s*[：:]?\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
                      text, re.I)
        if m and "neucse" not in m.group(1).lower():
            e = normalize_email(m.group(1))
            if e:
                out["email"] = e
    return out
