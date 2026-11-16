# -*- coding: utf-8 -*-
"""关闭流程回归测试：模拟点击窗口 X，验证进程能在数秒内优雅退出、无残留。

用法：py -3.14 tests/close_test.py
产物：tests/output/close_report.json
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fmp.version import APP_TITLE, EXE_NAME, PROJECT_CODE  # noqa: E402

EXE = os.path.join(ROOT, EXE_NAME)
TITLE = APP_TITLE
WM_CLOSE = 0x0010

u32 = ctypes.windll.user32
u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
u32.FindWindowW.restype = wintypes.HWND
u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.PostMessageW.restype = wintypes.BOOL
u32.IsWindowVisible.argtypes = [wintypes.HWND]
u32.IsWindowVisible.restype = wintypes.BOOL
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD

report = {"rounds": [], "passed": False}


def _window_pids():
    """本程序所有顶层窗口的进程号（含旧版本的窗口，标题里带项目名）。"""
    pids = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        n = u32.GetWindowTextLengthW(hwnd)
        if n > 0 and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            if PROJECT_CODE in buf.value:
                pid = wintypes.DWORD()
                u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pids.append(pid.value)
        return True

    u32.EnumWindows(cb, 0)
    return pids


def clear_leftovers(timeout=8.0):
    """确保没有上一轮 / 旧版本残留的实例，否则会误判为"新实例关不掉"。

    单实例锁跨版本共用，残留实例会让新进程直接退出（表现为窗口不出现），
    因此按「标题含项目名」找窗口并结束对应进程。
    """
    for _ in range(int(timeout * 10)):
        pids = _window_pids()
        if not pids:
            return True
        for pid in set(pids):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        time.sleep(0.2)
    return not _window_pids()


def one_round(idx):
    r = {"round": idx}
    r["clean_start"] = clear_leftovers()
    proc = subprocess.Popen([EXE], cwd=ROOT)
    r["pid"] = proc.pid
    # 窗口先创建后显示：必须等到真正可见再关，否则等于给"还没画出来的
    # 窗口"发 WM_CLOSE，会撞上 WebView2 初始化，属测试自身的时序错误。
    hwnd = 0
    t0 = time.time()
    while time.time() - t0 < 18:
        h = u32.FindWindowW(None, TITLE)
        if h and u32.IsWindowVisible(h):
            hwnd = h
            break
        time.sleep(0.05)
    r["window_found"] = bool(hwnd)
    r["startup_ms"] = int((time.time() - t0) * 1000)
    if not hwnd:
        r["error"] = "窗口未出现"
        proc.kill()
        return r
    win_pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
    r["window_pid"] = win_pid.value
    time.sleep(2.0)                      # 等待初始化完成，模拟正常使用后关闭
    t1 = time.time()
    u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    try:
        proc.wait(timeout=12)
        r["exit_code"] = proc.returncode
        r["close_ms"] = int((time.time() - t1) * 1000)
        r["exited"] = True
    except subprocess.TimeoutExpired:
        r["exited"] = False
        r["close_ms"] = 12000
        proc.kill()
        proc.wait(timeout=5)
    gone = True
    for _ in range(40):
        if not u32.FindWindowW(None, TITLE):
            break
        time.sleep(0.1)
    else:
        gone = False
    r["window_gone"] = gone
    r["ok"] = bool(r["clean_start"] and r["window_found"] and r.get("exited")
                   and gone and r["close_ms"] < 10000)
    return r


def main():
    if not os.path.isfile(EXE):
        print("缺少主程序：", EXE)
        return 1
    for i in (1, 2):
        report["rounds"].append(one_round(i))
    report["passed"] = all(x.get("ok") for x in report["rounds"])
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "close_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
