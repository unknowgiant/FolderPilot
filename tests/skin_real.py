# -*- coding: utf-8 -*-
"""真实窗口皮肤验证：改配置 → 启动打包版 → 截图 → 关闭 → 还原配置。

Chrome 里截图只证明 CSS 正确；WebView2 才代表用户实际看到的样子
（backdrop-filter 这类合成层特性尤其需要真机确认）。
窗口先置顶并固定位置，否则截图可能抓到压在它上面的其它程序。
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fmp.version import APP_TITLE, EXE_NAME  # noqa: E402

CFG = os.path.join(os.environ["APPDATA"], "FileManagerMulti", "v1", "config.json")
OUT = os.path.join(ROOT, "tests", "output")
u32 = ctypes.windll.user32
u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
u32.FindWindowW.restype = ctypes.c_void_p
u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_long * 4)]
u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
u32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)
SWP_SHOWWINDOW = 0x0040


def load_cfg():
    try:
        return json.load(open(CFG, encoding="utf-8"))
    except Exception:
        return {}


def save_cfg(d):
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    json.dump(d, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def find(title):
    return u32.FindWindowW(None, title) or 0


def main():
    # 参数：主题 key 列表；--op 40 可指定工作面不透明度（验证滑杆在真机上的合成）
    args = sys.argv[1:]
    op = None
    if "--op" in args:
        i = args.index("--op")
        op = float(args[i + 1])
        args = args[:i] + args[i + 2:]
    skins = args or ["xinghe", "mose"]
    orig = load_cfg()
    exe = os.path.join(ROOT, EXE_NAME)
    os.makedirs(OUT, exist_ok=True)
    report = []
    for sk in skins:
        cfg = load_cfg()
        cfg["skin"] = sk
        cfg["skin_wallpaper"] = True
        if op is not None:
            cfg["skin_surface"] = op
        save_cfg(cfg)
        p = subprocess.Popen([exe], close_fds=True)
        hwnd = 0
        for _ in range(120):
            time.sleep(0.25)
            hwnd = find(APP_TITLE)
            if hwnd and u32.IsWindowVisible(hwnd):
                break
        # 置顶 + 固定位置，避免被其它窗口盖住导致截到别的程序。
        # 窗口刚创建时 SetWindowPos 可能不生效（会留在副屏或记忆位置），
        # 所以设完回读坐标，不在主屏左上角就再设一次。
        for _ in range(4):
            u32.SetWindowPos(hwnd, HWND_TOPMOST, 30, 30, 1320, 880, SWP_SHOWWINDOW)
            time.sleep(0.35)
            chk = (ctypes.c_long * 4)()
            u32.GetWindowRect(hwnd, ctypes.byref(chk))
            if 0 <= chk[0] < 200 and 0 <= chk[1] < 200:
                break
        u32.SetForegroundWindow(hwnd)
        time.sleep(3.2)                     # 等壁纸与模糊层合成完
        rect = (ctypes.c_long * 4)()
        u32.GetWindowRect(hwnd, ctypes.byref(rect))
        l, t, r, b = rect
        img = None
        if r > l and b > t:
            img = ImageGrab.grab(bbox=(l + 1, t + 1, r - 1, b - 1))
            suffix = f"_op{int(op)}" if op is not None else ""
            img.save(os.path.join(OUT, f"real_{sk}{suffix}.png"))
        u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004)
        if hwnd:
            u32.PostMessageW(hwnd, 0x0010, None, None)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        time.sleep(1.2)
        rem = find(APP_TITLE)
        if rem:
            u32.PostMessageW(rem, 0x0010, None, None)
            time.sleep(0.8)
        report.append({"skin": sk, "op": op, "hwnd": hwnd, "rect": [l, t, r, b],
                       "shot": bool(img), "residual": bool(find(APP_TITLE))})
    save_cfg(orig)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
