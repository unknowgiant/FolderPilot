# -*- coding: utf-8 -*-
"""安装向导界面专项：版本对比是否摆得下、文案是否成对出现。

不依赖打包产物：直接实例化 setup_app.Wizard，让它排一次版，然后
  · 递归收集所有 Label 文本，断言「即将安装 / 系统已有 / 版本号 / 结论」都在
  · 量每个控件相对窗口的位置，断言没有溢出窗口（底部不许超出）
  · 截一张图存 tests/output/setup_wizard.png，人眼复核配色与对比度

用法：py tests/setup_ui_test.py
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import setup_app  # noqa: E402
from fmp.version import APP_LABEL, APP_TITLE, APP_VERSION  # noqa: E402

OUT = os.path.join(ROOT, "tests", "output")
report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def collect(widget, out):
    try:
        txt = widget.cget("text")
        if isinstance(txt, str) and txt.strip():
            out.append(txt.strip())
    except Exception:
        pass
    for child in widget.winfo_children():
        collect(child, out)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    w = setup_app.Wizard()
    root = w.root
    root.geometry("+160+60")
    root.deiconify()
    root.attributes("-topmost", True)
    root.update_idletasks()
    root.update()
    root.lift()
    root.focus_force()
    time.sleep(1.0)
    root.update()

    texts = collect(root, [])
    joined = " | ".join(texts)
    check("窗口标题为项目名 + 安装", root.title() == APP_TITLE + " 安装", root.title())
    check("窗口标题不含版本号", not any(c.isdigit() for c in root.title()), root.title())
    check("显示「即将安装」", "即将安装" in texts, texts[:8])
    check("显示「系统已有」", "系统已有" in texts, "")
    check("安装包版本号出现在界面上", ("v" + APP_VERSION) in joined, "")
    check("顶部标注安装包版本", ("安装包 v" + APP_VERSION) in joined, "")
    check("给出结论（升级/全新/重装/降级之一）",
          any(k in joined for k in ("升级安装", "全新安装", "同版本重装", "降级安装")), "")
    check("结论里带两端版本对比", "→" in joined or "覆盖" in joined, "")

    # 布局：所有控件都必须落在窗口内（安装向导固定尺寸，溢出会被裁掉）
    win_h = root.winfo_height()
    win_w = root.winfo_width()
    worst, worst_b = None, 0
    for child in root.winfo_children():
        stack = [child]
        while stack:
            c = stack.pop()
            stack.extend(c.winfo_children())
            if not c.winfo_ismapped():
                continue
            b = c.winfo_rooty() + c.winfo_height() - root.winfo_rooty()
            if b > worst_b:
                worst, worst_b = c, b
    check("界面内容没有超出窗口高度", worst_b <= win_h + 1,
          "最低控件底部 %d / 窗口高 %d" % (worst_b, win_h))
    check("窗口宽度足够（≥600）", win_w >= 600, win_w)
    check("窗口高度足够（≥560）", win_h >= 560, win_h)

    # 截图（仅供人眼复核）
    shot = os.path.join(OUT, "setup_wizard.png")
    try:
        u32 = ctypes.windll.user32
        u32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
        u32.GetAncestor.restype = wintypes.HWND
        u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_long * 4)]
        hwnd = u32.GetAncestor(root.winfo_id(), 2)   # GA_ROOT
        rect = (ctypes.c_long * 4)()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        l, t, r, b = rect
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(l + 1, t + 1, r - 1, b - 1)).save(shot)
        check("界面截图已保存", os.path.isfile(shot) and os.path.getsize(shot) > 8000,
              os.path.getsize(shot) if os.path.isfile(shot) else 0)
    except Exception as ex:            # noqa: BLE001
        check("界面截图已保存", False, "%s: %s" % (type(ex).__name__, ex))

    # 安装页 → 完成页也能正常排一次（不真的装，只换页）
    try:
        w.installed_exe = os.path.join(setup_app.DEFAULT_DIR, APP_TITLE + ".exe")
        w.page_done()
        root.update_idletasks()
        root.update()
        done_texts = collect(w.page, [])
        check("完成页显示完整版本号", APP_LABEL in " | ".join(done_texts), done_texts[:6])
        check("完成页说明本次变化",
              any(k in " | ".join(done_texts) for k in ("更新为", "首次安装")),
              done_texts[:8])
    except Exception as ex:            # noqa: BLE001
        check("完成页可正常渲染", False, "%s: %s" % (type(ex).__name__, ex))

    root.destroy()

    # 全新安装场景：本机查不到任何版本时，「系统已有」应显示破折号与「全新安装」
    real_latest = setup_app.installed.latest_installed
    setup_app.installed.latest_installed = lambda: None
    try:
        w2 = setup_app.Wizard()
        w2.root.update_idletasks()
        w2.root.update()
        t2 = collect(w2.root, [])
        j2 = " | ".join(t2)
        check("未安装时结论为「全新安装」", "全新安装" in j2, "")
        check("未安装时版本位显示破折号", "—" in t2, t2[-8:])
        check("未安装时说明本机没有已装版本", "没有检测到" in j2, "")
        w2.root.destroy()
    except Exception as ex:            # noqa: BLE001
        check("全新安装场景可正常渲染", False, "%s: %s" % (type(ex).__name__, ex))
    finally:
        setup_app.installed.latest_installed = real_latest

    report["passed"] = not report["errors"]
    with open(os.path.join(OUT, "setup_ui_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
