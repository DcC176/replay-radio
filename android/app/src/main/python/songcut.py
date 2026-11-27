# -*- coding: utf-8 -*-
"""自动歌切：从画面「歌名区」的变化找出每一首歌的起止。

原理（与 tools/subtitle_diff.py 同源，补上「配对」这一步）
    1. ffmpeg **一次**抽帧：`fps=1/step`，只裁歌名区、缩到 320 宽灰度。
       顺序解码，全片分钟级；逐帧 -ss seek 是 10 秒/帧的老路，不要用。
    2. 相邻帧求平均绝对差 → 峰值 = 歌名区发生了明显变化
       （换歌、歌名出现、歌名消失都算）。
    3. 峰值本身只知道「变了」，不知道是「进歌」还是「出歌」。
       用**文字密度**区分：峰值后取一帧算灰度方差/梯度，有歌名时文字像素反差大，
       纯背景时接近平坦。阈值用大津法（Otsu）在全场帧上自适应。
    4. 「进」开区间、「出」闭区间，配对成 [t0, t1]；过滤过短/过长。

与磁盘/网络的关系
    只读 B 站直链（360P 的 durl 足够读字幕），产物写 `tools/.songcut/<cid>/`。
    不碰 data/、不碰用户目录 —— 落盘由 serve.py 的接口负责。

命令行
    python tools/songcut.py --bvid BV1TEpn6cETF --cid 42656730115 --out r.json
    python tools/songcut.py --bvid ... --cid ... --step 10 --region left
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from auto_segments import find_ffmpeg, get_json  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 歌名区（按主播画风不同，默认取原 subtitle_diff 的中右区域）
# 歌名区。**默认左上角**：实测本库主播把「歌名：XXX」放这里；
# 中右那块是人物立绘（原来 subtitle_diff 的 CROP 取自另一个主播的布局，用在这里只抽到脸）。
# ⚠️ 底部是逐句歌词，变化比换歌频繁得多，拿它做切点会把每句歌词当成一首歌。
REGIONS = {
    "songline": "crop=iw*0.28:ih*0.055:0:0.008*ih",
    "center": "crop=iw*0.52:ih*0.12:iw*0.46:ih*0.42",
    "right-top": "crop=iw*0.22:ih*0.20:iw*0.70:ih*0.05",
}


def video_meta(bvid, cid, ttl=3600):
    """取 360P 直链**和时长**（秒）。带 1 小时缓存，避免重复打 B 站接口。

    时长用来把 ffmpeg 的「已处理时长」换算成百分比。放这里而不是靠前端传：
    前端拿的是「分P」的时长，结构一变就容易传 0，进度条就永远停在 10%。
    """
    cache = os.path.join(ROOT, "tools", ".cache", "vmeta_%s_%s.json" % (bvid, cid))
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < ttl:
        try:
            d = json.load(open(cache, encoding="utf-8"))
            if d.get("url"):
                return d["url"], float(d.get("dur") or 0)
        except (OSError, ValueError):
            pass
    last = None
    for i in range(4):
        try:
            d = get_json("https://api.bilibili.com/x/player/playurl"
                         "?bvid=%s&cid=%s&fnval=1&qn=32" % (bvid, cid),
                         "https://www.bilibili.com/video/%s" % bvid)
            if d.get("code") != 0:
                raise RuntimeError("playurl code=%s" % d.get("code"))
            data = d["data"]
            u = data["durl"][0]["url"]
            dur = float(data.get("timelength") or 0) / 1000.0
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump({"url": u, "dur": dur}, f)
            return u, dur
        except Exception as e:              # 代理偶发 502 / 限流
            last = e
            time.sleep(2 + i * 3)
    raise RuntimeError("取视频地址失败：%s" % last)


def grab_frames(ff, url, workdir, step, region="songline", timeout=1800,
                dur=0, on_progress=None):
    """一次抽帧：每 step 秒一帧，只裁 region、缩到 320 宽灰度。返回文件名列表（升序）。"""
    os.makedirs(workdir, exist_ok=True)
    mark = os.path.join(workdir, "_meta.txt")
    # 期望帧数：有总时长就能算出来。抽帧中途被打断时目录里是半截帧，
    # 只凭「区域/步长没变」就复用会把缺帧当成正常结果 —— 所以把帧数也写进标记里校验。
    expect = int(dur / step) + 1 if dur > 0 else 0
    tag = "%s|%g|%d" % (region, step, expect)
    old = sorted(f for f in os.listdir(workdir) if f.startswith("f_") and f.endswith(".png"))
    if old and os.path.exists(mark) and open(mark, encoding="utf-8").read().strip() == tag:
        if not expect or abs(len(old) - expect) <= max(3, int(expect * 0.02)):
            return old                  # 区域、步长、帧数都对得上：直接复用
    for f in old:
        os.remove(os.path.join(workdir, f))
    crop = REGIONS.get(region) or REGIONS["songline"]
    hdr = "Referer: https://www.bilibili.com\r\nUser-Agent: %s\r\n" % UA
    # -progress pipe:1 会按秒吐出 out_time_ms —— 用它换算「已处理 / 总时长」，
    # 否则长场（3~4 小时）抽帧要好几分钟，界面上只能看到固定不变的 10%。
    proc = subprocess.Popen(
        [ff, "-hide_banner", "-loglevel", "error", "-headers", hdr,
         "-probesize", "5000000", "-analyzeduration", "5000000",
         "-i", url,
         "-vf", "%s,fps=1/%g,scale=320:-1,format=gray" % (crop, step),
         "-progress", "pipe:1", "-nostats",
         "-y", os.path.join(workdir, "f_%06d.png")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for raw in proc.stdout:
            if not (dur > 0 and on_progress):
                continue
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("out_time_ms="):
                continue
            try:
                t = int(line.split("=", 1)[1]) / 1e6
            except (ValueError, IndexError):
                continue
            on_progress(max(0.0, min(1.0, t / dur)))
    finally:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    with open(mark, "w", encoding="utf-8") as fh:
        fh.write(tag)
    return sorted(f for f in os.listdir(workdir) if f.startswith("f_") and f.endswith(".png"))


def load_frames(workdir, files):
    """读进内存（320 宽灰度，单帧约 40KB，全片 1~2 千帧 ≈ 几十 MB）。"""
    return [np.asarray(Image.open(os.path.join(workdir, f)), dtype=np.float32) for f in files]


def diff_series(frames, step):
    """相邻帧平均绝对差。第 i 帧对应 t=(i+1)*step（fps 抽帧的第一帧落在 step 处）。"""
    out = []
    prev = None
    for i, img in enumerate(frames):
        t = (i + 1) * step
        if prev is not None and prev.shape == img.shape:
            out.append((t, float(np.mean(np.abs(img - prev)))))
        prev = img
    return out


def find_peaks(diffs, ratio=1.5, floor=8.0):
    """局部极大：显著高于左右各 2 个邻点，且绝对值不能太小。"""
    peaks = []
    for i in range(2, len(diffs) - 2):
        t, d = diffs[i]
        nb = [diffs[j][1] for j in range(i - 2, i + 3) if j != i]
        if nb and d > max(nb) * ratio and d > floor:
            peaks.append({"t": t, "diff": round(d, 2)})
    return peaks


def text_score(img):
    """文字密度：有文字时灰度反差大。

    用「标准差 + 平均梯度」的组合 —— 标准差对大片色块不敏感，梯度对细笔画敏感，
    两者一起用能压住「背景整体变亮/变暗」这类不改变文字量的变化。
    """
    if img.size == 0:
        return 0.0
    std = float(np.std(img))
    gx = float(np.mean(np.abs(np.diff(img, axis=1)))) if img.shape[1] > 1 else 0.0
    gy = float(np.mean(np.abs(np.diff(img, axis=0)))) if img.shape[0] > 1 else 0.0
    return std + 4.0 * (gx + gy)


def row_prefix_vec(img):
    """左端一小块的 8×8 灰度向量 —— 当作「行首图案」的特征。

    为什么要它：左上角这块**不只是歌名**，聊天时还常驻群号/公告（实测
    「企鹅Moe社活动通知群:112754…」）。两种行的「有没有文字」完全一样，
    但**行首图案不同** —— 歌名行以「歌名：」开头，群号行以「企鹅」开头。
    用灰度向量而不是二值哈希：二值化对一像素的抗锯齿抖动都敏感，同一行会被切成许多碎类；
    灰度向量 + 距离阈值可以稳定聚成几类。
    """
    h, w = img.shape
    if h < 4 or w < 8:
        return None
    sub = img[int(h * 0.12):max(int(h * 0.88), int(h * 0.12) + 2),
              0:max(8, int(w * 0.24))]
    small = Image.fromarray(sub.astype(np.uint8)).resize((8, 8))
    return np.asarray(small, dtype=np.float32).flatten()


def cluster_rows(frames, tol=16.0):
    """贪心聚类行首图案，返回每帧的类标（-1 = 无内容）。"""
    centers, labels = [], []
    for f in frames:
        v = row_prefix_vec(f)
        if v is None:
            labels.append(-1)
            continue
        best, bi = 1e9, -1
        for k, c in enumerate(centers):
            d = float(np.mean(np.abs(v - c)))
            if d < best:
                best, bi = d, k
        if bi >= 0 and best < tol:
            labels.append(bi)
            centers[bi] = centers[bi] * 0.85 + v * 0.15     # 缓慢跟随，抗渐变
        else:
            centers.append(v.copy())
            labels.append(len(centers) - 1)
    return labels


def text_extent(img):
    """整行文字的右边界（像素列）。歌名长度不一，群号是固定字符串 —— 用它区分两者。"""
    if img.size == 0:
        return 0
    col = img.max(axis=0)
    thr = max(60.0, float(np.median(col)) + 25.0)
    idx = np.where(col > thr)[0]
    return int(idx[-1]) if idx.size else 0


def pick_song_class(frames, labels, step):
    """找出「歌名行」那一类。

    单看「行宽标准差最大」会选错：换歌瞬间的过渡帧宽度差异很大，但只有二三十帧。
    实测这场里：
        · 群号行 532 帧、宽度恒为满宽（sd≈0）→ 聊天时一直是它
        · 歌名行 234 帧、宽度 237±77、合计约 39 分钟 → 正好是 9 首歌的总时长
    所以判据是三项相乘：**时间占比 × 宽度离散度 × 宽度多样性**。
    """
    n = max(1, len(frames))
    total = n * step
    groups = {}
    for i, lb in enumerate(labels):
        if lb >= 0:
            groups.setdefault(lb, []).append(i)
    best, best_score, stats = None, 0.0, []
    for lb, idxs in groups.items():
        widths = [text_extent(frames[i]) for i in idxs]
        sd = float(np.std(widths))
        span = len(idxs) * step / float(total)          # 时间占比
        # 宽度多样性：量化到 10px 后有多少个不同取值（每首歌名长度不同 → 多个）
        uniq = len(set(int(w / 10) for w in widths))
        score = sd * min(1.0, span / 0.15) * min(1.0, uniq / 4.0)
        stats.append((lb, len(idxs), round(sd, 1), round(span, 2), uniq, round(score, 1)))
        if span >= 0.06 and sd >= 15 and uniq >= 2 and score > best_score:
            best, best_score = lb, score
    stats.sort(key=lambda x: -x[5])
    if best is None:
        return None, 0.0, stats
    return best, round(best_score, 1), stats


def otsu(values, bins=64):
    """一维大津法阈值（值域自适应，不依赖固定常量）。"""
    a = np.asarray(values, dtype=np.float64)
    if a.size < 4:
        return float(np.max(a) if a.size else 0.0)
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-6:
        return hi
    hist, edges = np.histogram(a, bins=bins, range=(lo, hi))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return hi
    w0 = np.cumsum(hist)
    w1 = total - w0
    centers = (edges[:-1] + edges[1:]) / 2.0
    s0 = np.cumsum(hist * centers)
    s1 = s0[-1] - s0
    with np.errstate(divide="ignore", invalid="ignore"):
        m0 = np.where(w0 > 0, s0 / w0, 0.0)
        m1 = np.where(w1 > 0, s1 / w1, 0.0)
        between = w0 * w1 * (m0 - m1) ** 2
    between = np.nan_to_num(between)
    return float(centers[int(np.argmax(between))])


def segment_songs(frames, diffs, step, min_len=60, max_len=900):
    """先把「有歌名 / 无歌名」切成大区间，再在区间内按强差分切成多首。

    为什么不用「峰值进/出配对」：左上角那块**同时**会出现歌名和聊天通知，
    通知只持续几秒，配对时会被当成「进歌」→ 误报。改用**持续性**判据后，
    只有文字连续存在（≥ min_len）才算一首歌。

    返回 (songs, thr, scores)。
    """
    n = len(frames)
    scores = [text_score(f) for f in frames]
    thr = otsu(scores)
    # 整场大半时间都有歌名时，大津法会切在分布内部 → 用中位数的 0.75 兜底
    thr = max(thr, float(np.median(scores)) * 0.75)

    labels = cluster_rows(frames)
    song_cls, hv_sd, cls_stats = pick_song_class(frames, labels, step)
    if song_cls is not None:
        # 有明确的「歌名类」行首图案：直接按它筛，聊天时的群号行天然被排除
        on = [lb == song_cls for lb in labels]
    else:
        # 全场只有一种行（有的主播没有常驻群号）：退回「文字密度」判据
        on = [sc >= thr for sc in scores]
    # 5 帧窗口里至少 3 帧命中 → 压掉换歌瞬间的单帧过渡，但不吃掉整段
    on = [sum(on[max(0, i - 2):min(n, i + 3)]) >= min(3, i + 3) for i in range(n)]

    runs = []
    st = None
    for i, v in enumerate(on):
        if v and st is None:
            st = i
        elif not v and st is not None:
            runs.append((st, i - 1))
            st = None
    if st is not None:
        runs.append((st, n - 1))

    def t_of(i):
        """第 i 帧（0-based）的起点时间：fps 抽帧第一帧落在 step 处。"""
        return (i + 1) * step

    songs = []
    for a, b in runs:
        seg = [diffs[i][1] for i in range(max(1, a), min(len(diffs), b + 1))]
        if not seg:
            continue
        # 区间内的强差分阈值：用自身 P85，避免全场阈值被别的场次拉偏
        pthr = max(12.0, float(np.percentile(seg, 85)) * 1.15)
        cuts = [a]
        for i in range(a + 1, b + 1):
            if i - 1 < len(diffs) and diffs[i - 1][1] >= pthr:
                if (i - cuts[-1]) * step >= min_len:      # 太近的不切，防止碎成渣
                    cuts.append(i)
        cuts.append(b + 1)
        for k in range(len(cuts) - 1):
            t0, t1 = t_of(cuts[k]), t_of(cuts[k + 1])
            d = t1 - t0
            if min_len <= d <= max_len:
                songs.append({"t0": float(t0), "t1": float(t1),
                              "conf": 0.7 if d >= 90 else 0.55, "src": "frame"})
    songs.sort(key=lambda x: x["t0"])
    return songs, thr, scores, (song_cls is not None, round(hv_sd, 1)), cls_stats


def run(bvid, cid, step=5.0, region="songline", dur=0, progress=None):
    """完整流水线。progress(phase, ratio) 可选回调，供接口报进度。"""
    t_start = time.time()

    def say(phase, ratio):
        if progress:
            try:
                progress(phase, ratio)
            except Exception:
                pass

    ff = find_ffmpeg("")
    if not ff:
        raise RuntimeError("本机没找到 ffmpeg，无法抽帧")
    say("取播放地址", 0.02)
    url, info_dur = video_meta(bvid, cid)
    dur = float(dur or 0) or info_dur
    workdir = os.path.join(ROOT, "tools", ".songcut", str(cid))
    say("抽帧（顺序解码，分钟级）", 0.10)
    files = grab_frames(ff, url, workdir, step, region, dur=dur,
                        on_progress=lambda p: say("抽帧 %d%%" % int(p * 100),
                                                  0.10 + 0.45 * p))
    if not files:
        raise RuntimeError("抽帧结果为空（可能是直播中/无权限/网络失败）")
    say("读取帧", 0.55)
    frames = load_frames(workdir, files)
    say("计算差分", 0.65)
    diffs = diff_series(frames, step)
    peaks = find_peaks(diffs)
    say("判定歌名区间", 0.75)
    total_dur = dur or (len(frames) + 1) * step
    songs, thr, _scores, (has_songline, hv_sd), cls_stats = segment_songs(frames, diffs, step)
    say("完成", 1.0)
    return {
        "bvid": bvid, "cid": cid, "step": step, "region": region,
        "dur": round(total_dur, 1), "frames": len(frames), "peaks": len(peaks),
        "thr": round(thr, 2), "hasSongline": has_songline, "lineWidthSd": hv_sd,
        "rowClasses": cls_stats[:6],
        "songs": songs,
        "elapsed": round(time.time() - t_start, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", required=True)
    ap.add_argument("--cid", required=True)
    ap.add_argument("--step", type=float, default=5.0)
    ap.add_argument("--region", default="songline", choices=list(REGIONS))
    ap.add_argument("--dur", type=float, default=0)
    ap.add_argument("--out")
    a = ap.parse_args()
    r = run(a.bvid, a.cid, a.step, a.region, a.dur,
            progress=lambda ph, ra: print("  [%3d%%] %s" % (int(ra * 100), ph)))
    print("\n帧 %d / 峰值 %d / 歌 %d / 用时 %.1fs" % (
        r["frames"], r["peaks"], len(r["songs"]), r["elapsed"]))
    for i, s in enumerate(r["songs"], 1):
        print("  %2d  %6.0f–%-6.0f  %5.1f 分钟  conf=%.2f" % (
            i, s["t0"], s["t1"], (s["t1"] - s["t0"]) / 60, s["conf"]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print("已写 %s" % a.out)


if __name__ == "__main__":
    main()
