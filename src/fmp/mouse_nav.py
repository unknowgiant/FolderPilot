# -*- coding: utf-8 -*-
"""鼠标侧键（后退 / 前进）导航。

问题：WebView2 把鼠标侧键当成浏览器的「后退 / 前进」，而本应用是单页界面、
没有导航历史，于是按了没反应，有时还会把页面带离现场。

做法：装一个 WH_MOUSE_LL 低级鼠标钩子，在消息到达 WebView2 之前接住
WM_XBUTTONUP：
  · 侧键 1（后退）→ 回调(-1)，侧键 2（前进）→ 回调(+1)
  · 只有本程序窗口在前台时才处理，其它程序完全不受影响
  · 处理完返回 1 吞掉消息，避免 WebView2 再走它自己的后退逻辑
  · 回调在独立线程里执行（evaluate_js 可能阻塞，绝不能让钩子线程卡住，
    否则整个系统的鼠标都会变滞）

钩子线程用 PeekMessage 轮询泵消息，退出信号到达后 UnhookWindowsHookEx。
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

WH_MOUSE_LL = 14
WM_XBUTTONUP = 0x020C
XBUTTON1 = 1
XBUTTON2 = 2
PM_REMOVE = 0x0001

THROTTLE = 0.12          # 秒；侧键偶尔会连发，避免一次点击翻两层


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT),
                ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


class MouseNav:
    """title_hint：窗口标题里包含它，才算「本程序在前台」。"""

    def __init__(self, title_hint: str, on_nav, shutdown: threading.Event):
        self.title_hint = title_hint
        self.on_nav = on_nav            # 回调(delta)，delta = -1 / +1
        self.shutdown = shutdown
        self._hook = None
        self._proc = None
        self._thread = None
        self._last = 0.0
        self._ready = threading.Event()

    # ---------- 前台判定 ----------
    def _app_in_front(self) -> bool:
        if not self.title_hint:          # 空串 = 不做前台判定（自测用）
            return True
        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return False
        n = u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return False
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        return self.title_hint in buf.value

    # ---------- 钩子回调 ----------
    def _callback(self, ncode, wparam, lparam):
        u32 = ctypes.windll.user32
        try:
            if ncode == 0 and wparam == WM_XBUTTONUP:
                data = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                button = (data.mouseData >> 16) & 0xFFFF
                if button in (XBUTTON1, XBUTTON2) and self._app_in_front():
                    now = time.time()
                    if now - self._last >= THROTTLE:
                        self._last = now
                        delta = -1 if button == XBUTTON1 else 1
                        # 交给独立线程：evaluate_js 不能被钩子线程等
                        threading.Thread(target=self._fire, args=(delta,),
                                         daemon=True).start()
                    return 1
        except Exception:
            pass
        return u32.CallNextHookEx(None, ncode, wparam, lparam)

    def _fire(self, delta):
        try:
            self.on_nav(delta)
        except Exception:
            pass

    # ---------- 生命周期 ----------
    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="fmp-mouse-nav")
        self._thread.start()
        return self

    def _loop(self):
        u32 = ctypes.windll.user32
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                          wintypes.HINSTANCE, wintypes.DWORD]
        u32.SetWindowsHookExW.restype = wintypes.HHOOK
        u32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int,
                                       wintypes.WPARAM, wintypes.LPARAM]
        u32.CallNextHookEx.restype = ctypes.c_ssize_t
        u32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND,
                                     wintypes.UINT, wintypes.UINT, wintypes.UINT]
        u32.PeekMessageW.restype = wintypes.BOOL

        self._proc = HOOKPROC(self._callback)
        self._hook = u32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            self._ready.set()
            return
        self._ready.set()
        msg = MSG()
        while not self.shutdown.is_set():
            if u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)
        try:
            u32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass

    def stop(self, timeout: float = 1.0):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    @property
    def installed(self) -> bool:
        self._ready.wait(0.5)
        return bool(self._hook)
