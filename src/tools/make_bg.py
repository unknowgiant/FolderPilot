# -*- coding: utf-8 -*-
"""从色板原图生成界面壁纸。

色板给的 2048×1152 原图是运营图，左侧或右侧 30% 里烧着「云海初醒」这类
标题 + 口号。当界面背景时，这些字会从侧栏透出来 —— 是别人的宣传语。

试过几种就地消除的办法，都不干净：
  · 整图高斯模糊    → 壁纸变成一块纯色，主题就看不出图了（初版的问题）
  · 区域内模糊      → 羽化带把文字「保护」下来，字号大时字形还在
  · 缩到 1/48 再放大 → 小字能抹掉，100px 的大标题仍留轮廓
  · cv2.inpaint     → 大矩形出现三角伪影
  · 镜像补丁        → 云海这类纹理很好，山水/书法纸面会露对称痕迹
  · 自动定位文字    → 云海纹理、星空噪点的高频和文字一样强，测不准

最后用最朴素也最可靠的办法：直接把文字所在的那条边裁掉。
十套的文字都在左 30% 或右 30% 以内，裁完重新裁成 16:9，画面里没有
一个字，也没有任何修补痕迹，而且主体往往更聚焦。

用法：
    py -3.14 tools/make_bg.py                # 全部重做
    py -3.14 tools/make_bg.py yunhai xinghe  # 只做指定几套
    py -3.14 tools/make_bg.py --check        # 只检查成品

原图缓存：tests/output/_orig/<key>.jpg（缺的从色板 JSON 现下）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "ui", "skins")
CACHE = os.path.join(ROOT, "tests", "output", "_orig")
PLATE = r"C:\Users\unkno\DoubaoWork\chats\2026-11-13\new-chat-2\主题色板.json"

BG_W, BG_H = 1680, 945            # 界面背景（窗口最宽 1320，够用且不虚）
TH_W, TH_H = 1440, 810            # 卡片缩略图

CUT = 0.30   # 裁掉的比例

# 文字压在哪一侧 —— 逐张看过原图确认
SIDE = {
    "yunhai":   "left",     # 左下竖排 + 横排口号
    "xinghe":   "right",    # 右下
    "hupan":    "right",    # 右侧中部
    "mose":     "left",     # 左下
    "zhuying":  "left",     # 左侧中部
    "qinghua":  "left",     # 左下
    "hongri":   "left",     # 左侧中部
    "chicheng": "right",    # 右下
    "yaodong":  "left",     # 左侧中部
    "shishi":   "left",     # 左侧中部（竖排长条）
}


def fetch(key, url):
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, key + ".jpg")
    if os.path.isfile(dst) and os.path.getsize(dst) > 100000:
        return dst
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    open(dst, "wb").write(data)
    return dst


def cut_and_frame(im, side, frac=CUT):
    """裁掉带文字的一条边，再偏上取景裁成 16:9。"""
    W, H = im.size
    if side == "left":
        im = im.crop((int(W * frac), 0, W, H))
    else:
        im = im.crop((0, 0, int(W * (1 - frac)), H))

    w, h = im.size
    want_h = int(w * 9 / 16)
    if h > want_h:
        off = int((h - want_h) * 0.42)      # 偏上，留住天空与远山
        im = im.crop((0, off, w, off + want_h))
    elif h < want_h:
        want_w = int(h * 16 / 9)
        off = int((w - want_w) * 0.5)
        im = im.crop((off, 0, off + want_w, h))
    return im


def build(key, src):
    im = cut_and_frame(Image.open(src).convert("RGB"), SIDE[key])
    bg = im.resize((BG_W, BG_H), Image.LANCZOS)
    bg.save(os.path.join(UI, "bg-%s.webp" % key), "WEBP", quality=82, method=6)
    th = im.resize((TH_W, TH_H), Image.LANCZOS)
    th.save(os.path.join(UI, "%s.webp" % key), "WEBP", quality=80, method=6)
    return (os.path.getsize(os.path.join(UI, "bg-%s.webp" % key)),
            os.path.getsize(os.path.join(UI, "%s.webp" % key)))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--check" in sys.argv:
        for k in SIDE:
            for name in ("%s.webp" % k, "bg-%s.webp" % k):
                p = os.path.join(UI, name)
                if not os.path.isfile(p):
                    print("缺失", name)
                    continue
                im = Image.open(p)
                print("%-18s %-5s %dx%d %8d B" % (name, im.format, im.size[0], im.size[1],
                                                  os.path.getsize(p)))
        return

    plate = json.load(open(PLATE, encoding="utf-8"))
    urls = {t["key"]: t["wallpaper"]["url"] for t in plate["themes"]}
    keys = args or list(SIDE)
    total_b = total_t = 0
    for k in keys:
        src = fetch(k, urls[k])
        b, t = build(k, src)
        total_b += b
        total_t += t
        print("%-9s 裁%-5s bg %7d B  thumb %7d B" % (k, SIDE[k], b, t))
    print("合计 bg %.2f MB + thumb %.2f MB" % (total_b / 1048576, total_t / 1048576))


if __name__ == "__main__":
    main()
