# -*- coding: utf-8 -*-
"""真实窗口拖放链路验证（需要 GUI 桌面环境）。

验证内容：
  1. 前端经 window.pywebview.api.drag 的桥调用能进入拖放循环
     （DragService 的线程检查通过，不再返回"UI 线程"错误）；
  2. SHDoDragDrop 循环启动后能正确接管鼠标捕获 —— 合成鼠标松开时循环
     结束并返回结果（专职线程方案正是死在这里）；
  3. 整个过程窗口不崩溃、退出干净。

用法：py -3.14 tests/drag_test.py
"""
import ctypes
import json
import os
import sys
import tempfile
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from fmp.bridge import Bridge            # noqa: E402
from fmp.config import Config            # noqa: E402
from fmp.dragdrop import DragApi, DragService  # noqa: E402
from fmp.model import long_path          # noqa: E402
from fmp.ops import TaskManager          # noqa: E402
from fmp.search import SearchService     # noqa: E402
from fmp.server import UIServer          # noqa: E402

u32 = ctypes.windll.user32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]


def send_mouse(flags, dx=0, dy=0):
    inp = INPUT()
    inp.type = 0
    inp.mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
    arr = (INPUT * 1)(inp)
    return u32.SendInput(1, arr, ctypes.sizeof(INPUT))


result = {"steps": [], "passed": False}


def step(name, ok, detail=""):
    result["steps"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))


def main():
    import webview

    d = tempfile.mkdtemp(prefix="fmp_dragwin_")
    sample = os.path.join(d, "拖出样本.txt")
    with open(sample, "w", encoding="utf-8") as f:
        f.write("drag-out test")

    cfg = Config(os.path.join(d, "cfg"))
    svc = SearchService(cfg, os.path.join(SRC, "assets"), cfg.dir)
    drag = DragService()
    bridge = Bridge(cfg, svc, TaskManager(), drag).setup()
    server = UIServer(os.path.join(SRC, "ui"), "drag-test-token", long_path,
                      os.path.join(cfg.dir, "ui.log"), api_handler=bridge.call)

    win = webview.create_window(
        "FmpDragTest", f"{server.url}?t=drag-test-token",
        width=1000, height=700, confirm_close=False, js_api=DragApi(drag))

    state = {"launched": False}

    def run_test():
        try:
            _run_test_body(win, drag, sample)
        except Exception as ex:
            step("测试过程无异常", False, f"{type(ex).__name__}: {ex}")
            result["passed"] = False
        finally:
            send_mouse(0x4)
            try:
                win.destroy()
            except Exception:
                pass

    def _run_test_body(win, drag, sample):
        # 等 UI 就绪：页面 boot 完成 + pywebview 桥注入（拖出依赖桥）
        r = None
        for _ in range(150):
            try:
                r = win.evaluate_js(
                    "document.body.dataset.ready && window.pywebview && "
                    "window.pywebview.api && typeof window.pywebview.api.drag === 'function' "
                    "? 'ok' : ''")
                if r:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        step("窗口/页面/桥均已就绪", r == "ok", repr(r))

        # 光标移到窗口客户区中心并按下（WebView2 获得鼠标捕获）
        rect = ctypes.create_unicode_buffer(256)
        try:
            import win32gui  # pywebview 环境未必有，失败则跳过精确定位
            h = win32gui.FindWindow(None, "FmpDragTest")
            l, t, rr, b = win32gui.GetWindowRect(h)
            cx, cy = (l + rr) // 2, (t + b) // 2
        except Exception:
            cx, cy = 600, 400
        u32.SetCursorPos(cx, cy)
        step("合成鼠标按下", send_mouse(0x2) == 1)
        time.sleep(0.15)

        # 页面内发起桥调用（与前端 dragdrop.js 的路径一致）。
        # ExecuteScriptAsync 对 async 函数立即返回，不等待 promise。
        js = (
            "window.__dragResult = null; "
            "window.pywebview.api.drag("
            + json.dumps(json.dumps({"paths": [sample], "effect": "copyMove"})) +
            ").then(r => { window.__dragResult = "
            "(typeof r === 'string' ? JSON.parse(r) : r); }); 'sent'"
        )
        r = win.evaluate_js(js)
        step("页面已发起 drag.start 桥调用", r == "sent", repr(r))

        # 等 UI 线程进入拖放循环（此时 SHDoDragDrop 正在泵消息）
        dragging = False
        for _ in range(40):
            st = drag.status()
            if st["state"] == "dragging":
                dragging = True
                break
            time.sleep(0.1)
        step("拖放循环已启动（UI 线程）", dragging, drag.status())

        # 移动 + 松开：若捕获被正确接管，循环应结束
        time.sleep(0.2)
        send_mouse(0x1, 120, 80)
        time.sleep(0.25)
        send_mouse(0x4)
        done = False
        for _ in range(60):
            st = drag.status()
            if st["state"] in ("done", "error"):
                done = True
                break
            time.sleep(0.1)
        step("鼠标松开后拖放循环结束", done, drag.status())

        # 页面侧 promise 应拿到结果（UI 线程恢复后 JS 才能继续）
        page_result = None
        for _ in range(60):
            try:
                pr = win.evaluate_js("JSON.stringify(window.__dragResult)")
                if pr and pr != "null":
                    page_result = json.loads(pr)
                    break
            except Exception:
                pass
            time.sleep(0.1)
        ok = bool(page_result and page_result.get("data", page_result).get("state") == "done")
        step("前端拿到拖放结果", ok, json.dumps(page_result, ensure_ascii=False)[:200])

        result["passed"] = all(s["ok"] for s in result["steps"])
        state["launched"] = True

    try:
        webview.start(func=run_test)
    finally:
        try:
            win.destroy()
        except Exception:
            pass
        send_mouse(0x4)
    server.stop()
    out = os.path.join(ROOT, "tests", "output", "drag_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("passed:", result["passed"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
