# -*- coding: utf-8 -*-
"""B 站限流体检：一次看清"现在是不是被限流、哪个接口不行"。

用法（在仓库根目录）：
    python tools\check_ban.py

只发 4~5 个请求、每个间隔 0.6 秒 —— **别连续跑**，体检本身也会计入请求密度。
判定口径：
    code=0        正常
    code=-101     未登录（正常，不算限流）
    code=-352     风控（缺指纹 / 需登录）
    code=-799     频率限制
    HTTP 412     硬限流，只能等 B 站解除
"""
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serve  # noqa: E402


def main():
    print("=" * 62)
    print("B 站限流体检  ", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 62)

    left = max(0, serve._BAN["until"] - time.time())
    print("\n【1】本地冷却状态")
    print("  冷却中      :", "是" if left > 0 else "否")
    print("  剩余        : %.0f 秒" % left)
    print("  连续撞了几次 :", serve._BAN.get("strikes"))
    print("  退避上限    : %d 秒" % serve.BAN_MAX)

    print("\n【2】设备指纹 buvid3")
    try:
        ck = serve.buvid_cookie()
        print("  cookie      :", ck or "（无）")
        print("  落盘        :", "有" if os.path.exists(serve.BUVID_FILE) else "无",
              "→", serve.BUVID_FILE)
    except Exception as e:
        print("  异常        :", type(e).__name__, e)

    mid = str(serve.cur_mid() or "")
    try:
        rs = serve.resolve_series(serve.cur_station(), allow_network=True)
        print("\n【3】回放来源: series_id=%s kind=%s total=%s"
              % (rs.get("series_id"), rs.get("kind"), rs.get("total")))
    except Exception as e:
        print("\n【3】回放来源 取不到:", str(e)[:70])

    cases = [
        ("连接指纹 finger/spi",
         "https://api.bilibili.com/x/frontend/finger/spi", "https://www.bilibili.com"),
        ("登录态 nav",
         "https://api.bilibili.com/x/web-interface/nav", "https://www.bilibili.com"),
    ]
    if mid:
        cases.append(("系列列表（歌单/节目单用）",
                      "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
                      "?mid=%s&page_size=20&page_num=1&web_location=333.1387" % mid,
                      "https://space.bilibili.com/%s/lists" % mid))
        cases.append(("开播状态",
                      "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids?uids[]=%s" % mid,
                      "https://live.bilibili.com/"))

    print("\n【4】接口实测（间隔 0.6 秒，避免体检本身变成压力测试）")
    print("  %-26s %-10s %-8s %s" % ("接口", "code", "耗时", "判定"))
    print("  " + "-" * 58)
    results = []
    for name, url, ref in cases:
        t0 = time.time()
        try:
            d = serve.bili_get(url, ref)
            dt = time.time() - t0
            code = d.get("code")
            tag = {0: "正常", -101: "正常（未登录）", -352: "⚠ 风控 -352",
                   -799: "⚠ 频率限制 -799"}.get(code, "code=%s" % code)
            print("  %-26s %-10s %5.2fs  %s" % (name, code, dt, tag))
            results.append((name, code, tag))
        except urllib.error.HTTPError as e:
            dt = time.time() - t0
            tag = "⚠ HTTP 412 硬限流" if e.code == 412 else "HTTP %s" % e.code
            print("  %-26s HTTP %-5s %5.2fs  %s" % (name, e.code, dt, tag))
            results.append((name, e.code, tag))
        except Exception as e:
            dt = time.time() - t0
            print("  %-26s %-10s %5.2fs  %s"
                  % (name, "-", dt, "%s: %s" % (type(e).__name__, str(e)[:40])))
            results.append((name, None, "异常"))
        time.sleep(0.6)

    print("\n【5】结论")
    bad = [r for r in results if r[1] not in (0, -101)]
    if not bad:
        print("  ✅ 当前没有被限流：所有接口都拿到了正常响应（-101 只是没登录，不算限流）")
    elif any(r[1] == 412 for r in bad):
        print("  ❌ 正处于硬限流（HTTP 412），需要等 B 站解除；本地已进入指数退避")
    else:
        print("  ⚠ 部分接口异常：")
        for n, c, t in bad:
            print("     - %s → %s" % (n, t))
    print("\n  提示：本次只发了 %d 个请求。反复跑体检本身也会加重限流。" % len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
