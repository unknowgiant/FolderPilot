# -*- coding: utf-8 -*-
"""鼠标侧键自测：钩子能装上，且 XBUTTON1/2 能被正确解析成后退 / 前进。

用法：py -3.14 tests/mouse_nav_test.py
产物：tests/output/mouse_nav_report.json

说明：Windows 在不少环境（远程会话、部分安全软件、驱动接管）会丢弃
合成出来的侧键事件，SendInput 打回去收不到，所以这里不依赖真实注入——
直接构造 MSLLHOOKSTRUCT 喂给钩子回调，验证「消息解析 → 方向 → 节流 → 吞消息」
这条我们自己写的链路。真实侧键另在窗口里人工点一次确认。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fmp.mouse_nav import (MSLLHOOKSTRUCT, WM_XBUTTONUP, MouseNav,  # noqa: E402
                           THROTTLE)

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def feed(nav, message, button=None):
    """构造一条低级鼠标消息喂给钩子回调，返回回调的返回值。"""
    st = MSLLHOOKSTRUCT()
    st.mouseData = (button << 16) if button else 0
    return nav._callback(0, message, ctypes.addressof(st))


def main():
    got = []
    lock = threading.Lock()

    def on_nav(delta):
        with lock:
            got.append(delta)

    stop = threading.Event()
    nav = MouseNav("", on_nav, stop).start()
    check("hook.installed", nav.installed, "SetWindowsHookEx 失败（可能被安全软件拦截）")

    # 后退键：解析成 -1，并且吞掉消息（返回 1，不让 WebView2 自己后退）
    ret = feed(nav, WM_XBUTTONUP, 1)
    time.sleep(0.25)
    check("xbutton1.back", got[:1] == [-1], got[:])
    check("xbutton1.swallowed", ret == 1, ret)

    # 前进键
    feed(nav, WM_XBUTTONUP, 2)
    time.sleep(0.25)
    check("xbutton2.forward", got[:2] == [-1, 1], got[:])

    # 节流：THROTTLE 内连点只算一次
    time.sleep(THROTTLE + 0.05)
    got.clear()
    feed(nav, WM_XBUTTONUP, 1)
    feed(nav, WM_XBUTTONUP, 1)
    time.sleep(0.25)
    check("throttle.single", len(got) == 1, got[:])

    # 其它鼠标消息不触发导航
    time.sleep(THROTTLE + 0.05)
    got.clear()
    feed(nav, 0x0200)          # WM_MOUSEMOVE
    feed(nav, 0x0201)          # WM_LBUTTONDOWN
    time.sleep(0.2)
    check("ignore_other", got == [], got[:])

    # 前台不匹配时不处理（生产环境靠这条避免影响其它程序）
    nav.title_hint = "一个绝对不可能出现的窗口标题__FMP__"
    time.sleep(THROTTLE + 0.05)
    got.clear()
    ret = feed(nav, WM_XBUTTONUP, 1)
    time.sleep(0.2)
    check("foreground_guard", got == [] and ret != 1, (got[:], ret))

    stop.set()
    nav.stop()
    return finish()


def finish():
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    json.dump(report, open(os.path.join(out, "mouse_nav_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    total = len(report["checks"])
    ok = sum(1 for c in report["checks"] if c["ok"])
    print("鼠标侧键自测：%d/%d 通过" % (ok, total))
    for c in report["checks"]:
        if not c["ok"]:
            print("  FAIL %s — %s" % (c["name"], c["detail"]))
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
