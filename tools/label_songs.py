# -*- coding: utf-8 -*-
"""给一场回放补「歌名 / 聊天 / 视频」标注，并把校准后的登记点写回该主播目录。

为什么要这个小工具
    自动分段只能给出「哪几秒有内容」，歌名要靠画面左上角的「歌名：XXX」浮层。
    `seg_refine.py` 读的是「已唱」列表的**累积高度**，遇到列表在右上、或被礼物卡
    盖住的场次会读错（祈心iko 雨夜歌回：23 个登记点，实际只有 9 首歌）。
    这里把「抽帧人工核对 → 写回 labels/setlists/sung」固化成一条命令，后续任何
    一场都能照做，不用再手改 JS。

用法
    1) 生成每段起点的拼图（每张 4 段，标注段号与时间）：
       python tools/label_songs.py sheet --bvid BV1TEpn6cETF --cid 42656730115
       # 图片在 tools/.labels/<cid>/sheet_NN.png
    2) 照着画面把结果写成 JSON（格式见下），再应用：
       python tools/label_songs.py apply --station 3707047143016490 --json my.json

    JSON 格式：
    {
      "cid": "42656730115",
      "setlist": ["雨とカプチーノ", "入秋的..."],      # 可按演唱顺序给
      "sung": [220, 910, 1560],                     # 真正的歌曲起点（秒）
      "labels": {
         "220": {"label": "雨とカプチーノ", "sub": "画面「歌名」核对"},
         "510": {"label": "聊天", "sub": "画面为聊天通知"}
      }
    }

    · `sung` 不给就保留原登记点；给了就整段替换（这是「校准」的关键）。
    · `labels` 按段起点（秒）匹配，页面里人工标签优先级最高。
    · 写之前自动把原文件备份成 *.bak-时间戳，绝不静默覆盖。
"""
import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from auto_segments import find_ffmpeg, get_json, NO_WINDOW, HIDE_SI  # noqa: E402
import seg_refine as sr  # noqa: E402


def station_dir(station, data_dir=None):
    if data_dir:
        base = data_dir
    else:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ReplayRadio",
                            "www", "data", "stations")
        if not os.path.isdir(os.path.join(base, station)):
            base = os.path.join(ROOT, "data", "stations")
    return os.path.join(base, station)


def load_js(path, var):
    if not os.path.exists(path):
        return {}
    txt = io.open(path, encoding="utf-8").read()
    i, k = txt.find("{"), txt.rfind("}")
    if i < 0 or k <= i:
        return {}
    try:
        return json.loads(txt[i:k + 1])
    except ValueError:
        return {}


def write_js(path, var, obj, note):
    if os.path.exists(path):
        bak = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, bak)
        print("备份：%s" % bak)
    body = json.dumps(obj, ensure_ascii=False, indent=1)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write("/* %s */\nwindow.%s = " % (note, var))
        f.write(body)
        f.write(";\n")


def media_url(bvid, cid, qn=64):
    d = get_json("https://api.bilibili.com/x/player/playurl"
                 "?bvid=%s&cid=%s&fnval=1&qn=%d" % (bvid, cid, qn),
                 "https://www.bilibili.com/video/%s" % bvid)
    if d.get("code") != 0:
        raise RuntimeError("playurl code=%s" % d.get("code"))
    return d["data"]["durl"][0]["url"]


def make_sheets(args):
    sdir = station_dir(args.station, args.data_dir)
    seg_all = load_js(os.path.join(sdir, "segments.js"), "SEGMENTS")
    segs = seg_all.get(str(args.cid)) or []
    if not segs:
        print("没有该 cid 的分段：%s" % args.cid)
        return 1
    ff = find_ffmpeg(args.ffmpeg)
    url = media_url(args.bvid, args.cid, args.qn)
    hdr = "Referer: https://www.bilibili.com\r\nUser-Agent: %s\r\n" % sr.UA
    out = os.path.join(ROOT, "tools", ".labels", str(args.cid))
    os.makedirs(out, exist_ok=True)
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
    tiles = []
    for i, s in enumerate(segs, 1):
        tm = int(s["start"]) + args.offset
        p = os.path.join(out, "s%02d_%d.png" % (i, tm))
        if not os.path.exists(p):
            subprocess.run([ff, "-hide_banner", "-loglevel", "error", "-headers", hdr,
                            "-ss", str(tm), "-i", url, "-frames:v", "1", "-y", p],
                           creationflags=NO_WINDOW, startupinfo=HIDE_SI, timeout=120)
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGB")
        w, h = im.size
        crop = im.crop((0, 0, int(w * 0.66), int(h * 0.16))).resize(
            (int(w * 0.66 * 1.7), int(h * 0.16 * 1.7)), Image.LANCZOS)
        tile = Image.new("RGB", (crop.width, crop.height + 26), (18, 18, 22))
        d = ImageDraw.Draw(tile)
        d.text((8, 3), "第 %02d 段  起点+%ds = %d:%02d" % (i, args.offset, tm // 60, tm % 60),
               font=font, fill=(255, 220, 120))
        tile.paste(crop, (0, 26))
        tiles.append(tile)
    per = max(1, args.per)
    for si in range(0, len(tiles), per):
        chunk = tiles[si:si + per]
        H = sum(t.height for t in chunk) + 8 * (len(chunk) - 1)
        sheet = Image.new("RGB", (chunk[0].width, H), (18, 18, 22))
        y = 0
        for t in chunk:
            sheet.paste(t, (0, y))
            y += t.height + 8
        fp = os.path.join(out, "sheet_%02d.png" % (si // per + 1))
        sheet.save(fp)
        print("拼图：%s" % fp)
    print("分段数：%d" % len(segs))
    return 0


def apply_json(args):
    obj = json.load(io.open(args.json, encoding="utf-8"))
    cid = str(obj.get("cid") or "").strip()
    if not cid:
        print("JSON 里缺少 cid")
        return 1
    sdir = station_dir(args.station, args.data_dir)
    if not os.path.isdir(sdir):
        print("找不到主播目录：%s" % sdir)
        return 1
    if obj.get("sung") is not None:
        sung = load_js(os.path.join(sdir, "sung.js"), "SUNGKEYS")
        sung[cid] = [int(x) for x in obj["sung"]]
        write_js(os.path.join(sdir, "sung.js"), "SUNGKEYS", sung,
                 "画面「已唱」登记时刻（人工校准）")
    if obj.get("setlist") is not None:
        sets = load_js(os.path.join(sdir, "setlists.js"), "SETLISTS")
        sets[cid] = [str(x) for x in obj["setlist"]]
        write_js(os.path.join(sdir, "setlists.js"), "SETLISTS", sets,
                 "本场歌单（按演唱顺序，人工核对）")
    if obj.get("labels") is not None:
        labs = load_js(os.path.join(sdir, "labels.js"), "SEGLABELS")
        labs[cid] = {str(k): v for k, v in obj["labels"].items()}
        write_js(os.path.join(sdir, "labels.js"), "SEGLABELS", labs,
                 "分段内容标签（人工读画面核对）")
    print("已写入：%s" % sdir)
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("sheet")
    sh.add_argument("--bvid", required=True)
    sh.add_argument("--cid", required=True)
    sh.add_argument("--station", default="")
    sh.add_argument("--data-dir")
    sh.add_argument("--ffmpeg")
    sh.add_argument("--qn", type=int, default=64)
    sh.add_argument("--offset", type=int, default=5)
    sh.add_argument("--per", type=int, default=4)
    ap_ = sub.add_parser("apply")
    ap_.add_argument("--json", required=True)
    ap_.add_argument("--station", required=True)
    ap_.add_argument("--data-dir")
    args = ap.parse_args()
    return make_sheets(args) if args.cmd == "sheet" else apply_json(args)


if __name__ == "__main__":
    sys.exit(main())
