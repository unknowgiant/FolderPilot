# -*- coding: utf-8 -*-
"""由「主题色板」生成界面皮肤 CSS 与前端元数据。

输入：tools/skins.json（8 个令牌：bg / surface / text / accent / accent-strong /
      overlay / scheme / bg-image）
输出：ui/skin-themes.css   —— 每套主题的全量界面变量 + 壁纸 + 玻璃层钩子
      ui/js/skins.js       —— 皮肤清单（名称、分类、壁纸、强调色、可读下限）

为什么不让界面直接吃那 8 个令牌：现有界面用到 22 个变量（面板三层、分隔线、
hover、选中、阴影、玻璃层…）。这里按色板的 bg/surface/text/accent 用「混色 +
对比度校验」推出来，保证 10 套主题的层次关系一致，且正文与强调色在各自面板
上都能过 WCAG AA。

1.8 起的关键改动：**校验对象从「不透明面板」换成「真实渲染出来的底色」**。
面板是半透明的（--plate-a），底下还压着一层壁纸蒙层（--wall-scrim）和壁纸本身，
最终落在文字底下的是这三层的合成结果。旧版只比 text 与 surface 两个实色，于是
红色主题（壁纸高光接近纯白）看起来「校验通过、肉眼看不清」。现在的做法：

  壁纸 → brightness/saturate 提亮 → 蒙层 → 面板 alpha 合成 → 取 P02/P50/P98
  三个亮度带的颜色，正文在这三个带里都要过 4.5:1。

字色也不再照抄色板的 text，而是从色板出发逐级「推远」（向白或向黑），取第一个
达标的层级——所以换主题后字色是跟着主题自动变的，而不是复用上一个主题的墨色。

用法：
    py -3.14 src/tools/gen_skins.py           # 生成
    py -3.14 src/tools/gen_skins.py --check   # 只校验对比度，不写文件
"""
from __future__ import annotations

import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 壁纸提亮目标（平均感知亮度 0-255）：深色主题落到暗调，浅色主题落到浅调
DARK_TARGET = 66
LIGHT_TARGET = 175
SRC = os.path.join(ROOT, "tools", "skins.json")
OUT_CSS = os.path.join(ROOT, "ui", "skin-themes.css")
OUT_JS = os.path.join(ROOT, "ui", "js", "skins.js")

# 对比度门限：正文 AA 4.5，次要信息（大小/时间）3.6，提示（路径、状态）2.8
INK_MIN = 4.5
INK2_MIN = 3.6
INK3_MIN = 2.8
# 生成时留一点余量，免得刚好 4.5 被抗锯齿磨掉
MARGIN = 1.08
# 取色带：最暗 2%、中间、最亮 2%。文字压在哪个带上都要看得清，
# 所以两个极端都要过门限——只看平均值正是旧版漏掉红色主题的原因。
BANDS = (0.02, 0.50, 0.98)
# 下采样网格：640×360 的窗口下每格约 10px，对齐 backdrop-filter 的模糊半径
GRID = (128, 72)
# 面板设计厚度（玻璃感）与最薄处
PANE_A = {True: 0.48, False: 0.44}
CHROME_A = {True: 0.24, False: 0.30}
# 默认厚度按「舒适」反推（5.6），下限按「可读」反推（4.5）。
# 两者之间的差就是滑杆的有效行程：默认舒服，往下拖也还能读。
COMFORT_TARGET = 5.6
FLOOR_TARGET = 4.5
# 面板再厚也不超过这个值，否则玻璃感没了、壁纸也白留
PANE_CAP = 0.76


def lift_k(key, dark_ui):
    """壁纸提亮系数：深色主题压到暗调，浅色主题提到浅调。

    暗图提亮是为了不「一锅黑」，亮图压暗是为了不让浅字被冲掉 —— 两头都是
    按平均亮度定的。真正决定文字能不能读的是高光带，那一步在 wall_bands 里。
    """
    lum = bg_lum(key)
    if not lum:
        return 1.0
    target = DARK_TARGET if dark_ui else LIGHT_TARGET
    lo = 0.45 if dark_ui else 1.0
    return max(lo, min(2.0, target / lum))


# ---------------- 颜色工具 ----------------
def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(t):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in t)


def _mix(a, b, w):
    """两组 (r,g,b) 元组混色，w 为 b 的权重。"""
    return tuple(a[i] * (1 - w) + b[i] * w for i in range(3))


def mix(a, b, w):
    """w 为 b 的权重。"""
    return hexc(_mix(rgb(a), rgb(b), w))


def lum(h):
    if isinstance(h, str):
        h = rgb(h)

    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = h
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rgba(h, a):
    r, g, b = rgb(h)
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, a)


def shade(h, w):
    """w>0 提亮（混白），w<0 加深（混黑）。"""
    return mix(h, "#FFFFFF", w) if w > 0 else mix(h, "#000000", -w)


def chroma(h):
    c = rgb(h)
    return max(c) - min(c)


# ---------------- 壁纸剖面 ----------------
def bg_lum(key):
    """量壁纸的平均感知亮度（0-255）。裁边后构图变了，不能用色板里的原图数值。"""
    try:
        from PIL import Image
        im = Image.open(os.path.join(ROOT, "ui", "skins", "bg-%s.webp" % key))
        im = im.convert("RGB").resize((40, 23))
        px = list(im.getdata())
        return sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / len(px)
    except Exception:
        return None


def wall_bands(key, k, dark):
    """套用 --wall-lift 的滤镜后，按亮度取三个分位的代表色。

    面板只挡住一部分，剩下的全靠这张图给的底色；所以必须量「提亮之后」的图，
    而且要看最亮那一带——深色主题被冲掉的正是这里。
    """
    try:
        from PIL import Image, ImageEnhance
        im = Image.open(os.path.join(ROOT, "ui", "skins", "bg-%s.webp" % key))
        im = im.convert("RGB")
        im = ImageEnhance.Brightness(im).enhance(k)
        im = ImageEnhance.Color(im).enhance(1.08 if dark else 1.03)
        if dark:
            im = ImageEnhance.Contrast(im).enhance(1.03)
        im = im.resize(GRID, Image.LANCZOS)
        px = sorted((tuple(float(v) for v in c) for c in im.getdata()), key=lum)
        n = len(px)
        out = []
        for p in BANDS:
            c = min(n - 1, int(p * (n - 1)))
            seg = px[max(0, c - 6):min(n, c + 7)]
            out.append(tuple(sum(x[i] for x in seg) / len(seg) for i in range(3)))
        return out
    except Exception:
        return []


# ---------------- 对比度求解 ----------------
def compose(band, scrim_c, scrim_a, surface_rgb, alpha):
    """壁纸 → 蒙层 → 半透明面板，最终落在文字底下的颜色。"""
    return _mix(_mix(band, scrim_c, scrim_a), surface_rgb, alpha)


def worst_contrast(ink, bands, scrim_c, scrim_a, surface_rgb, alpha):
    if not bands:
        return 21.0
    return min(contrast(ink, compose(b, scrim_c, scrim_a, surface_rgb, alpha))
               for b in bands)


def ink_ladder(text_hex, dark_ui):
    """从色板给的文字色出发，逐级往「更极端」推。

    深色主题的墨是浅色，推的方向是白；浅色主题的墨是深色，推的方向是近黑。
    第一级永远是色板原色——能不动就不动，保住设计意图。
    """
    # 上限收到 0.86：再往纯白/纯黑推就丢了主题的暖调（红色系会变成刺眼的白字），
    # 真不够就让面板加厚 —— 那是更诚实的做法。
    far = rgb("#FFFFFF") if dark_ui else rgb("#0B0D10")
    base = rgb(text_hex)
    return [base] + [tuple(_mix(base, far, w)) for w in (0.25, 0.50, 0.72, 0.86)]


def solve_ink_and_alpha(ladder, base_a, bands, scrim_c, scrim_a, surface_rgb,
                        target=None):
    """先试设计厚度 + 原墨；不行就推墨；再不行才加厚面板。

    推到纯白/近黑还不够，说明不是字色的问题，而是这层玻璃太薄、壁纸太亮，
    只能把面板加厚 —— 加厚的同时也就把滑杆的行程留出来了。
    """
    target = target if target is not None else INK_MIN * MARGIN
    for ink in ladder:
        if worst_contrast(ink, bands, scrim_c, scrim_a, surface_rgb, base_a) >= target:
            return base_a, ink
    a = base_a
    while a < PANE_CAP:
        a = round(a + 0.02, 3)
        for ink in ladder:
            if worst_contrast(ink, bands, scrim_c, scrim_a, surface_rgb, a) >= target:
                return min(a, PANE_CAP), ink
    return PANE_CAP, ladder[-1]


def min_alpha(ink, bands, scrim_c, scrim_a, surface_rgb, target):
    """这层墨在什么厚度以上才达标；达不到就返回 None。"""
    a = 0.04
    while a <= 0.98:
        if worst_contrast(ink, bands, scrim_c, scrim_a, surface_rgb, a) >= target:
            return a
        a = round(a + 0.02, 3)
    return None


def dim_to(ink, surface_rgb, bands, scrim_c, scrim_a, pane_a, target, start):
    """次要文字：尽量调淡（向面板底色靠），但必须自己过门限。

    旧版固定混 0.30 / 0.52，等于按「实色面板」算好就发车；面板一变透明，
    修改时间那一列就直接没了。现在各自验，淡到刚好够读为止。
    """
    w = start
    while w > 0 and worst_contrast(_mix(ink, surface_rgb, w), bands,
                                   scrim_c, scrim_a, surface_rgb, pane_a) < target:
        w = round(w - 0.04, 2)
    return max(0.0, w)


# ---------------- 推导 ----------------
def derive(t):
    tk = t["tokens"]
    bg, surface = tk["--tm-bg"], tk["--tm-surface"]
    text = tk["--tm-text"]
    accent = tk["--tm-accent"]
    strong = tk["--tm-accent-strong"]
    secondary = t["colors"]["secondary"]["hex"]
    dark_ui = tk["--tm-scheme"] == "light-text"
    surface_rgb = rgb(surface)

    if dark_ui:
        panel, panel2, panel3 = surface, mix(surface, "#FFFFFF", 0.055), mix(surface, "#FFFFFF", 0.10)
        line, line2 = mix(surface, "#FFFFFF", 0.10), mix(surface, "#FFFFFF", 0.20)
        acc, acc_d = strong, shade(strong, 0.10)
        acc_soft, sel, hover = mix(surface, accent, 0.20), mix(surface, accent, 0.32), mix(surface, accent, 0.10)
        danger, ok, warn = "#E8837C", "#6FC79E", "#E0B261"
        sh, shs = "rgba(0,0,0,.55)", "rgba(0,0,0,.40)"
        scrim_c, scrim_a = (0.0, 0.0, 0.0), 0.07
        # 深色主题的文字是浅色，底色越暗字越清楚 —— 所以不要压暗，反而要把图提亮，
        # 否则夜景/星空本来就暗，再叠蒙层就成「一锅黑」（用户原话：背景太昏）。
        k = lift_k(t["key"], True)
        lift = "brightness(%.2f) saturate(1.08) contrast(1.03)" % k
    else:
        panel = surface
        panel2, panel3 = mix(surface, bg, 0.55), mix(surface, bg, 0.95)
        line, line2 = mix(surface, text, 0.13), mix(surface, text, 0.24)
        # 强调色要同时「够显眼」与「当文字能读」：若 accent-strong 太接近灰
        # （青花那种淡彩），改用色板里的 secondary —— 那是这张壁纸的墨色。
        pick = strong
        if chroma(secondary) > chroma(strong) * 1.6 and contrast(secondary, surface) >= 4.5:
            pick = secondary
        acc, acc_d = pick, shade(pick, -0.14)
        acc_soft, sel, hover = mix(surface, accent, 0.16), mix(surface, accent, 0.30), mix(surface, accent, 0.07)
        danger, ok, warn = "#C4574C", "#3E8F6E", "#B4832F"
        sh = "rgba(%d,%d,%d,.16)" % rgb(mix(text, "#000000", 0.5))
        shs = "rgba(%d,%d,%d,.12)" % rgb(mix(text, "#000000", 0.5))
        # 浅色主题要「整体变成浅色底」：原图反差很大（亮云压暗山），
        # 只提亮 10% 的话深色文字落在山影上会糊掉。蒙层压到四成，
        # 图的大形（山脊、天空渐变）仍在，但已经是浅色调，文字始终有底。
        scrim_c, scrim_a = surface_rgb, 0.39
        k = lift_k(t["key"], False)
        lift = "brightness(%.2f) saturate(1.03)" % k

    bands = wall_bands(t["key"], k, dark_ui)

    # ① 正文：墨色 + 面板厚度一起解（默认厚度要「舒服」，不只是「勉强能读」）
    ladder = ink_ladder(text, dark_ui)
    pane_a, ink = solve_ink_and_alpha(
        ladder, PANE_A[dark_ui], bands, scrim_c, scrim_a, surface_rgb, COMFORT_TARGET)

    # ② 顶栏 / 侧栏 / 状态栏：同一层墨，但它们更薄，得单独算够不够
    chrome_a = CHROME_A[dark_ui]
    need = min_alpha(ink, bands, scrim_c, scrim_a, surface_rgb, COMFORT_TARGET)
    if need and chrome_a < need:
        chrome_a = min(round(need, 2), pane_a)   # 不做得比内容区还厚
    # 封顶后仍不达标就继续抬到与内容区同厚 —— 侧栏那一片在截图里是最花的
    while chrome_a < pane_a and worst_contrast(
            ink, bands, scrim_c, scrim_a, surface_rgb, chrome_a) < INK_MIN:
        chrome_a = round(chrome_a + 0.02, 2)
    chrome_a = min(chrome_a, pane_a)

    # ③ 可读下限：滑杆最低点对应的厚度。低于它，这层墨怎么调都读不出来，
    #    所以直接把滑杆下限顶住 —— 面板再透也不透到这个程度。
    floor_a = min_alpha(ink, bands, scrim_c, scrim_a, surface_rgb, FLOOR_TARGET) or pane_a
    floor_k = min(1.0, max(0.0, floor_a / max(pane_a, 1e-6)))
    floor_k = math.ceil(floor_k * 20) / 20          # 对齐 5% 步进，宁高勿低
    floor_k = min(floor_k, 1.0)

    # ④ 次要 / 提示文字：各自淡到刚好够读
    w2 = dim_to(ink, surface_rgb, bands, scrim_c, scrim_a, pane_a, INK2_MIN, 0.30)
    w3 = dim_to(ink, surface_rgb, bands, scrim_c, scrim_a, pane_a, INK3_MIN, 0.52)
    tx, tx2, tx3 = hexc(ink), hexc(_mix(ink, surface_rgb, w2)), hexc(_mix(ink, surface_rgb, w3))

    # ⑤ 文字光晕：滑到最薄时给一圈反差色，压住壁纸上的高光碎块
    m = worst_contrast(ink, bands, scrim_c, scrim_a, surface_rgb,
                       max(0.04, pane_a * floor_k))
    halo_a = 0.0 if m >= 6.0 else min(0.5, max(0.0, (6.0 - m) * 0.16))
    if halo_a <= 0.01:
        halo = "none"
    else:
        halo = "0 1px 2px " + (rgba("#000000", halo_a) if dark_ui
                               else rgba("#FFFFFF", halo_a))

    # 强调色当填充时，用哪个颜色写字更清楚
    acc_ink = "#FFFFFF" if contrast(accent, "#FFFFFF") >= contrast(accent, "#141414") else "#141414"

    return {
        "dark": dark_ui, "panel": panel, "panel2": panel2, "panel3": panel3,
        "line": line, "line2": line2, "tx": tx, "tx2": tx2, "tx3": tx3,
        "acc": acc, "acc_d": acc_d, "acc_soft": acc_soft, "sel": sel, "hover": hover,
        "danger": danger, "ok": ok, "warn": warn, "shadow": sh, "shadow_s": shs,
        # 工作面：底色拆成 rgb + 基准 alpha，运行时 alpha 再乘 --plate-k（滑杆）。
        # 变量名不能叫 --pane-a / --pane-b —— 那是 app.css 里窗格宽度的分配比例。
        # rgb 用空格分隔：只有 rgb(R G B / calc(...)) 这种现代写法才认 calc 透明度，
        # 老式 rgba(r,g,b,calc(...)) 会被判为非法值 → 整条声明作废 → 面板全透明。
        "plate_rgb": "%d %d %d" % surface_rgb, "plate_a": round(pane_a, 2),
        "plate_top_a": round(chrome_a, 2), "floor_pct": int(round(floor_k * 100)),
        "accent": accent, "accent_strong": strong,
        "acc_ink": acc_ink, "acc_fill_d": shade(accent, 0.12 if dark_ui else -0.12),
        "halo": halo, "ink_worst": round(worst_contrast(
            ink, bands, scrim_c, scrim_a, surface_rgb, pane_a), 2),
        "_k": k, "_scrim_c": scrim_c, "_scrim_a": scrim_a,
        "scrim": _scrim_css(scrim_c, scrim_a, dark_ui),
        "lift": lift, "bg": bg, "surface": surface,
        "brand": "linear-gradient(135deg,%s,%s)" % (accent, strong),
        "wall": t["wallpaper"]["local"],
        # 界面背景用「去文字 + 预模糊」版，避免壁纸上烧死的宣传大字透到界面里
        "bgimg": "skins/bg-%s.webp" % t["key"],
    }


def _scrim_css(scrim_c, scrim_a, dark_ui):
    if dark_ui:
        return ("linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,.04) 55%, "
                "rgba(0,0,0,.14) 100%)")
    s = hexc(scrim_c)
    return ("linear-gradient(180deg, %s 0%%, %s 50%%, %s 100%%)"
            % (rgba(s, 0.36), rgba(s, 0.38), rgba(s, 0.42)))


def block(t, d):
    k = t["key"]
    wall = 'url("%s") center/cover no-repeat' % d["bgimg"]
    wall_img = 'url("%s")' % d["bgimg"]
    return "\n".join([
        '/* %s %s · %s · 平均亮度 %s · %s */' % (
            t["id"], t["name"], t["category"], t["meanLuminance"],
            "浅字深底" if d["dark"] else "深字浅底"),
        'html[data-skin="%s"]{' % k,
        "  --bg:%s; --panel:%s; --panel2:%s; --panel3:%s;" % (d["bg"], d["panel"], d["panel2"], d["panel3"]),
        "  --line:%s; --line2:%s;" % (d["line"], d["line2"]),
        "  /* 字色：由色板文字色按真实合成底色逐级推远得到，换主题即换墨 */",
        "  --tx:%s; --tx2:%s; --tx3:%s;" % (d["tx"], d["tx2"], d["tx3"]),
        "  --tx-halo:%s;" % d["halo"],
        "  --acc:%s; --acc-d:%s; --acc-fill:%s; --acc-fill-d:%s; --acc-ink:%s;" % (
            d["acc"], d["acc_d"], d["accent"], d["acc_fill_d"], d["acc_ink"]),
        "  --acc-soft:%s; --sel:%s; --hover:%s;" % (d["acc_soft"], d["sel"], d["hover"]),
        "  --danger:%s; --ok:%s; --warn:%s;" % (d["danger"], d["ok"], d["warn"]),
        "  --shadow:0 18px 48px %s; --shadow-s:0 4px 16px %s;" % (d["shadow"], d["shadow_s"]),
        "  --plate-rgb:%s; --plate-a:%s; --plate-top-a:%s;" % (
            d["plate_rgb"], d["plate_a"], d["plate_top_a"]),
        "  /* 工作面透明度：--plate-k 由皮肤面板滑杆实时写入（1 = 本套主题的默认厚度，0 = 全透）*/",
        "  /* 滑杆下限：再薄下去这层墨就压不住壁纸了，界面按 --plate-min 卡住 */",
        "  --plate-min:%d%%;" % d["floor_pct"],
        "  --chrome:rgb(var(--plate-rgb) / calc(var(--plate-top-a) * var(--plate-k,1)));",
        "  --pane-bg:rgb(var(--plate-rgb) / calc(var(--plate-a) * var(--plate-k,1)));",
        "  --brand-grad:%s;" % d["brand"],
        "  --app-bg:%s, %s;" % (d["scrim"], wall),
        "  /* 壁纸层：原图直出，不随滑杆变淡；调淡的是上面的工作面 */",
        "  --wall-img:%s; --wall-lift:%s;" % (wall_img, d["lift"]),
        "  --wall-scrim:%s;" % d["scrim"],
        "}",
        'html[data-skin="%s"][data-wallpaper="0"]{' % k,
        "  --app-bg:linear-gradient(180deg,%s 0%%,%s 100%%);" % (d["bg"], d["panel2"]),
        "  --wall-img:none;",
        "  --wall-scrim:linear-gradient(180deg,%s 0%%,%s 100%%);" % (d["bg"], d["panel2"]),
        "  /* 没有壁纸时底面就是实色，字色回到实色校验用的墨 */",
        "  --tx-halo:none;",
        "}",
    ])


# 分类气质：只加一两处极轻的装饰，避免过度设计
FLOURISH = {
    "mose": 'html[data-skin="mose"] .brand-mark{border-radius:3px}',
    "zhuying": 'html[data-skin="zhuying"] .brand-mark{border-radius:3px}',
    "qinghua": 'html[data-skin="qinghua"] .brand-mark{border-radius:3px}',
    "hongri": 'html[data-skin="hongri"] .topbar{box-shadow:inset 0 -1px 0 %s}',
    "chicheng": 'html[data-skin="chicheng"] .topbar{box-shadow:inset 0 -1px 0 %s}',
}


def js_entry(t, d):
    return (
        '  {key: "%s", name: "%s", cat: "%s", slogan: "%s", acc: "%s", sur: "%s",\n'
        '   wall: "%s", scheme: "%s", pf: %d, prev: "linear-gradient(160deg, %s, %s)"},'
        % (t["key"], t["name"], t["category"], t["slogan"], d["accent"], d["surface"],
           d["wall"], "dark" if d["dark"] else "light", d["floor_pct"], d["surface"], d["bg"])
    )


HOOKS = """

/* ---------- 通用钩子：壁纸与玻璃 ---------- */
body{background:var(--app-bg,var(--bg))}
/* 壁纸独立成层（body::before / ::after）：
   主题图保持原样（opacity 恒为 1），不再随滑杆变淡 —— 变淡的是它上面的
   工作面（.pane / 顶栏 / 侧栏）。之前把滑杆做在壁纸层上，面板仍旧 48% 厚，
   于是「调了也没用，还是看不到图」。 */
html[data-skin]:not([data-skin="default"]){background:var(--bg)}
html[data-skin]:not([data-skin="default"]) body{background:transparent}
html[data-skin]:not([data-skin="default"]) body::before{
  content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:var(--wall-img,none) center/cover no-repeat;
  filter:var(--wall-lift,none)}
html[data-skin]:not([data-skin="default"]) body::after{
  content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:var(--wall-scrim,none)}
/* 文字光晕：壁纸是照片，字底下既有亮丝也有暗影，一层反差色描边让笔画
   在任何一块高光上都立得住。深色主题给暗影，浅色主题给亮边，alpha 由
   生成器按最薄处的余量算，够安全时就是 transparent。 */
body{text-shadow:var(--tx-halo,none)}
.pane{background:var(--pane-bg,var(--panel))}
.topbar,.sidebar,.statusbar{background:var(--chrome,var(--panel))}
html[data-skin]:not([data-skin="default"]) .topbar,
html[data-skin]:not([data-skin="default"]) .sidebar,
html[data-skin]:not([data-skin="default"]) .statusbar{
  backdrop-filter:blur(calc(var(--glass-blur,10) * 1px)) saturate(1.06);
  -webkit-backdrop-filter:blur(calc(var(--glass-blur,10) * 1px)) saturate(1.06)}
/* 内容窗格也是磨砂玻璃：壁纸的色温透进来，列表仍在同一块底上，不抢文字。
   模糊半径跟着面板厚度一起减：面板越薄越要看得清图，一直 10px 会把风景
   糊成一块纯色（「调了透明度还是看不到主题图」的另一半原因）。 */
html[data-skin]:not([data-skin="default"]) .pane{
  backdrop-filter:blur(calc(var(--glass-blur,10) * 1px)) saturate(1.02);
  -webkit-backdrop-filter:blur(calc(var(--glass-blur,10) * 1px)) saturate(1.02)}
/* 列表本身不再刷一层实色，否则玻璃全被盖住；底色由 .pane 那层半透明面板负责 */
html[data-skin]:not([data-skin="default"]) .lbody{background:transparent}
/* 关键：.panes 原本铺满整个内容区当「窗格缝隙底色」（--line 实色），
   它在 body 壁纸之上、.pane 之下，等于把内容区整块挡住了 —— 只有侧栏
   在 .panes 之外，所以之前只有侧栏能看见图。皮肤模式下让缝隙透气，
   整张壁纸才能从窗口这头连到那头。 */
html[data-skin]:not([data-skin="default"]) .panes{background:transparent}
/* 标签条与列表头也属于「同一块面板」，实色会把面板上的玻璃从中间截断 */
html[data-skin]:not([data-skin="default"]) .tabs,
html[data-skin]:not([data-skin="default"]) .lhead{background:transparent}
"""


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    derived = [(t, derive(t)) for t in data["themes"]]

    bad = []
    print("%-9s %-4s %-6s %-6s %-6s %-6s %-6s %-6s" % (
        "主题", "方案", "正文", "次要", "提示", "面板", "顶栏", "下限"))
    for t, d in derived:
        # 用生成时的同一套底色重新验，确保写出去的值真的达标
        tk = t["tokens"]
        dark_ui = tk["--tm-scheme"] == "light-text"
        surf = rgb(tk["--tm-surface"])
        scrim_c, scrim_a = d["_scrim_c"], d["_scrim_a"]
        bands = wall_bands(t["key"], d["_k"], dark_ui)
        c1 = worst_contrast(rgb(d["tx"]), bands, scrim_c, scrim_a, surf, d["plate_a"])
        c2 = worst_contrast(rgb(d["tx2"]), bands, scrim_c, scrim_a, surf, d["plate_a"])
        c3 = worst_contrast(rgb(d["tx3"]), bands, scrim_c, scrim_a, surf, d["plate_a"])
        cc = worst_contrast(rgb(d["tx"]), bands, scrim_c, scrim_a, surf, d["plate_top_a"])
        print("%-9s %-4s %-6.2f %-6.2f %-6.2f %-6.2f %-6.2f %-5d%%" % (
            t["key"], "深底" if dark_ui else "浅底", c1, c2, c3,
            d["plate_a"], d["plate_top_a"], d["floor_pct"]))
        if c1 < INK_MIN:
            bad.append("%s 正文 %.2f<%.1f" % (t["key"], c1, INK_MIN))
        if c2 < INK2_MIN - 0.01:
            bad.append("%s 次要 %.2f<%.1f" % (t["key"], c2, INK2_MIN))
        if c3 < INK3_MIN - 0.01:
            bad.append("%s 提示 %.2f<%.1f" % (t["key"], c3, INK3_MIN))
        if cc < INK_MIN:
            bad.append("%s 顶栏 %.2f<%.1f" % (t["key"], cc, INK_MIN))

    if "--check" in sys.argv:
        print("对比度问题：", bad or "无")
        return 0 if not bad else 1

    head = """/* 文件管理多面手 — 主题皮肤（自动生成，请勿手改）
 * 由 src/tools/gen_skins.py 读取 tools/skins.json 生成。
 * 变量来源：每套主题的 bg / surface / text / accent 四个令牌，其余层次色
 * 由混色推导。校验对象是「壁纸 → 蒙层 → 半透明面板」合成后的真实底色，
 * 取最暗 2% / 中位 / 最亮 2% 三个带，正文都要过 WCAG AA 4.5:1。
 * 字色由色板文字色按这条路逐级推远得到，换主题即换墨。
 */
"""
    body = "\n\n".join(block(t, d) for t, d in derived)
    fl = []
    for t, d in derived:
        f = FLOURISH.get(t["key"])
        if f:
            fl.append(f % d["accent"] if "%s" in f else f)
    css = head + "\n" + body + HOOKS + "\n".join(fl) + "\n"
    open(OUT_CSS, "w", encoding="utf-8").write(css)
    print("写入", os.path.relpath(OUT_CSS, ROOT), len(css), "字节")

    js = """// 主题皮肤清单（自动生成，请勿手改；见 src/tools/gen_skins.py）
// prev 为壁纸缺失时的兜底渐变；wall 为皮肤缩略图，sur 为该主题的面板底色，
// pf 为可读下限（滑杆最低百分比）——再薄下去文字就压不住壁纸了。
export const SKINS = [
  {key: 'default', name: '晨雾蓝', cat: '默认', slogan: '出厂外观', acc: '#4a7fd0',
   wall: '', scheme: '', pf: 0, prev: 'linear-gradient(165deg,#f7f9fd,#e8eff9 60%,#dfe9f6)'},
""" + "\n".join(js_entry(t, d) for t, d in derived) + """
];
export const SKIN_KEYS = SKINS.map(s => s.key);
export const skinOf = k => SKINS.find(s => s.key === k) || SKINS[0];
"""
    open(OUT_JS, "w", encoding="utf-8").write(js)
    print("写入", os.path.relpath(OUT_JS, ROOT), len(js), "字节")
    print("对比度问题：", bad or "无")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
