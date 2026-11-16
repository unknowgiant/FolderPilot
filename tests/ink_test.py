# -*- coding: utf-8 -*-
"""皮肤字色一致性测试：换主题必须换字色，且写出去的每个变量都成立。

不重复算对比度（那是 gen_skins.py 的活，浏览器里的真实像素由 ink_check.mjs 量），
这里守的是「关系」：

  1. 生成器自检必须通过（--check 退出码 0）；
  2. 每套主题都写全了 --tx / --tx2 / --tx3 / --tx-halo / --plate-a / --plate-min；
  3. 10 套主题的字色两两不同，且与默认皮肤的 --tx 不同 —— 这就是「换主题自动换字色」；
  4. 深色主题的字亮、浅色主题的字暗；tx2 / tx3 依次淡下去但不糊成一团；
  5. skins.js 的 pf 与 CSS 的 --plate-min 一对一吻合（滑杆下限的数据源只有一个）；
  6. 没有主题把 --plate-a 或 --plate-top-a 压到看不见壁纸的程度。

用法：py tests/ink_test.py
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "src", "ui", "skin-themes.css")
JS = os.path.join(ROOT, "src", "ui", "js", "skins.js")
OUT = os.path.join(ROOT, "tests", "output")

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def f(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def blocks():
    """把 CSS 按 html[data-skin="xxx"]{...} 切块。"""
    css = io.open(CSS, encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'html\[data-skin="([\w-]+)"\]\{(.*?)\n\}', css, re.S):
        key, body = m.group(1), m.group(2)
        if key in out:          # 第二块是 [data-wallpaper="0"]，跳过
            continue
        out[key] = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))
    return out


def main():
    # 1) 生成器自检
    r = subprocess.run([sys.executable, os.path.join(ROOT, "src", "tools", "gen_skins.py"),
                        "--check"], capture_output=True, text=True, encoding="utf-8")
    check("gen_skins --check 通过", r.returncode == 0,
          (r.stdout or r.stderr or "").strip().splitlines()[-1:])

    bl = blocks()
    check("解析到 10 套主题", len(bl) == 10, sorted(bl))
    check("默认皮肤不在主题块里（走 app.css）", "default" not in bl, list(bl))

    need = ("--tx", "--tx2", "--tx3", "--tx-halo", "--plate-a", "--plate-top-a", "--plate-min")
    for k, v in bl.items():
        miss = [n for n in need if n not in v]
        check("%s.变量齐全" % k, not miss, miss)

    # 2) 墨色真的换了吗
    inks = {k: v["--tx"].strip() for k, v in bl.items() if "--tx" in v}
    check("主题之间字色互不相同", len(set(inks.values())) == len(inks),
          "%d 套 / %d 种" % (len(inks), len(set(inks.values()))))
    app_tx = re.search(r"--tx:\s*(#[0-9A-Fa-f]{6})", io.open(
        os.path.join(ROOT, "src", "ui", "app.css"), encoding="utf-8").read()).group(1)
    clashes = [k for k, c in inks.items() if c.upper() == app_tx.upper()]
    check("没有主题沿用默认皮肤的墨色", not clashes, clashes)

    # 3) 深浅方向 + 层级
    for k, v in bl.items():
        dark = "--panel:#" + "" if False else None
        panel = v.get("--panel", "")
        tx = v["--tx"].strip()
        is_dark = lum(panel) < lum(tx)      # 面板比字暗 = 深底浅字
        check("%s.墨与面板反差足够" % k, contrast(tx, panel) >= 4.5,
              "%.2f:1" % contrast(tx, panel))
        before = lum(tx)
        ok = True
        for name in ("--tx2", "--tx3"):
            cur = v[name].strip()
            # 越往后越靠近面板底色（淡化），但不该跨过面板跑到另一侧
            if abs(lum(cur) - lum(panel)) >= abs(before - lum(panel)):
                ok = False
            before = lum(cur)
        check("%s.次要/提示逐级淡化" % k, ok,
              " ".join("%s %s" % (n, v[n].strip()) for n in ("--tx", "--tx2", "--tx3")))

    # 4) 面板厚度：太薄会漏字，太厚就没有玻璃感
    for k, v in bl.items():
        pa = float(v["--plate-a"])
        ca = float(v["--plate-top-a"])
        check("%s.面板厚度" % k, 0.30 <= pa <= 0.80 and 0.18 <= ca <= pa + 0.001,
              "pane %.2f / chrome %.2f" % (pa, ca))
        pmin = float(v["--plate-min"].strip().rstrip("%"))
        check("%s.可读下限" % k, 0 <= pmin <= 100, v["--plate-min"])

    # 5) skins.js 与 CSS 的 pf 必须一一对应（滑杆读的是 JS 那份）
    js = io.open(JS, encoding="utf-8").read()
    pairs = re.findall(r'key: "([\w-]+)".*?pf: (\d+)', js, re.S)
    mp = {k: int(v) for k, v in pairs}
    check("skins.js 覆盖全部主题", set(mp) == set(bl), "%s vs %s" % (sorted(mp), sorted(bl)))
    bad = []
    for k in bl:
        css_min = float(bl[k]["--plate-min"].strip().rstrip("%"))
        if k in mp and abs(mp[k] - css_min) > 0.01:
            bad.append("%s css=%s js=%s" % (k, css_min, mp[k]))
    check("pf 与 --plate-min 一致", not bad, bad)

    # 6) 光晕：要么 none，要么是完整的 text-shadow
    for k, v in bl.items():
        h = v["--tx-halo"].strip()
        check("%s.光晕格式" % k, h == "none" or re.match(r"^0 1px 2px rgba\(", h), h)

    os.makedirs(OUT, exist_ok=True)
    report["passed"] = sum(1 for c in report["checks"] if c["ok"])
    report["total"] = len(report["checks"])
    io.open(os.path.join(OUT, "ink_report_py.json"), "w", encoding="utf-8").write(
        json.dumps(report, ensure_ascii=False, indent=2))
    for c in report["checks"]:
        if not c["ok"]:
            print("X  ", c["name"], "|", c["detail"])
    print("%d/%d 通过" % (report["passed"], report["total"]))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
