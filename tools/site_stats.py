# -*- coding: utf-8 -*-
"""抓取 Release 下载量，生成/追加本地快照，供 site/stats/ 的趋势图使用。

用法：
    python tools/site_stats.py            # 追加今天的快照
    python tools/site_stats.py --dry-run  # 只看数，不写文件
    python tools/site_stats.py --print    # 顺便打印各版本明细

产物：site/stats/history.json
    {"snapshots": [{"date": "2026-10-17", "total": 8, "versions": {"v1.0.36": 0, ...}}, ...]}

说明：
- 同一天重复运行只覆盖当天那一行，不会堆重复数据。
- 优先用 `gh auth token` 的令牌调接口（配额 5000/h），取不到就匿名（60/h）。
- 只统计 Release 里**以 .exe 结尾**的资产，避免把源码包算进去。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

REPO = "DcC176/replay-radio"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "site", "stats", "history.json")


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def fetch_releases():
    tk = token()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "replay-radio-stats"}
    if tk:
        headers["Authorization"] = "Bearer " + tk
    out, url = [], "https://api.github.com/repos/%s/releases?per_page=100" % REPO
    while url:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                page = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403:
                sys.exit("！GitHub 拒绝（403，多半是配额用完）：去掉令牌里限额 60/h，等整点或用带令牌的环境")
            sys.exit("！请求失败 HTTP %s" % e.code)
        except Exception as e:
            sys.exit("！网络错误：%s（本机可能需要代理）" % e)
        out.extend(page or [])
        url = ""
        for link in (r.headers.get("Link") or "").split(","):
            if 'rel="next"' in link:
                url = link.split("<")[1].split(">")[0]
    return out


def snap_of(releases):
    versions = {}
    for rel in releases:
        tag = rel.get("tag_name") or "?"
        dl = sum(a.get("download_count", 0) for a in rel.get("assets") or []
                 if str(a.get("name", "")).lower().endswith(".exe"))
        versions[tag] = dl
    return {"date": datetime.now().strftime("%Y-%m-%d"),
            "total": sum(versions.values()), "versions": versions}


def load_history():
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and isinstance(data.get("snapshots"), list) else {"snapshots": []}
    except (OSError, ValueError):
        return {"snapshots": []}


def save_history(data):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data["snapshots"].sort(key=lambda s: s.get("date", ""))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不写文件")
    ap.add_argument("--print", dest="show", action="store_true", help="打印各版本明细")
    args = ap.parse_args()

    cur = snap_of(fetch_releases())
    hist = load_history()
    prev = None
    for s in hist["snapshots"]:
        if s.get("date") != cur["date"]:
            prev = s
    if prev is None and hist["snapshots"]:
        prev = hist["snapshots"][-1]

    hist["snapshots"] = [s for s in hist["snapshots"] if s.get("date") != cur["date"]]
    if not args.dry_run:
        hist["snapshots"].append(cur)
        save_history(hist)

    delta = (cur["total"] - prev["total"]) if prev else None
    print("日期 %s  累计 %d 次%s" % (
        cur["date"], cur["total"],
        "" if delta is None else "（较 %s %+d）" % (prev.get("date", "上次"), delta)))

    if args.show:
        for tag, n in sorted(cur["versions"].items(), key=lambda kv: -kv[1]):
            before = (prev or {}).get("versions", {}).get(tag, 0)
            print("  %-10s %5d%s" % (tag, n, "" if prev is None else "  (较上次 %+d)" % (n - before)))

    if args.dry_run:
        print("（--dry-run：未写入）")
    else:
        print("已写入 %s（共 %d 条快照）" % (os.path.relpath(OUT), len(hist["snapshots"])))


if __name__ == "__main__":
    main()
