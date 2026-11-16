# -*- coding: utf-8 -*-
r"""系统剪贴板：CF_HDROP 读写，与资源管理器及第三方客户端双向互通。

要点：
  · 交给外部程序（云盘 / 微信 / WPS 等）的路径必须是「普通 Win32 路径」，
    绝不能带 \\?\ 长路径前缀；也不应带 / 混合分隔符。
  · DROPFILES 头 20 字节，fWide=1 表示后面的路径是 UTF-16LE，双 NUL 结尾。
  · 同时提供 FileNameW 与 Preferred DropEffect，兼容只认这些格式的客户端。
  · 写之前逐个校验路径可读，失败给出明确原因，而不是静默写一个坏路径。
"""
from __future__ import annotations

import ctypes
import os
import struct
import time
from ctypes import wintypes

CF_HDROP = 15
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
DROPEFFECT_COPY, DROPEFFECT_MOVE = 1, 2

# 会让外部客户端读不了的特殊属性（云盘占位 / 重解析点 / 只读等）
UNSAFE_ATTRS = (0x00000001 |  # READONLY
                0x00000400 |  # REPARSE_POINT
                0x00001000 |  # OFFLINE
                0x00040000 |  # RECALL_ON_OPEN
                0x00400000)  # RECALL_ON_DATA_ACCESS


def _fns():
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.CloseClipboard.restype = wintypes.BOOL
    u32.EmptyClipboard.restype = wintypes.BOOL
    u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u32.RegisterClipboardFormatW.restype = wintypes.UINT
    u32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u32.GetClipboardData.restype = wintypes.HGLOBAL
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.SetClipboardData.restype = wintypes.HGLOBAL
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HGLOBAL]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.restype = wintypes.BOOL
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalSize.restype = ctypes.c_size_t
    k32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    k32.GlobalFree.restype = wintypes.HGLOBAL
    k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetFileAttributesW.restype = wintypes.DWORD
    k32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    return u32, k32


def shell_path(p: str) -> str:
    """把内部路径转成外部程序可直接打开的普通 Win32 绝对路径。"""
    if not p:
        raise ValueError("路径为空")
    p = str(p).replace("/", "\\")
    if p.startswith("\\\\?\\UNC\\"):
        p = "\\\\" + p[8:]
    elif p.startswith("\\\\?\\"):
        p = p[4:]
    p = os.path.normpath(p)
    if not os.path.isabs(p):
        p = os.path.abspath(p)
    return p


def long_path(p: str) -> str:
    """仅用于本地 API 调用的长路径形式。"""
    return "\\\\?\\" + p.replace("/", "\\") if not p.startswith("\\\\") else p


def check_access(p: str) -> dict:
    """诊断一个文件对外部程序是否可读：返回路径长度、属性、可读性。"""
    u32, k32 = _fns()
    p = shell_path(p)
    info = {"path": p, "length": len(p), "exists": False, "attrs": 0,
            "unsafe_attrs": [], "readable": False, "error": ""}
    lp = long_path(p)
    info["exists"] = os.path.exists(lp)
    a = k32.GetFileAttributesW(lp)
    if a != 0xFFFFFFFF:
        info["attrs"] = a
        info["unsafe_attrs"] = [n for bit, n in (
            (0x1, "READONLY"), (0x400, "REPARSE_POINT"), (0x1000, "OFFLINE"),
            (0x40000, "RECALL_ON_OPEN"), (0x400000, "RECALL_ON_DATA_ACCESS"))
            if a & bit]
    if not info["exists"]:
        info["error"] = "文件不存在"
        return info
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    h = k32.CreateFileW(lp, GENERIC_READ, 7, None, OPEN_EXISTING, 0x80, None)
    if h == ctypes.c_void_p(-1).value:
        info["error"] = "CreateFileW 打开失败（可能被占用或无权限），错误码 " + str(ctypes.get_last_error())
    else:
        k32.CloseHandle(h)
        info["readable"] = True
    return info


def _set(u32, k32, fmt, blob):
    """分配全局内存并写入剪贴板；失败时释放，成功时所有权交给系统。"""
    h = k32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
    if not h:
        raise RuntimeError("剪贴板内存分配失败")
    p = k32.GlobalLock(h)
    if not p:
        k32.GlobalFree(h)
        raise RuntimeError("剪贴板内存锁定失败")
    ctypes.memmove(p, blob, len(blob))
    k32.GlobalUnlock(h)
    if not u32.SetClipboardData(fmt, h):
        k32.GlobalFree(h)
        raise RuntimeError("写入剪贴板失败（格式 %s）" % fmt)
    return h


def _open(u32, tries=8):
    for _ in range(tries):
        if u32.OpenClipboard(0):
            return True
        time.sleep(0.05)
    raise RuntimeError("剪贴板被其他程序占用，请稍后重试")


def write_files(paths, move=False, verify=True):
    """把文件列表以标准 CF_HDROP 写入系统剪贴板。"""
    u32, k32 = _fns()
    clean = [shell_path(p) for p in paths]
    if not clean:
        raise ValueError("没有可复制的文件")
    if verify:
        for p in clean:
            info = check_access(p)
            if not info["readable"]:
                raise RuntimeError("文件不可读：%s（%s）" %
                                   (os.path.basename(p), info["error"] or "未知原因"))
    payload = "\x00".join(clean) + "\x00\x00"
    blob = struct.pack("IIIii", 20, 0, 0, 0, 1) + payload.encode("utf-16-le")
    _open(u32)
    try:
        u32.EmptyClipboard()
        _set(u32, k32, CF_HDROP, blob)
        # 部分第三方客户端优先读 FileNameW（多文件时给第一项，与资源管理器一致）
        fmt_name = u32.RegisterClipboardFormatW("FileNameW")
        if fmt_name:
            _set(u32, k32, fmt_name, (clean[0] + "\x00").encode("utf-16-le"))
        fmt_effect = u32.RegisterClipboardFormatW("Preferred DropEffect")
        if fmt_effect:
            _set(u32, k32, fmt_effect,
                 struct.pack("I", DROPEFFECT_MOVE if move else DROPEFFECT_COPY))
    finally:
        u32.CloseClipboard()
    return {"count": len(clean), "paths": clean}


def read_files():
    """返回 (paths, is_move)；兼容其它程序写入的 ANSI(fWide=0) DROPFILES。"""
    u32, k32 = _fns()
    if not u32.IsClipboardFormatAvailable(CF_HDROP):
        return [], False
    paths = []
    _open(u32)
    try:
        h = u32.GetClipboardData(CF_HDROP)
        if h:
            p = k32.GlobalLock(h)
            if p:
                buf = ctypes.string_at(p, k32.GlobalSize(h))
                off, _x, _y, _nc, wide = struct.unpack_from("IIIii", buf, 0)
                raw = buf[off:]
                if wide:
                    text = raw.decode("utf-16-le", "replace")
                else:
                    text = raw.decode("mbcs", "replace")
                paths = [shell_path(s) for s in text.split("\x00") if s]
                k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()
    move = False
    fmt = u32.RegisterClipboardFormatW("Preferred DropEffect")
    if fmt and u32.IsClipboardFormatAvailable(fmt):
        _open(u32)
        try:
            hd = u32.GetClipboardData(fmt)
            if hd:
                pd = k32.GlobalLock(hd)
                if pd:
                    move = struct.unpack_from("I", ctypes.string_at(pd, 4), 0)[0] == DROPEFFECT_MOVE
                    k32.GlobalUnlock(hd)
        finally:
            u32.CloseClipboard()
    return paths, move


def write_text(text):
    u32, k32 = _fns()
    data = str(text).encode("utf-16-le") + b"\x00\x00"
    _open(u32)
    try:
        u32.EmptyClipboard()
        _set(u32, k32, CF_UNICODETEXT, data)
    finally:
        u32.CloseClipboard()
    return True
