# -*- coding: utf-8 -*-
"""定位壁纸里的宣传文字：在给定粗范围内，用高频响应找出文字带的精确边界。

文字是细笔画、局部高频，云雾/水面/天空是低频；在粗范围内按行/列统计
高频能量，取显著高于背景的连续区段，就是文字的包围盒。

用法：py -3.14 tests/measure_text.py
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = os.path.join(ROOT, "tests", "output", "_orig")

# 粗范围（人工估的象限），只用来限定搜索，不参与最终结果
COARSE = {
    "yunhai":   (0, 30, 30, 100),
    "xinghe":   (60, 70, 100, 100),
    "hupan":    (60, 20, 100, 80),
    "mose":     (0, 60, 30, 100),
    "zhuying":  (0, 20, 25, 65),
    "qinghua":  (0, 65, 30, 100),
    "hongri":   (0, 20, 30, 65),
    "chicheng": (60, 65, 100, 100),
    "yaodong":  (0, 20, 25, 65),
    "shishi":   (0, 35, 30, 90),
}


def band(score, thr_ratio=0.35):
    """在一维能量序列里找最显著的连续区段。"""
    peak = score.max()
    if peak <= 1e-6:
        return 0, len(score) - 1
    idx = np.where(score > peak * thr_ratio)[0]
    if len(idx) == 0:
        return 0, len(score) - 1
    # 取包含峰值的最长连续段
    groups, start = [], idx[0]
    for a, b in zip(idx, idx[1:]):
        if b - a > 6:
            groups.append((start, a))
            start = b
    groups.append((start, idx[-1]))
    best = max(groups, key=lambda g: score[g[0]:g[1] + 1].sum())
    return int(best[0]), int(best[1])


def measure(key):
    p = os.path.join(ORIG, key + ".jpg")
    img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    H, W = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hp = np.abs(g - cv2.GaussianBlur(g, (0, 0), 6))

    x0, y0, x1, y1 = COARSE[key]
    X0, Y0 = int(x0 / 100 * W), int(y0 / 100 * H)
    X1, Y1 = int(x1 / 100 * W), int(y1 / 100 * H)
    roi = hp[Y0:Y1, X0:X1]

    ry0, ry1 = band(roi.mean(axis=1))
    rx0, rx1 = band(roi.mean(axis=0))
    # 留 1.2% 余量
    pad_x, pad_y = int(W * 0.012), int(H * 0.012)
    fx0 = max(0, X0 + rx0 - pad_x); fx1 = min(W, X0 + rx1 + pad_x)
    fy0 = max(0, Y0 + ry0 - pad_y); fy1 = min(H, Y0 + ry1 + pad_y)
    return (round(fx0 / W * 100, 1), round(fy0 / H * 100, 1),
            round(fx1 / W * 100, 1), round(fy1 / H * 100, 1))


if __name__ == "__main__":
    keys = sys.argv[1:] or list(COARSE)
    print("TEXT_BOX = {")
    for k in keys:
        bx = measure(k)
        print('    "%s": %s,' % (k, bx))
    print("}")
