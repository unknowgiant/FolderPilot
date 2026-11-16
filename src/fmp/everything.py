# -*- coding: utf-8 -*-
"""Everything 集成：SDK 直连（首选）→ HTTP 服务（备用）→ 本地索引（兜底）。

SDK 与 HTTP 都只负责「给出候选绝对路径」，产出的条目一律交给 model.FileEntry
重新 stat，保证路径身份统一。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request
from ctypes import wintypes

from .model import FileEntry, norm_path

FILETIME_UNIX_OFFSET = 11644473600.0

# Everything 客户端的 IPC 窗口类名（SDK 与 ES.exe 都靠它找目标实例）
IPC_WINDOW_CLASS = "EVERYTHING_TASKBAR_NOTIFICATION"
try:
    _u32 = ctypes.windll.user32
    _u32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    _u32.FindWindowW.restype = ctypes.c_void_p
    _FIND_WINDOW = _u32.FindWindowW
except Exception:                                   # 非 Windows 上仅用于导入
    def _FIND_WINDOW(*_a):
        return None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint), ("dwHighDateTime", ctypes.c_uint)]


class EverythingSDK:
    REQ_NAME, REQ_PATH, REQ_SIZE, REQ_DATE_MODIFIED = 0x1, 0x2, 0x10, 0x40

    def __init__(self, assets_dir: str, data_dir: str):
        self.assets_dir = assets_dir
        self.data_dir = data_dir
        self.dll = None
        self.lock = threading.Lock()
        self.last_error = ""
        self.major = self.minor = 0
        self.has_isdir = self.has_isfolder = self.has_attrs = False
        self.busy = False               # 有一次同步 IPC 还没返回

    def _dll_path(self):
        for c in (os.path.join(self.assets_dir, "Everything64.dll"),
                  os.path.join(self.data_dir, "bin", "Everything64.dll")):
            if os.path.isfile(c):
                return c
        src = os.path.join(self.assets_dir, "Everything64.dll")
        if os.path.isfile(src):
            dst = os.path.join(self.data_dir, "bin", "Everything64.dll")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.copyfile(src, dst)
                return dst
            except OSError:
                return src
        # 系统安装目录兜底
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Everything")):
            p = os.path.join(base, "Everything", "Everything64.dll")
            if base and os.path.isfile(p):
                return p
        return None

    def connect(self):
        if self.dll:
            return True
        p = self._dll_path()
        if not p:
            self.last_error = "未找到 Everything64.dll"
            return False
        try:
            d = ctypes.WinDLL(p)
        except OSError as e:
            self.last_error = f"加载 SDK 失败: {e}"
            return False

        def bind(name, argtypes=None, restype=None, optional=False):
            """按需绑定；SDK 各版本导出函数不完全一致，可选函数缺失不算致命。"""
            try:
                fn = getattr(d, name)
            except AttributeError:
                if optional:
                    return False
                raise
            if argtypes is not None:
                fn.argtypes = argtypes
            if restype is not None:
                fn.restype = restype
            return True

        try:
            bind("Everything_SetSearchW", [ctypes.c_wchar_p])
            bind("Everything_SetMatchCase", [ctypes.c_int])
            bind("Everything_SetMatchWholeWord", [ctypes.c_int])
            bind("Everything_SetMax", [ctypes.c_uint])
            bind("Everything_SetRequestFlags", [ctypes.c_uint])
            bind("Everything_QueryW", [ctypes.c_int], ctypes.c_int)
            bind("Everything_GetNumResults", None, ctypes.c_uint)
            bind("Everything_GetResultFileNameW", None, ctypes.c_wchar_p)
            bind("Everything_GetResultPathW", None, ctypes.c_wchar_p)
            bind("Everything_GetResultSize", [ctypes.c_uint, ctypes.POINTER(ctypes.c_ulonglong)])
            bind("Everything_GetResultDateModified", [ctypes.c_uint, ctypes.POINTER(_FILETIME)])
            # 旧 SDK 只有 IsFolderResult；IsDirResult 在部分版本里根本不存在，
            # 之前绑它会让 connect() 直接抛 AttributeError，available() 静默变 False。
            self.has_isdir = bind("Everything_IsDirResult", [ctypes.c_uint], ctypes.c_int, optional=True)
            self.has_isfolder = bind("Everything_IsFolderResult", [ctypes.c_uint], ctypes.c_int, optional=True)
            self.has_attrs = bind("Everything_GetResultAttributes", [ctypes.c_uint], ctypes.c_uint, optional=True)
            bind("Everything_GetLastError", None, ctypes.c_uint)
            bind("Everything_GetMajorVersion", None, ctypes.c_uint, optional=True)
            bind("Everything_GetMinorVersion", None, ctypes.c_uint, optional=True)
        except AttributeError as e:
            self.last_error = f"SDK 接口不匹配: {e}"
            return False
        self.dll = d
        try:
            self.major = d.Everything_GetMajorVersion()
            self.minor = d.Everything_GetMinorVersion()
        except Exception:
            pass
        return True

    @property
    def pinyin_ok(self):
        return (self.major, self.minor) >= (1, 5)

    def version(self):
        return f"{self.major}.{self.minor}" if self.major else "1.x"

    def _ipc_window(self):
        """有没有 Everything 实例的 IPC 窗口 —— 比发一次查询便宜得多。

        Everything 客户端刚启动时窗口已经存在但还没开始处理 IPC，此时同步
        QueryW 会一直等到它响应（实测能卡 20 秒以上）。所以先用这个窗口
        判断「有没有可能应答」，再用受控超时兜住「有窗口但不响应」。
        """
        try:
            return _FIND_WINDOW(IPC_WINDOW_CLASS, None)
        except Exception:
            return None

    def _run_guarded(self, fn, timeout, idle_value):
        """在独立线程里跑同步 IPC，超过 timeout 就当作没就绪返回 idle_value。

        返回 (值, 是否超时)。超时不会杀掉线程（DLL 调用无法中断），但它
        完成后会自己释放 busy 标记；期间新的调用直接按「未就绪」处理，
        避免多个线程堆在同一个锁上。
        """
        if self.busy:
            return idle_value, True
        box = {}
        self.busy = True

        def work():
            try:
                box["v"] = fn()
            except Exception as ex:      # noqa: BLE001 交给调用方判定
                box["e"] = ex
            finally:
                self.busy = False

        t = threading.Thread(target=work, daemon=True, name="fmp-ev-ipc")
        t.start()
        t.join(timeout)
        if t.is_alive():
            return idle_value, True
        if "e" in box:
            raise box["e"]
        return box.get("v"), False

    def available(self, timeout=2.0):
        """Everything 实例是否在应答（有窗口 + 查询真的返回）。"""
        try:
            if not self.connect():
                return False
            if not self._ipc_window():
                return False

            def q():
                with self.lock:
                    self.dll.Everything_SetSearchW("")
                    self.dll.Everything_SetMax(1)
                    self.dll.Everything_SetRequestFlags(self.REQ_NAME)
                    return bool(self.dll.Everything_QueryW(True))

            v, _hung = self._run_guarded(q, timeout, False)
            return bool(v)
        except Exception:
            return False

    def search(self, query: str, limit: int = 500, match_case=False, whole_word=False,
               timeout=6.0):
        """返回 [(绝对路径, is_dir, size, mtime), ...]；卡住的实例不会拖死搜索。"""
        if not self.connect():
            raise RuntimeError(self.last_error or "SDK 不可用")
        if not self._ipc_window():
            raise RuntimeError("没有正在运行的 Everything 实例")

        def q():
            with self.lock:
                d = self.dll
                d.Everything_SetSearchW(query)
                d.Everything_SetMatchCase(1 if match_case else 0)
                d.Everything_SetMatchWholeWord(1 if whole_word else 0)
                d.Everything_SetMax(int(limit))
                d.Everything_SetRequestFlags(self.REQ_NAME | self.REQ_PATH
                                             | self.REQ_SIZE | self.REQ_DATE_MODIFIED)
                if not d.Everything_QueryW(True):
                    err = d.Everything_GetLastError()
                    raise RuntimeError({1: "内存不足", 2: "Everything 未运行"}.get(
                        err, f"查询失败 ({err})"))
                out = []
                n = min(int(d.Everything_GetNumResults()), int(limit))
                for i in range(n):
                    name = d.Everything_GetResultFileNameW(i) or ""
                    folder = d.Everything_GetResultPathW(i) or ""
                    full = os.path.join(folder, name) if folder else name
                    sz = ctypes.c_ulonglong(0)
                    ft = _FILETIME()
                    try:
                        d.Everything_GetResultSize(i, ctypes.byref(sz))
                        d.Everything_GetResultDateModified(i, ctypes.byref(ft))
                    except Exception:
                        pass
                    raw = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
                    mt = raw / 1e7 - FILETIME_UNIX_OFFSET if raw > 10 ** 14 else 0
                    isd = False
                    try:
                        if self.has_isdir:
                            isd = bool(d.Everything_IsDirResult(i))
                        elif self.has_isfolder:
                            isd = bool(d.Everything_IsFolderResult(i))
                        elif self.has_attrs:
                            isd = bool(d.Everything_GetResultAttributes(i) & 0x10)  # FILE_ATTRIBUTE_DIRECTORY
                    except Exception:
                        pass
                    out.append((norm_path(full), isd, int(sz.value), mt))
                return out

        rows, hung = self._run_guarded(q, timeout, None)
        if hung:
            raise RuntimeError("Everything 响应超时")
        return rows


class EverythingHTTP:
    def __init__(self):
        self.base = ""

    def probe(self):
        for port in (8080, 80, 8081):
            u = f"http://127.0.0.1:{port}/?j=1&q=&c=1"
            try:
                with urllib.request.urlopen(u, timeout=0.35) as r:
                    if r.status == 200:
                        self.base = f"http://127.0.0.1:{port}/"
                        return True
            except Exception:
                pass
        return False

    def search(self, query: str, limit: int = 500):
        q = urllib.parse.urlencode({"j": 1, "q": query, "c": 1, "n": limit,
                                   "path_column": 1, "size_column": 1, "date_modified_column": 1})
        with urllib.request.urlopen(self.base + "?" + q, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out = []
        for x in data.get("results", []):
            p = x.get("path", "")
            n = x.get("name", "")
            full = os.path.join(p, n) if p and n else (p or n)
            t = str(x.get("type", "")).lower()
            out.append((norm_path(full), t in ("folder", "directory", "dir"), int(x.get("size") or 0), 0))
        return out


def find_everything_exe():
    import winreg
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\voidtools\Everything"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\voidtools\Everything"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\voidtools\Everything")]
    for h, sub in roots:
        try:
            with winreg.OpenKey(h, sub) as k:
                for name in ("InstallLocation", "ExePath", ""):
                    try:
                        v, _ = winreg.QueryValueEx(k, name)
                        if v:
                            p = v if v.lower().endswith(".exe") else os.path.join(v, "Everything.exe")
                            if os.path.isfile(p):
                                return p
                    except OSError:
                        pass
        except OSError:
            pass
    for p in (os.path.join(os.environ.get("ProgramFiles", ""), "Everything", "Everything.exe"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Everything", "Everything.exe")):
        if os.path.isfile(p):
            return p
    return None
