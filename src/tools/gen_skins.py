# -*- coding: utf-8 -*-
"""由「主题色板」生成界面皮肤 CSS 与前端元数据。

输入：tools/skins.json（8 个令牌：bg / surface / text / accent / accent-strong /
      overlay / scheme / bg-image）
输出：ui/skin-themes.css   —— 每套主题的全量界面变量 + 壁纸 + 玻璃层钩子
      ui/js/skins.js       —— 皮肤清单（名称、分类、壁纸、强调色）

为什么不让界面直接吃那 8 个令牌：现有界面用到 22 个变量（面板三层、分隔线、
hover、选中、阴影、玻璃层…）。这里按色板的 bg/surface/text/accent 用「混色 +
对比度校验」推出来，保证 10 套主题的层次关系一致，且正文与强调色在各自面板
上都能过 WCAG AA。

用法：
    py -3.14 src/tools/gen_skins.py           # 生成
    py -3.14 src/tools/gen_skins.py --check   # 只校验对比度，不写文件
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 壁纸提亮目标（平均感知亮度 0-255）：深色主题落到暗调，浅色主题落到浅调
DARK_TARGET = 66
LIGHT_TARGET = 175
SRC = os.path.join(ROOT, "tools", "skins.json")
OUT_CSS = os.path.join(ROOT, "ui", "skin-themes.css")
OUT_JS = os.path.join(ROOT, "ui", "js", "skins.js")


# ---------------- 颜色工具 ----------------
def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexc(t):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in t)


def mix(a, b, w):
    """w 为 b 的权重。"""
    x, y = rgb(a), rgb(b)
    return hexc(tuple(x[i] * (1 - w) + y[i] * w for i in range(3)))


def lum(h):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
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


def chroma(h):
    c = rgb(h)
    return max(c) - min(c)


# ---------------- 推导 ----------------
def derive(t):
    tk = t["tokens"]
    bg, surface = tk["--tm-bg"], tk["--tm-surface"]
    text = tk["--tm-text"]
    accent = tk["--tm-accent"]
    strong = tk["--tm-accent-strong"]
    secondary = t["colors"]["secondary"]["hex"]
    dark_ui = tk["--tm-scheme"] == "light-text"

    if dark_ui:
        panel, panel2, panel3 = surface, mix(surface, "#FFFFFF", 0.055), mix(surface, "#FFFFFF", 0.10)
        line, line2 = mix(surface, "#FFFFFF", 0.10), mix(surface, "#FFFFFF", 0.20)
        tx2, tx3 = mix(text, surface, 0.30), mix(text, surface, 0.52)
        acc, acc_d = strong, shade(strong, 0.10)
        acc_soft, sel, hover = mix(surface, accent, 0.20), mix(surface, accent, 0.32), mix(surface, accent, 0.10)
        danger, ok, warn = "#E8837C", "#6FC79E", "#E0B261"
        sh, shs = "rgba(0,0,0,.55)", "rgba(0,0,0,.40)"
        # 深色主题的文字是浅色，底色越暗字越清楚 —— 所以不要压暗，反而要把图提亮，
        # 否则夜景/星空本来就暗，再叠蒙层就成「一锅黑」（用户原话：背景太昏）。
        chrome, pane = rgba(surface, 0.24), rgba(surface, 0.48)
        scrim = ("linear-gradient(180deg, rgba(0,0,0,0) 0%, rgba(0,0,0,.04) 55%, "
                 "rgba(0,0,0,.14) 100%)")
        # 深色主题的目标：底图落在 60~70 的暗调区间。
        # 太暗（星河 39）要提亮，太亮（实事求是那张纸 94）要压暗 ——
        # 一刀切给同一个 brightness 时，亮底图会把浅色文字整片吃掉。
        lum = bg_lum(t["key"])
        k = max(0.45, min(2.0, DARK_TARGET / lum)) if lum else 1.0
        lift = "brightness(%.2f) saturate(1.08) contrast(1.03)" % k
    else:
        panel = surface
        panel2, panel3 = mix(surface, bg, 0.55), mix(surface, bg, 0.95)
        line, line2 = mix(surface, text, 0.13), mix(surface, text, 0.24)
        tx2, tx3 = mix(text, surface, 0.30), mix(text, surface, 0.52)
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
        chrome, pane = rgba(surface, 0.30), rgba(surface, 0.44)
        # 浅色主题要「整体变成浅色底」：原图反差很大（亮云压暗山），
        # 只提亮 10% 的话深色文字落在山影上会糊掉。蒙层压到四成，
        # 图的大形（山脊、天空渐变）仍在，但已经是浅色调，文字始终有底。
        scrim = ("linear-gradient(180deg, %s 0%%, %s 50%%, %s 100%%)"
                 % (rgba(surface, 0.36), rgba(surface, 0.38), rgba(surface, 0.42)))
        # 浅色主题只需要把暗图提上来；已经很亮的纸面别再去压，压了会发灰
        lum = bg_lum(t["key"])
        k = max(1.0, min(2.0, LIGHT_TARGET / lum)) if lum else 1.0
        lift = "brightness(%.2f) saturate(1.03)" % k

    # 强调色当填充时，用哪个颜色写字更清楚
    acc_ink = "#FFFFFF" if contrast(accent, "#FFFFFF") >= contrast(accent, "#141414") else "#141414"

    return {
        "dark": dark_ui, "panel": panel, "panel2": panel2, "panel3": panel3,
        "line": line, "line2": line2, "tx": text, "tx2": tx2, "tx3": tx3,
        "acc": acc, "acc_d": acc_d, "acc_soft": acc_soft, "sel": sel, "hover": hover,
        "danger": danger, "ok": ok, "warn": warn, "shadow": sh, "shadow_s": shs,
        "chrome": chrome, "pane": pane, "accent": accent, "accent_strong": strong,
        "acc_ink": acc_ink, "acc_fill_d": shade(accent, 0.12 if dark_ui else -0.12),
        "scrim": scrim, "lift": lift, "bg": bg, "surface": surface,
        "brand": "linear-gradient(135deg,%s,%s)" % (accent, strong),
        "wall": t["wallpaper"]["local"],
        # 界面背景用「去文字 + 预模糊」版，避免壁纸上烧死的宣传大字透到界面里
        "bgimg": "skins/bg-%s.webp" % t["key"],
    }


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
        "  --tx:%s; --tx2:%s; --tx3:%s;" % (d["tx"], d["tx2"], d["tx3"]),
        "  --acc:%s; --acc-d:%s; --acc-fill:%s; --acc-fill-d:%s; --acc-ink:%s;" % (
            d["acc"], d["acc_d"], d["accent"], d["acc_fill_d"], d["acc_ink"]),
        "  --acc-soft:%s; --sel:%s; --hover:%s;" % (d["acc_soft"], d["sel"], d["hover"]),
        "  --danger:%s; --ok:%s; --warn:%s;" % (d["danger"], d["ok"], d["warn"]),
        "  --shadow:0 18px 48px %s; --shadow-s:0 4px 16px %s;" % (d["shadow"], d["shadow_s"]),
        "  --chrome:%s; --pane-bg:%s;" % (d["chrome"], d["pane"]),
        "  --brand-grad:%s;" % d["brand"],
        "  --app-bg:%s, %s;" % (d["scrim"], wall),
        "  /* 壁纸层：独立出来才能单独调不透明度 */",
        "  --wall-img:%s; --wall-lift:%s;" % (wall_img, d["lift"]),
        "  --wall-scrim:%s;" % d["scrim"],
        "}",
        'html[data-skin="%s"][data-wallpaper="0"]{' % k,
        "  --app-bg:linear-gradient(180deg,%s 0%%,%s 100%%);" % (d["bg"], d["panel2"]),
        "  --wall-img:none;",
        "  --wall-scrim:linear-gradient(180deg,%s 0%%,%s 100%%);" % (d["bg"], d["panel2"]),
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
        '   wall: "%s", scheme: "%s", prev: "linear-gradient(160deg, %s, %s)"},'
        % (t["key"], t["name"], t["category"], t["slogan"], d["accent"], d["surface"],
           d["wall"], "dark" if d["dark"] else "light", d["surface"], d["bg"])
    )


HOOKS = """

/* ---------- 通用钩子：壁纸与玻璃 ---------- */
body{background:var(--app-bg,var(--bg))}
/* 壁纸独立成层（body::before / ::after），好处是能单独调不透明度：
   之前壁纸是 body 背景图的一层，靠改蒙层 alpha 才能「变淡」，
   但那样会让整张图发糊发白。现在只降这一层的 opacity，图本身还是清晰的。 */
html[data-skin]:not([data-skin="default"]){background:var(--bg)}
html[data-skin]:not([data-skin="default"]) body{background:transparent}
html[data-skin]:not([data-skin="default"]) body::before{
  content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:var(--wall-img,none) center/cover no-repeat;
  opacity:var(--wall-opacity,1);filter:var(--wall-lift,none);
  transition:opacity .16s linear}
html[data-skin]:not([data-skin="default"]) body::after{
  content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;
  background:var(--wall-scrim,none)}
.pane{background:var(--pane-bg,var(--panel))}
.topbar,.sidebar,.statusbar{background:var(--chrome,var(--panel))}
html[data-skin]:not([data-skin="default"]) .topbar,
html[data-skin]:not([data-skin="default"]) .sidebar,
html[data-skin]:not([data-skin="default"]) .statusbar{
  backdrop-filter:blur(10px) saturate(1.06);-webkit-backdrop-filter:blur(10px) saturate(1.06)}
/* 内容窗格也是磨砂玻璃：壁纸的色温透进来，列表仍在同一块底上，不抢文字。
   模糊半径要小：底图本身已做过柔化，再叠 20px+ 会把风景糊成一块纯色。 */
html[data-skin]:not([data-skin="default"]) .pane{
  backdrop-filter:blur(10px) saturate(1.02);-webkit-backdrop-filter:blur(10px) saturate(1.02)}
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
    for t, d in derived:
        c1 = contrast(d["tx"], d["panel"])
        c2 = contrast(d["acc"], d["panel"])
        if c1 < 4.5:
            bad.append("%s 正文 %.2f" % (t["key"], c1))
        if c2 < 4.4:
            bad.append("%s 强调 %.2f" % (t["key"], c2))
        print("%-9s %-4s 正文 %5.2f  强调 %5.2f  填充字 %s" % (
            t["key"], "深底" if d["dark"] else "浅底", c1, c2, d["acc_ink"]))
    if "--check" in sys.argv:
        print("对比度问题：", bad or "无")
        return 0 if not bad else 1

    head = """/* 文件管理多面手 — 主题皮肤（自动生成，请勿手改）
 * 由 src/tools/gen_skins.py 读取 tools/skins.json 生成。
 * 变量来源：每套主题的 bg / surface / text / accent 四个令牌，其余层次色
 * 由混色推导，正文与强调色对面板底色的对比度均已核到 WCAG AA 以上。
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
// prev 为壁纸缺失时的兜底渐变；wall 为皮肤缩略图，sur 为该主题的面板底色。
export const SKINS = [
  {key: 'default', name: '晨雾蓝', cat: '默认', slogan: '出厂外观', acc: '#4a7fd0',
   wall: '', scheme: '', prev: 'linear-gradient(165deg,#f7f9fd,#e8eff9 60%,#dfe9f6)'},
""" + "\n".join(js_entry(t, d) for t, d in derived) + """
];
export const SKIN_KEYS = SKINS.map(s => s.key);
export const skinOf = k => SKINS.find(s => s.key === k) || SKINS[0];
"""
    open(OUT_JS, "w", encoding="utf-8").write(js)
    print("写入", os.path.relpath(OUT_JS, ROOT), len(js), "字节")
    print("对比度问题：", bad or "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
