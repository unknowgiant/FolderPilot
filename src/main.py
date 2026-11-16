# -*- coding: utf-8 -*-
"""文件管理多面手 —— 应用入口（版本号见 fmp.version）。

启动顺序：单实例锁 → 配置 → 服务 → 本地资源服务 → WebView2 窗口 → 全局热键。
关闭时不做任何跨线程 JS 调用（那会导致窗口销毁与 UI 线程互等而「未响应」）。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes

SHUTDOWN = threading.Event()
MB_ICONINFORMATION, MB_OKCANCEL, IDOK = 0x40, 0x1, 1


def resource_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE = resource_dir()
if BASE not in sys.path and os.path.isdir(os.path.join(BASE, "fmp")):
    sys.path.insert(0, BASE)

from fmp import __version__  # noqa: E402
from fmp.bridge import Bridge  # noqa: E402
from fmp.config import APP_TITLE, Config  # noqa: E402
from fmp.dragdrop import DragApi, DragService  # noqa: E402
from fmp.model import long_path  # noqa: E402
from fmp.mouse_nav import MouseNav  # noqa: E402
from fmp.ops import TaskManager  # noqa: E402
from fmp.search import SearchService  # noqa: E402
from fmp.server import UIServer  # noqa: E402
from fmp.version import (APP_ID, APP_VERSION, DATA_DIR_DISPLAY,  # noqa: E402
                         DATA_SERIES, LEGACY_UNINSTALL_PREFIX, PROJECT_CODE, UNINSTALL_KEY)


def _migrate_legacy_data(base: str, target: str):
    """把旧版本目录里的 config.json 搬到当前主版本目录。

    1.0 及以前的数据在 %APPDATA%\\FileManagerMulti\\1.0，从 1.1 起改为按
    主版本归档（v1）。用户全部个人数据（收藏、标签、暂存盘、历史、会话）
    都存在 config.json 里，因此只搬这一个文件即可，不搬日志与导出。
    仅当目标目录还没有配置时才搬，避免覆盖用户已在新版里的设置。
    """
    try:
        if os.path.isfile(os.path.join(target, "config.json")):
            return
        cands = []
        if os.path.isdir(base):
            for name in os.listdir(base):
                d = os.path.join(base, name)
                if not os.path.isdir(d) or d == target:
                    continue
                if not re.fullmatch(r"\d+\.\d+", name):
                    continue
                cfg = os.path.join(d, "config.json")
                if os.path.isfile(cfg):
                    cands.append((os.path.getmtime(cfg), cfg))
        if not cands:
            return
        src = max(cands)[1]
        os.makedirs(target, exist_ok=True)
        shutil.copyfile(src, os.path.join(target, "config.json"))
    except Exception:
        pass


def data_directory():
    if os.environ.get("FMP_PORTABLE") == "1":
        return os.path.join(os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__)), "data")
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else ""
    if exe_dir and os.path.isfile(os.path.join(exe_dir, "portable.flag")):
        return os.path.join(exe_dir, "data")
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)
    target = os.path.join(base, DATA_SERIES)
    _migrate_legacy_data(base, target)
    return target


def message_box(text, title=APP_TITLE, flags=MB_ICONINFORMATION):
    u32 = ctypes.windll.user32
    u32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    u32.MessageBoxW.restype = ctypes.c_int
    return u32.MessageBoxW(0, text, title, flags)


def _legacy_uninstall_keys():
    """枚举旧版安装器留下的版本化卸载键，例如 FileManagerMulti_1_0。"""
    out = []
    path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                if name.startswith(LEGACY_UNINSTALL_PREFIX) and \
                        name != os.path.basename(UNINSTALL_KEY):
                    out.append(path + "\\" + name)
    except OSError:
        pass
    return out


def uninstall(skip_confirm=False):
    """安装版卸载入口：删快捷方式与注册表项，延时删除安装目录，保留用户数据。"""
    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    # 只有「我们自己装的」索引服务才会被移除（指向内置内核目录的那个），
    # 用户自己安装的 Everything 服务一律不动。
    eng = None
    try:
        from fmp.engine import EngineManager
        eng = EngineManager(install_dir, data_directory())
        ours = bool(eng.marker()) and eng.status().get("service_ours")
    except Exception:
        ours = False
    if not skip_confirm:
        rc = message_box(
            f"将卸载「{APP_TITLE}」。\n\n"
            "个人数据（收藏、标签、暂存盘、搜索历史）会保留在\n"
            f"{DATA_DIR_DISPLAY}，可在卸载后手动删除。"
            + ("\n\n内置搜索引擎的 NTFS 索引服务将一并移除（需一次管理员确认）。" if ours else ""),
            "卸载确认", MB_ICONINFORMATION | MB_OKCANCEL)
        if rc != IDOK:
            return 0
    if ours and eng is not None:
        try:
            eng.remove_service_if_ours()
        except Exception:
            pass
    shortcuts = []
    manifest = os.path.join(install_dir, "install.json")
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            shortcuts = json.load(f).get("shortcuts", [])
    except Exception:
        pass
    for s in shortcuts:
        try:
            os.remove(s)
        except OSError:
            pass
    # 当前固定键 + 旧版按版本号建的键（FileManagerMulti_1_0 等）一并清理
    for key in [UNINSTALL_KEY] + _legacy_uninstall_keys():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
    # 当前 exe 正在运行，无法删除自身所在目录。方案：
    #   1) 若与 %TEMP% 同盘，先把自身改名挪出去（运行中的 exe 可改名），
    #      安装目录随即整目录删除；自身残留交给批处理重试删除。
    #   2) 跨盘或改名失败：批处理循环重试删除安装目录（进程退出后即成功）。
    # 不用 PowerShell：实测 -EncodedCommand 进程级开销可达 30 秒。
    self_exe = os.path.abspath(sys.executable)
    pending = ""
    try:
        pending = os.path.join(os.environ.get("TEMP") or install_dir,
                               "fmp_uninst_%d.tmp" % os.getpid())
        os.rename(self_exe, pending)              # 同盘改名；跨盘会抛 OSError
    except OSError:
        pending = ""                              # 交由批处理重试删除安装目录
    try:
        if os.path.isdir(install_dir):
            shutil.rmtree(install_dir, ignore_errors=True)
    except OSError:
        pass
    bat = os.path.join(os.environ.get("TEMP") or install_dir,
                       "fmp_uninst_%d.cmd" % os.getpid())
    targets = [install_dir, pending] if pending else [install_dir]
    lines = ["@echo off"]
    for d in targets:
        lines += ['for /l %%i in (1,1,40) do (',
                  'if exist "' + d + '" (',
                  'rd /s /q "' + d + '"',
                  'if exist "' + d + '" ping -n 2 127.0.0.1 >nul',
                  ')', ')']
    lines.append('del "%~f0"')
    try:
        with open(bat, "w", encoding="mbcs", newline="\r\n") as f:
            f.write("\r\n".join(lines) + "\r\n")
        subprocess.Popen(["cmd", "/c", bat], creationflags=0x08000000,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except Exception:
        pass
    if not skip_confirm:
        message_box("卸载完成，安装目录将在数秒后自动清除。\n个人数据已保留。", "卸载完成")
    return 0


def single_instance():
    """单实例锁：锁名不含版本号，1.0 / 1.1 / 1.2 … 共用同一把锁。

    否则不同版本各自持锁，同机会同时跑起多个实例，端口与配置互相抢。
    锁被占用时把已有窗口唤到前台（旧版本窗口标题不同，故逐个试当前
    标题与"按进程枚举"两种方式）。
    """
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    h = k32.CreateMutexW(None, False, "Local\\" + APP_ID + "_SingleInstance")
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, APP_TITLE) or _find_own_window(APP_ID)
        if hwnd:
            u32.ShowWindow(hwnd, 9)          # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
        return False, h
    return True, h


def _find_own_window(marker):
    """按类名/标题里的项目名找本程序的顶层窗口（兼容旧版本标题）。"""
    u32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        if not u32.IsWindowVisible(hwnd) or u32.GetParent(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        if PROJECT_CODE in buf.value:
            found.append(hwnd)
        return True

    u32.EnumWindows(cb, 0)
    return found[0] if found else 0


def global_hotkey(win, title):
    """Alt+Space 全局呼出搜索。轮询式消息循环，退出时能自然结束。"""
    u32 = ctypes.windll.user32
    MOD_ALT, MOD_NOREPEAT, VK_SPACE, WM_HOTKEY, PM_REMOVE = 0x0001, 0x4000, 0x20, 0x0312, 1

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

    u32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND,
                                 wintypes.UINT, wintypes.UINT, wintypes.UINT]
    u32.PeekMessageW.restype = wintypes.BOOL

    def loop():
        if not u32.RegisterHotKey(None, 1, MOD_ALT | MOD_NOREPEAT, VK_SPACE):
            return
        msg = MSG()
        while not SHUTDOWN.is_set():
            if u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY and msg.wParam == 1 and not SHUTDOWN.is_set():
                    # 标题不再带版本号，精确匹配即可；旧版本实例仍在跑时按
                    # 进程窗口标题里的项目名兜底（_find_own_window）。
                    hwnd = u32.FindWindowW(None, title) or _find_own_window(APP_ID)
                    if hwnd:
                        u32.ShowWindow(hwnd, 9)
                        u32.SetForegroundWindow(hwnd)
                    try:
                        win.evaluate_js("window.FMP && FMP.onGlobalHotkey && FMP.onGlobalHotkey()")
                    except Exception:
                        pass
            else:
                time.sleep(0.06)
        try:
            u32.UnregisterHotKey(None, 1)
        except Exception:
            pass

    threading.Thread(target=loop, daemon=True, name="fmp-hotkey").start()


def selftest():
    """打包后自检：验证资源解包路径、token 注入与 HTTP 命令通道。"""
    import urllib.request
    cfg = Config(data_directory())
    assets = os.path.join(BASE, "assets")
    ui = os.path.join(BASE, "ui")
    svc = SearchService(cfg, assets, cfg.dir)
    bridge = Bridge(cfg, svc, TaskManager()).setup()
    token = "selftest-token"
    server = UIServer(ui, token, long_path, api_handler=bridge.call)
    result = {"ok": False, "base": BASE, "data_dir": cfg.dir}
    try:
        html = urllib.request.urlopen(server.url, timeout=5).read().decode("utf-8")
        css = urllib.request.urlopen(server.url + "app.css", timeout=5).read().decode("utf-8")
        info = json.loads(bridge.call("app.info"))
        listing = json.loads(bridge.call("dir.list", json.dumps({"path": ""})))
        req = urllib.request.Request(
            server.url + "api?t=" + token,
            data=json.dumps({"method": "app.info", "params": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        api_res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        result.update({
            "ok": True, "html_len": len(html), "css_len": len(css),
            "token_injected": token in html and "__FMP_TOKEN__" not in html,
            # 版本占位符必须被替换干净：避免界面上出现 __FMP_VERSION__
            "version_injected": ("__FMP_VERSION__" not in html
                                 and "__FMP_TITLE__" not in html
                                 and f'<span class="brand-ver">{APP_VERSION}</span>' in html),
            "app_info": info.get("data"),
            "dir_list_ok": listing.get("ok", False),
            "dir_entries": len(listing.get("data", {}).get("entries", [])),
            "http_api_ok": bool(api_res.get("ok")) and api_res.get("data", {}).get("version") == APP_VERSION,
            "ui_modules_ready": os.path.isfile(os.path.join(ui, "js", "main.js")),
        })
    except Exception as ex:
        result["error"] = f"{type(ex).__name__}: {ex}"
    finally:
        server.stop()
    os.makedirs(cfg.dir, exist_ok=True)
    with open(os.path.join(cfg.dir, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


def engine_selftest():
    """打包后验证内置搜索引擎：内核能否从安装包释放、能否真搜出结果。

    不弹 UAC：只走 ensure()（服务已存在就用，缺服务就如实返回 needs_auth）。
    """
    cfg = Config(data_directory())
    svc = SearchService(cfg, os.path.join(BASE, "assets"), cfg.dir)
    out = {"ok": False, "data_dir": cfg.dir}
    try:
        # 先单独验证「安装包里的内核能不能落到数据目录」——这一步与最终由谁
        # 应答无关（机器上装了 Everything 时会优先复用它）。
        exe = svc.engine.deploy()
        force = any(a.lower().strip("-") == "bundled" for a in sys.argv[1:])
        st = svc.connect(prefer_bundled=force)
        # 首次使用要读全盘 MFT（实测 20 秒上下），这里最多等 6 轮
        for _ in range(6):
            if st.get("sdk"):
                break
            time.sleep(10)
            st = svc.connect(prefer_bundled=force, wait=12.0)
        eng = st.get("engine", {})
        out.update({"backend": st.get("backend"), "sdk": st.get("sdk"),
                    "service": eng.get("service"), "needs_auth": eng.get("needs_auth"),
                    "engine_exe": exe, "deployed": bool(exe and os.path.isfile(exe)),
                    "version": st.get("version"), "source": eng.get("source")})
        if st.get("sdk"):
            r = svc.run({"query": "Everything.exe", "scope": "global", "limit": 5})
            out["search_total"] = r["total"]
            out["search_ms"] = r["elapsed"]
            out["search_backend"] = r["backend"]
            out["sample"] = r["entries"][0]["path"] if r["entries"] else ""
            out["ok"] = r["total"] >= 1
        else:
            out["note"] = eng.get("last_error") or "内核未就绪"
    except Exception as ex:
        out["error"] = f"{type(ex).__name__}: {ex}"
    try:
        svc.engine.stop()
    except Exception:
        pass
    os.makedirs(cfg.dir, exist_ok=True)
    with open(os.path.join(cfg.dir, "engine_selftest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--engine-test" in sys.argv:
        return engine_selftest()
    if "--uninstall" in sys.argv:
        return uninstall("--yes" in sys.argv or "--silent" in sys.argv)
    ok, _ = single_instance()
    if not ok:
        return 0

    import webview
    cfg = Config(data_directory())
    assets = os.path.join(BASE, "assets")
    ui = os.path.join(BASE, "ui")
    if not os.path.isdir(ui):
        raise RuntimeError(f"缺少界面资源目录：{ui}")

    svc = SearchService(cfg, assets, cfg.dir)
    # Everything 未运行时后台尝试唤起；找不到也不影响启动，会自动退化为本地索引。
    if cfg.get("ev_autostart", True):
        def _auto_connect():
            # 冷启动 Everything 要读全盘 MFT，实测 5–15 秒才应答，所以多试几轮：
            # 首轮等久一点，之后每 8 秒补一次，最多 3 轮，成功后不再打扰。
            for i in range(3):
                try:
                    st = svc.connect(wait=8.0 if i == 0 else 4.0)
                    if st.get("sdk"):
                        return
                except Exception:
                    pass
                time.sleep(8)
        t = threading.Timer(2.0, _auto_connect)
        t.daemon = True
        t.start()
    tasks = TaskManager()
    drag = DragService()
    bridge = Bridge(cfg, svc, tasks, drag).setup()
    token = secrets.token_hex(12)
    server = UIServer(ui, token, long_path, os.path.join(cfg.dir, "ui.log"),
                      api_handler=bridge.call)

    win = webview.create_window(
        APP_TITLE, f"{server.url}?t={token}",
        width=1360, height=860, min_size=(960, 620),
        background_color="#F5F8FC", text_select=False, confirm_close=False,
        # 只暴露一个极小门面用于拖出（drag 需在应用线程执行 OLE 拖放）。
        # 绝不能把 Bridge 整体当 js_api：pywebview 会递归遍历其全部公开属性，
        # Bridge.window 会引出 window.native.AccessibilityObject… 的无限递归，
        # 遍历线程卡死导致关闭时窗口无法销毁。常规命令仍走 HTTP。
        js_api=DragApi(drag),
    )
    bridge.window = win
    global_hotkey(win, APP_TITLE)

    # 鼠标侧键：接住 XBUTTON1/2，当成「后退 / 前进」交给界面处理。
    # 不接的话 WebView2 会按自己的浏览历史后退——单页界面没有历史，按了没反应。
    def _mouse_nav(delta):
        try:
            win.evaluate_js("window.FMP && FMP.onMouseNav && FMP.onMouseNav(%d)" % delta)
        except Exception:
            pass
    MouseNav(PROJECT_CODE, _mouse_nav, SHUTDOWN).start()

    # 不注册 closing 事件：窗口销毁过程中调用 evaluate_js 会与 WebView2
    # 互相等待，正是「关闭时未响应」的根因。会话改由前端 pagehide + sendBeacon 保存。
    webview.start(debug=False)
    SHUTDOWN.set()
    # 内置搜索引擎的内核进程随管理器一起退出（只结束「我们自己启动的」那个，
    # 用户自己开的 Everything 不受影响）；索引由 NTFS 的 USN 日志增量维护，
    # 下次启动重新读 MFT 通常 1–3 秒，不必常驻。
    try:
        svc.engine.stop()
    except Exception:
        pass
    server.stop()

    # 兜底看门狗：若仍有非守护线程拖住解释器，2.5 秒后强制退出
    def _force_exit():
        time.sleep(2.5)
        os._exit(0)
    threading.Thread(target=_force_exit, daemon=True).start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
