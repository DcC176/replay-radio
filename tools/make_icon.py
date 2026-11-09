# -*- coding: utf-8 -*-
"""从 `tools/icon_source.jpg` 生成站点图标。

一处源图，三个用途：
  * `favicon.ico`   —— 浏览器标签页 / 收藏夹，以及 PyInstaller 打包出来的 EXE 图标
                       （build_exe.py 用 `--icon favicon.ico`）；桌面快捷方式
                       `IconLocation = <exe>,0` 也就跟着一起换了。
  * `favicon.png`   —— index.html 里显式声明的 PNG，供高 DPI 标签页 / 收藏夹使用。

用法：
    python tools/make_icon.py
"""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "icon_source.jpg")
ICO = os.path.join(ROOT, "favicon.ico")
PNG = os.path.join(ROOT, "favicon.png")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
         (128, 128), (256, 256)]


def main():
    src = Image.open(SRC).convert("RGBA")
    if src.width != src.height:
        raise SystemExit("图标源图必须是正方形，当前为 %dx%d" % src.size)
    # 先高质量缩到 256，再让 Pillow 从它生成 ICO 的其余尺寸（避免逐级劣化）
    base = src.resize((256, 256), Image.LANCZOS)
    base.save(ICO, sizes=SIZES)
    base.resize((64, 64), Image.LANCZOS).save(PNG)
    print("已生成 %s（%s）与 %s" % (ICO, ", ".join(str(s[0]) for s in SIZES), PNG))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
