"""更新工会名册（发布前跑一次）：萌娘百科 → assets/guilds_seed.json。

目前只抓 VirtuaReal。加别的工会：把页面 URL 加进 GUILDS，重新跑。
解析规则：页面成员表每行只要同时有「成员条目链接」与 space.bilibili.com/<uid>，
就把两者配成一条；条目名里的「(虚拟UP主)」等后缀会在后端展示时去掉。

用法：py -3.11 tools/update_guilds.py
"""
import json
import os
import re
import sys
import urllib.request

GUILDS = [
    ("VirtuaReal", "https://moegirl.icu/VirtuaReal"),
]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "guilds_seed.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def parse(html):
    out, seen = [], set()
    for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        m = re.search(r"space\.bilibili\.com/(\d+)", row)
        if not m:
            continue
        uid = m.group(1)
        if uid in seen:
            continue
        t = re.search(r'<a[^>]*title="([^"]+)"', row)
        if not t:
            continue
        name = re.sub(r"\s+", " ", t.group(1)).strip()
        if name in ("VirtuaReal", "Bilibili主页"):
            continue
        seen.add(uid)
        out.append({"name": name, "uid": uid})
    return out


def main():
    guilds = []
    for name, url in GUILDS:
        try:
            members = parse(fetch(url))
        except Exception as e:
            print("[guilds] %s 抓取失败：%s" % (name, e))
            members = []
        print("[guilds] %s：%d 人" % (name, len(members)))
        if members:
            guilds.append({"name": name, "members": members})
    if not guilds:
        print("没有抓到任何成员，保留原文件")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"guilds": guilds}, f, ensure_ascii=False, indent=1)
    print("写入", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
