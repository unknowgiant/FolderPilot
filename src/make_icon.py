# -*- coding: utf-8 -*-
"""生成「文件管理多面手」应用图标（精修版；版本无关，可长期复用）。

风格参照用户提供的效果图：天蓝渐变圆角贴纸方块 +
白色文件夹（后板纯白、前板白描边内填蓝绿渐变）+ 顶部高光。
1024x1024 超采样绘制，输出 assets/app_icon.ico（256/128/64/48/32/16）。
"""
from PIL import Image, ImageDraw
import os

S = 1024
R = 230
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT_DIR, exist_ok=True)

PAD = 20          # 贴纸外圈留白
RING = 24         # 白色外圈宽度
EDGE = 8          # 深色细描边


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def v_gradient_box(size, r, top, bottom):
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        grad.putpixel((0, y), lerp(top, bottom, y / (size - 1)))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def build():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # ---- 底盘 ----
    base = v_gradient_box(S - 2 * PAD, R, (96, 200, 242), (40, 148, 212))
    img.alpha_composite(base, (PAD, PAD))
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).rounded_rectangle([PAD, PAD, S - PAD - 1, S - PAD - 1],
                                           radius=R, outline=255, width=RING)
    img.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), (0, 0), ring)
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).rounded_rectangle([PAD, PAD, S - PAD - 1, S - PAD - 1],
                                           radius=R, outline=255, width=EDGE)
    img.paste(Image.new("RGBA", (S, S), (26, 105, 170, 255)), (0, 0), edge)

    # ---- 顶部高光 ----
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle([PAD + 14, PAD + 14, S - PAD - 15, int(S * 0.50)],
                                         radius=R - 14, fill=(255, 255, 255, 64))
    img.alpha_composite(hl)
    d = ImageDraw.Draw(img)

    W = (255, 255, 255, 255)
    SHADOW = (22, 92, 150, 200)

    # ---- 文件夹后板（纯白，含标签舌）----
    # 阴影层
    d.rounded_rectangle([262, 322, 812, 712], radius=44, fill=SHADOW)
    # 主体
    d.rounded_rectangle([250, 308, 800, 700], radius=44, fill=W)
    # 标签舌
    d.rounded_rectangle([296, 246, 540, 360], radius=32, fill=W)

    # ---- 前板：白描边 + 内部蓝绿渐变 ----
    # 斜面梯形（上宽下略窄收进），顶边在 y=430，底边 y=756
    ft, fb = 430, 756          # 顶 / 底
    fl, fr = 316, 776          # 顶边左右
    flb, frb = 344, 744        # 底边左右（向内收）
    # 阴影层（整体向下偏移 10）
    d.polygon([(fl, ft + 10), (fr, ft + 10), (frb, fb + 10), (flb, fb + 10)], fill=SHADOW)
    d.rounded_rectangle([fl - 2, ft + 8, fr + 2, ft + 56], radius=26, fill=SHADOW)

    # 白色前板（描边即整块白色梯形 + 圆角顶条）
    d.rounded_rectangle([fl - 3, ft - 3, fr + 3, ft + 56], radius=28, fill=W)
    d.polygon([(fl - 3, ft + 20), (fr + 3, ft + 20), (frb + 6, fb + 6), (flb - 6, fb + 6)], fill=W)

    # 内部渐变（挖掉白描边宽度后的区域）
    bw = 22                     # 白描边宽度
    grad = Image.new("RGB", (1, S))
    for y in range(S):
        grad.putpixel((0, y), lerp((168, 224, 235), (23, 132, 138), y / (S - 1)))
    inner_mask = Image.new("L", (S, S), 0)
    di = ImageDraw.Draw(inner_mask)
    di.rounded_rectangle([fl + bw, ft + bw, fr - bw, ft + 60], radius=16, fill=255)
    di.polygon([(fl + bw + 6, ft + 26), (fr - bw - 6, ft + 26),
                (frb - bw, fb - bw), (flb + bw, fb - bw)], fill=255)
    grad_full = grad.resize((S, S)).convert("RGBA")
    img.paste(grad_full, (0, 0), inner_mask)

    # 前板内再叠一道上高光，贴近参考图的玻璃质感
    hl2 = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl2).rounded_rectangle([fl + bw, ft + bw, fr - bw, ft + 170],
                                          radius=16, fill=(255, 255, 255, 60))
    img.alpha_composite(hl2)

    sizes = [256, 128, 64, 48, 32, 16]
    img.save(os.path.join(OUT_DIR, "app_icon.ico"),
             format="ICO", sizes=[(s, s) for s in sizes])
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT_DIR, "app_icon_256.png"))
    img.resize((48, 48), Image.LANCZOS).save(os.path.join(OUT_DIR, "app_icon_48_preview.png"))
    print("已生成", os.path.join(OUT_DIR, "app_icon.ico"))


if __name__ == "__main__":
    build()
