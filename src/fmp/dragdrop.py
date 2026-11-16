# -*- coding: utf-8 -*-
"""原生 OLE 拖放：把选中项"拖"给资源管理器 / 云盘客户端 / 微信等外部程序。

为什么需要这一层：
    WebView2 里的 HTML5 拖拽是浏览器内部拖拽，拖出窗口时不会给外部程序
    提供 CF_HDROP，云盘客户端因此收不到文件。资源管理器之所以能拖，
    是因为它调用的是 OLE 的 DoDragDrop + 一个带 CF_HDROP 的 IDataObject。

为什么自己实现 IDataObject 而不用 SHCreateDataObject：
    SHCreateDataObject 要求「父文件夹 PIDL + 相对子 PIDL」，同目录多选没问题，
    但搜索结果跨目录多选就拼不出正确的 CF_HDROP。这里用纯 ctypes 实现一个
    足够完整的数据对象：CF_HDROP（任意路径组合）、CF_UNICODETEXT（回退用）、
    Preferred DropEffect（复制/移动语义）、SetData（拖动中目标程序会写回
    DropDescription 等格式，接受并保存以免拖放被中断）、EnumFormatEtc。

线程模型：
    前端检测到"拖出窗口" → POST /api drag.start → 请求入队
    → PostMessage 给主窗口 → 窗口过程（SetWindowSubclass）在 UI 线程
    调 SHDoDragDrop（pdsrc=NULL，系统提供默认拖放源：光标、Esc 取消、
    Ctrl/Shift 修饰键）→ 结果写回状态供前端轮询。
    DoDragDrop 必须在窗口所属线程调用（内部对源窗口 SetCapture）。
"""
from __future__ import annotations

import ctypes
import json
import os
import struct
import threading
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
ole32 = ctypes.windll.ole32
comctl32 = ctypes.windll.comctl32

WM_FMP_DRAG = 0x8000 + 501          # WM_APP + 501，仅本进程内使用
DROPEFFECT_NONE, DROPEFFECT_COPY, DROPEFFECT_MOVE = 0, 1, 2
VK_LBUTTON = 0x01
GMEM_MOVEABLE = 0x0002
CF_HDROP = 15
CF_UNICODETEXT = 13
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
E_NOTIMPL = ctypes.c_long(0x80004001).value
S_OK = 0
S_FALSE = 1


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(d1, d2, d3, rest):
    g = GUID()
    g.Data1, g.Data2, g.Data3 = d1, d2, d3
    for i, b in enumerate(rest):
        g.Data4[i] = b
    return g


IID_IUnknown = _guid(0x00000000, 0x0000, 0x0000,
                     (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IDataObject = (0x0000010E, 0x0000, 0x0000,
                   (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
IID_IEnumFORMATETC = (0x00000103, 0x0000, 0x0000,
                      (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))


class FORMATETC(ctypes.Structure):
    _fields_ = [("cfFormat", wintypes.UINT), ("ptd", ctypes.c_void_p),
                ("dwAspect", wintypes.DWORD), ("lindex", wintypes.LONG),
                ("tymed", wintypes.DWORD)]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [("tymed", wintypes.DWORD), ("hGlobal", ctypes.c_void_p),
                ("punkForRelease", ctypes.c_void_p)]


def _bind():
    u32, k32 = user32, kernel32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k32.GlobalSize.restype = ctypes.c_size_t
    k32.GlobalSize.argtypes = [ctypes.c_void_p]
    k32.GlobalFree.restype = ctypes.c_void_p
    k32.GlobalFree.argtypes = [ctypes.c_void_p]
    u32.RegisterClipboardFormatW.restype = wintypes.UINT
    u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    shell32.SHDoDragDrop.restype = ctypes.c_long
    shell32.SHDoDragDrop.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    ole32.OleInitialize.restype = ctypes.c_long
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    comctl32.SetWindowSubclass.restype = wintypes.BOOL
    comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.c_size_t]
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
    comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT,
                                         wintypes.WPARAM, wintypes.LPARAM]
    u32.PostMessageW.restype = wintypes.BOOL
    u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM]
    u32.GetAsyncKeyState.restype = ctypes.c_short
    u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    # 专职拖放线程的窗口与消息循环（64 位下句柄返回值必须显式声明）
    u32.RegisterClassW.restype = wintypes.ATOM
    u32.RegisterClassW.argtypes = [ctypes.c_void_p]
    u32.CreateWindowExW.restype = wintypes.HWND
    u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                    wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u32.GetMessageW.restype = ctypes.c_int
    u32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
    u32.TranslateMessage.restype = wintypes.BOOL
    u32.TranslateMessage.argtypes = [ctypes.c_void_p]
    u32.DispatchMessageW.restype = ctypes.c_ssize_t
    u32.DispatchMessageW.argtypes = [ctypes.c_void_p]
    u32.DefWindowProcW.restype = ctypes.c_ssize_t
    u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    u32.PostQuitMessage.restype = None
    u32.PostQuitMessage.argtypes = [ctypes.c_int]
    k32.GetModuleHandleW.restype = wintypes.HINSTANCE
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


_bind()

# 常用 COM 错误码
DV_E_FORMATETC = ctypes.c_long(0x80040064).value
DV_E_TYMED = ctypes.c_long(0x80040069).value


def _hglobal(blob: bytes):
    """把字节串装进新的可移动全局内存；调用方（ReleaseStgMedium）负责释放。"""
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
    if not h:
        raise MemoryError("GlobalAlloc 失败")
    p = kernel32.GlobalLock(h)
    if not p:
        kernel32.GlobalFree(h)
        raise MemoryError("GlobalLock 失败")
    ctypes.memmove(p, blob, len(blob))
    kernel32.GlobalUnlock(h)
    return h


def _hdrop_blob(paths):
    payload = "\x00".join(paths) + "\x00\x00"
    return struct.pack("IIIii", 20, 0, 0, 0, 1) + payload.encode("utf-16-le")


# ---------------------------------------------------------------- COM 对象基座
# 约定：每个 COM 对象是一个 Python 实例；接口指针指向一块只含"vtable 指针"的
# 内存。回调按地址映射回 Python 实例（_REGISTRY）。Release 归零时注销。
_REGISTRY = {}


def _register(obj):
    _REGISTRY[obj.address] = obj
    return obj.address


def _unregister(addr):
    _REGISTRY.pop(addr, None)


class _ComBase:
    _methods = []          # [(name, WINFUNCTYPE, impl工厂)]
    _accepts = ()          # 额外接受的 IID（4 元组形式）

    def __init__(self):
        self._ref = 1
        self._keep = []    # 持有回调引用防 GC
        slots = []
        for name, ftype, impl in self._methods:
            cb = ftype(self._thunk(name, impl))
            self._keep.append(cb)
            slots.append(ctypes.cast(cb, ctypes.c_void_p).value)
        self._vtbl = (ctypes.c_void_p * len(slots))(*slots)
        self._mem = ctypes.c_void_p(ctypes.cast(self._vtbl, ctypes.c_void_p).value)
        self.address = ctypes.addressof(self._mem)
        _register(self)

    def ptr(self):
        return ctypes.cast(ctypes.addressof(self._mem), ctypes.c_void_p)

    def _thunk(self, name, impl):
        def call(this, *a):
            key = this if isinstance(this, int) else (
                this.value if isinstance(this, ctypes.c_void_p) else
                ctypes.cast(this, ctypes.c_void_p).value)
            obj = _REGISTRY.get(key)
            if obj is None:
                return E_NOTIMPL
            try:
                return getattr(obj, name)(*a)
            except Exception:
                return E_NOTIMPL
        return call

    # ---- IUnknown ----
    def QueryInterface(self, riid, ppv):
        try:
            g = ctypes.cast(riid, ctypes.POINTER(GUID)).contents
            key = (g.Data1, g.Data2, g.Data3, tuple(g.Data4))
            ok = key == (0, 0, 0, (0xC0, 0, 0, 0, 0, 0, 0, 0x46)) or key in self._accepts
        except Exception:
            ok = False
        if not ok:
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = None
            return ctypes.c_long(0x80004002).value      # E_NOINTERFACE
        self._ref += 1
        ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = self.ptr()
        return S_OK

    def AddRef(self):
        self._ref += 1
        return self._ref

    def Release(self):
        self._ref -= 1
        if self._ref <= 0:
            self._destroy()
            _unregister(self.address)
        return max(0, self._ref)

    def _destroy(self):
        pass


# HRESULT 签名工厂（每次返回新的 WINFUNCTYPE 类）
def _HR():
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)          # (self)


def _HR1(*a):
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *a)      # (self, ...)


# ---------------------------------------------------------------- IDataObject
class HdDataSource(_ComBase):
    """提供 CF_HDROP / CF_UNICODETEXT / Preferred DropEffect 的数据对象。"""

    def __init__(self, paths, allowed=DROPEFFECT_COPY | DROPEFFECT_MOVE):
        self._paths = list(paths)
        self._allowed = allowed
        self._fmt_effect = user32.RegisterClipboardFormatW("Preferred DropEffect") or 0
        self._stored = []          # SetData 存进来的 (fmt, hGlobal)，Release 时释放
        self._formats = []
        if self._paths:
            self._formats.append(CF_HDROP)
            self._formats.append(CF_UNICODETEXT)
        if self._fmt_effect:
            self._formats.append(self._fmt_effect)
        self._accepts = (IID_IDataObject,)
        # vtable：IUnknown 3 + IDataObject 9
        self._methods = [
            ("QueryInterface", _HR1(ctypes.c_void_p, ctypes.c_void_p), None),
            ("AddRef", _HR(), None),
            ("Release", _HR(), None),
            ("GetData", _HR1(ctypes.c_void_p, ctypes.c_void_p), None),
            ("GetDataHere", _HR1(ctypes.c_void_p, ctypes.c_void_p), None),
            ("QueryGetData", _HR1(ctypes.c_void_p), None),
            ("GetCanonicalFormatEtc", _HR1(ctypes.c_void_p, ctypes.c_void_p), None),
            ("SetData", _HR1(ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL), None),
            ("EnumFormatEtc", _HR1(wintypes.DWORD, ctypes.c_void_p), None),
            ("DAdvise", _HR1(ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                             ctypes.c_void_p), None),
            ("DUnadvise", _HR1(wintypes.DWORD), None),
            ("EnumDAdvise", _HR1(ctypes.c_void_p), None),
        ]
        super().__init__()

    # ---- 供 DragService 使用的句柄与释放 ----
    def _destroy(self):
        for _, h in self._stored:
            kernel32.GlobalFree(h)
        self._stored = []

    # ---- IDataObject ----
    def _blob_for(self, fmt):
        if fmt == CF_HDROP:
            return _hdrop_blob(self._paths)
        if fmt == CF_UNICODETEXT:
            return ("\r\n".join(self._paths) + "\x00").encode("utf-16-le")
        if self._fmt_effect and fmt == self._fmt_effect:
            return struct.pack("I", self._allowed)
        return None

    def GetData(self, pfe, pmed):
        if not pfe or not pmed:
            return E_NOTIMPL
        fe = ctypes.cast(pfe, ctypes.POINTER(FORMATETC)).contents
        # 优先返回拖动中目标程序 SetData 进来的格式（如 DropDescription）
        for fmt, h in self._stored:
            if fmt == fe.cfFormat:
                src = kernel32.GlobalLock(h)
                if not src:
                    break
                size = kernel32.GlobalSize(h)
                blob = ctypes.string_at(src, size)
                kernel32.GlobalUnlock(h)
                med = ctypes.cast(pmed, ctypes.POINTER(STGMEDIUM)).contents
                med.tymed = TYMED_HGLOBAL
                med.hGlobal = _hglobal(blob)
                med.punkForRelease = None
                return S_OK
        blob = self._blob_for(fe.cfFormat)
        if blob is None or not (fe.tymed & TYMED_HGLOBAL) or fe.dwAspect != DVASPECT_CONTENT:
            return DV_E_FORMATETC
        med = ctypes.cast(pmed, ctypes.POINTER(STGMEDIUM)).contents
        med.tymed = TYMED_HGLOBAL
        med.hGlobal = _hglobal(blob)
        med.punkForRelease = None
        return S_OK

    def GetDataHere(self, pfe, pmed):
        return E_NOTIMPL        # 目标已提供内存的优化路径，不做

    def QueryGetData(self, pfe):
        if not pfe:
            return E_NOTIMPL
        fe = ctypes.cast(pfe, ctypes.POINTER(FORMATETC)).contents
        if not (fe.tymed & TYMED_HGLOBAL) or fe.dwAspect != DVASPECT_CONTENT:
            return DV_E_TYMED
        if self._blob_for(fe.cfFormat) is None:
            return DV_E_FORMATETC
        return S_OK

    def GetCanonicalFormatEtc(self, pfe, pfeOut):
        if pfeOut:
            ctypes.cast(pfeOut, ctypes.POINTER(FORMATETC)).contents.ptd = None
        return E_NOTIMPL

    def SetData(self, pfe, pmed, fRelease):
        """接受目标程序写回的格式（拖动中的 DropDescription 等），接管内存。"""
        if not pfe or not pmed:
            return E_NOTIMPL
        fe = ctypes.cast(pfe, ctypes.POINTER(FORMATETC)).contents
        med = ctypes.cast(pmed, ctypes.POINTER(STGMEDIUM)).contents
        if med.tymed != TYMED_HGLOBAL or not med.hGlobal:
            return E_NOTIMPL
        if fRelease:
            self._stored.append((fe.cfFormat, med.hGlobal))
            med.hGlobal = None          # 所有权已转移
            med.tymed = 0
            return S_OK
        src = kernel32.GlobalLock(med.hGlobal)
        if not src:
            return E_NOTIMPL
        size = kernel32.GlobalSize(med.hGlobal)
        blob = ctypes.string_at(src, size)
        kernel32.GlobalUnlock(med.hGlobal)
        self._stored.append((fe.cfFormat, _hglobal(blob)))
        return S_OK

    def EnumFormatEtc(self, direction, ppenum):
        if direction != 1:              # DATADIR_GET
            return E_NOTIMPL
        if not ppenum:
            return E_NOTIMPL
        enum = _FmtEnum(self._formats)
        enum.AddRef()
        ctypes.cast(ppenum, ctypes.POINTER(ctypes.c_void_p))[0] = enum.ptr()
        return S_OK

    def DAdvise(self, *a):
        return E_NOTIMPL

    def DUnadvise(self, *a):
        return E_NOTIMPL

    def EnumDAdvise(self, ppenum):
        return E_NOTIMPL


# ---------------------------------------------------------------- IEnumFORMATETC
class _FmtEnum(_ComBase):
    def __init__(self, formats):
        self._formats = list(formats)
        self._pos = 0
        self._accepts = (IID_IEnumFORMATETC,)
        self._methods = [
            ("QueryInterface", _HR1(ctypes.c_void_p, ctypes.c_void_p), None),
            ("AddRef", _HR(), None),
            ("Release", _HR(), None),
            ("Next", _HR1(wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p), None),
            ("Skip", _HR1(wintypes.ULONG), None),
            ("Reset", _HR(), None),
            ("Clone", _HR1(ctypes.c_void_p), None),
        ]
        super().__init__()

    def Next(self, celt, pfe, pfetched):
        if not pfe:
            return E_NOTIMPL
        got = 0
        while got < celt and self._pos < len(self._formats):
            fmt = self._formats[self._pos]
            self._pos += 1
            fe = FORMATETC(fmt, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
            dst = ctypes.cast(pfe, ctypes.POINTER(FORMATETC))
            dst[got] = fe
            got += 1
        if pfetched:
            ctypes.cast(pfetched, ctypes.POINTER(wintypes.ULONG))[0] = got
        return S_OK if got == celt else S_FALSE

    def Skip(self, celt):
        self._pos = min(self._pos + celt, len(self._formats))
        return S_OK if self._pos >= len(self._formats) else S_FALSE

    def Reset(self):
        self._pos = 0
        return S_OK

    def Clone(self, ppenum):
        if not ppenum:
            return E_NOTIMPL
        e = _FmtEnum(self._formats)
        e._pos = self._pos
        e.AddRef()
        ctypes.cast(ppenum, ctypes.POINTER(ctypes.c_void_p))[0] = e.ptr()
        return S_OK


def make_data_object(paths, allowed=DROPEFFECT_COPY | DROPEFFECT_MOVE):
    """由任意绝对路径列表创建可拖放的 IDataObject（返回 HdDataSource）。

    返回的对象初始引用 1，调用方在拖放结束后调 Release()。
    """
    paths = [p for p in paths if p]
    if not paths:
        raise ValueError("没有可拖动的项目")
    return HdDataSource(paths, allowed)


# ---------------------------------------------------------------- 拖放服务
def _mask(effect):
    e = (effect or "copy").lower()
    if e in ("move", "cut"):
        return DROPEFFECT_MOVE
    if e in ("auto", "copymove", "all"):
        return DROPEFFECT_COPY | DROPEFFECT_MOVE
    return DROPEFFECT_COPY


class DragService:
    """原生 OLE 拖放执行器。

    线程模型（实测结论）：
      · pywebview 的 js_api 回调、事件回调都不在窗口 UI 线程上，
        而鼠标按下时的捕获在 UI 线程 —— 直接在回调线程调
        SHDoDragDrop 会抢不到捕获，拖放循环永不结束。
      · 解法：AttachThreadInput 把回调线程挂到窗口线程的输入队列，
        两线程共享捕获状态后，DoDragDrop 的 SetCapture 即可全局生效，
        鼠标松开能正常送达拖放循环。
      · 前端优先经 window.pywebview.api.call 触发（回调线程）；
        HTTP 通道同样放行（同样 attach），两路都可用。
      · 拖放期间回调线程阻塞在 SHDoDragDrop 的内部消息泵，属预期。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._busy = False
        self._state = {"state": "idle", "effect": 0, "count": 0,
                       "error": "", "elapsed": 0, "paths": []}

    # ---------- 前端接口 ----------
    def start(self, paths, effect="copy", hwnd=0):
        paths = [p for p in (paths or []) if p]
        if not paths:
            return {"started": False, "reason": "没有选中任何项目"}
        with self._lock:
            if self._busy:
                return {"started": False, "reason": "已有拖放正在进行"}
            self._busy = True
        t0 = time.time()
        main_hwnd = 0
        attached = False
        ui_tid = 0
        try:
            k32, u32 = kernel32, user32
            k32.GetCurrentThreadId.restype = wintypes.DWORD
            k32.GetCurrentThreadId.argtypes = []
            main_hwnd = hwnd or find_main_window()
            if not main_hwnd:
                return {"started": False, "reason": "未找到应用窗口"}
            u32.GetWindowThreadProcessId.restype = wintypes.DWORD
            u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            ui_tid = u32.GetWindowThreadProcessId(main_hwnd, None)
            cur_tid = k32.GetCurrentThreadId()
            if ui_tid and ui_tid != cur_tid:
                u32.AttachThreadInput.restype = wintypes.BOOL
                u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
                attached = bool(u32.AttachThreadInput(cur_tid, ui_tid, True))
            # 用户已松手（请求延迟到达）就不启动，避免"幽灵拖拽"
            if not (u32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
                return {"started": False, "reason": "鼠标已松开，拖放取消"}
            # 本线程（桥回调/HTTP 线程）需 STA 才能跑 DoDragDrop
            ole32.OleInitialize(None)
            mask = _mask(effect)
            obj = make_data_object(paths, mask)
            try:
                with self._lock:
                    self._state = {"state": "dragging", "effect": 0,
                                   "count": len(paths), "error": "",
                                   "elapsed": 0, "paths": paths}
                out = wintypes.DWORD(mask)
                hr = shell32.SHDoDragDrop(main_hwnd, obj.ptr(), None, mask,
                                          ctypes.byref(out))
                effect_done = int(out.value) if hr >= 0 else DROPEFFECT_NONE
                err = "" if hr >= 0 else "拖放失败 (HRESULT %#x)" % (hr & 0xFFFFFFFF)
                st = {"state": "done" if not err else "error",
                      "effect": effect_done, "count": len(paths),
                      "error": err, "elapsed": round(time.time() - t0, 2),
                      "paths": paths}
                with self._lock:
                    self._state = st
                return st
            finally:
                obj.Release()
        except Exception as ex:
            st = {"state": "error", "effect": 0, "count": len(paths),
                  "error": str(ex), "elapsed": round(time.time() - t0, 2),
                  "paths": paths}
            with self._lock:
                self._state = st
            return st
        finally:
            if attached and ui_tid:
                try:
                    user32.AttachThreadInput(kernel32.GetCurrentThreadId(), ui_tid, False)
                except Exception:
                    pass
            with self._lock:
                self._busy = False

    def status(self):
        with self._lock:
            return dict(self._state)

    def reset(self):
        with self._lock:
            self._state = {"state": "idle", "effect": 0, "count": 0,
                           "error": "", "elapsed": 0, "paths": []}
        return True


class DragApi:
    """pywebview 的 js_api 门面：只暴露一个方法。

    为什么不能直接把 Bridge 当 js_api：
      pywebview 生成 JS 接口时会递归遍历对象的**所有公开属性**
      （webview/util.py get_functions）。Bridge 上挂着 window（pywebview
      窗口对象），于是它一路展开 window.native.AccessibilityObject.Bounds
      .Empty.Empty.…  每层都返回新对象、id 去重失效，最终无限递归直到
      RecursionError；该遍历线程卡死期间窗口无法正常销毁，表现为
      「关闭时卡住」。因此这里只保留 _ 开头的私有字段与普通方法，
      绝不挂任何对象图。
    """

    def __init__(self, service):
        self._svc = service
        self._lock = threading.Lock()

    def drag(self, payload="{}"):
        """前端调用入口：payload 为 JSON 字符串 {paths, effect}。"""
        try:
            data = json.loads(payload) if isinstance(payload, str) else (payload or {})
        except Exception:
            data = {}
        paths = data.get("paths") or []
        effect = data.get("effect") or "copy"
        with self._lock:
            st = self._svc.start(paths, effect)
        return json.dumps(st, ensure_ascii=False)


def find_main_window(pid=None, title=None):
    """按进程 ID（优先）或标题找主窗口。"""
    pid = pid or os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _l):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title and buf.value != title:
            return True
        if user32.GetParent(hwnd):
            return True
        found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0
