# -*- coding: utf-8 -*-
"""内置搜索引擎：把 Everything 内核随程序一起分发，用户无需单独安装 Everything。

为什么不是「只放一个 DLL」：Everything 的客户端 SDK 只是一个 IPC 客户端，
真正建索引的是 Everything.exe（读 NTFS 的 MFT / 监听 USN 日志）。所以内置
需要三件套：Everything.exe + Everything64.dll + 一份私有配置。

为什么要一次性授权：读 NTFS 的 MFT 必须管理员权限。Everything 的标准解法
是装一个约 1MB 常驻服务（Everything.exe -svc，随系统启动），客户端就能以
普通用户身份索引。本模块在「系统里没有该服务、当前进程又没提权」时不会偷偷
启动内核（那会弹出一个没人看得懂的 UAC），而是把状态标成 needs_auth，由界面
上的「启用全盘秒搜」按钮触发一次显式授权。

三级来源，优先级从高到低：
  1. 用户自己装过 Everything（注册表 / 常见安装路径）→ 直接复用，不碰它的配置
  2. 随包分发的内核 → 部署到 %APPDATA%\\FileManagerMulti\\v1\\engine 后启动
  3. 本地索引 LocalIndex（纯 os.walk，无需任何权限）→ 兜底

内核进程只在管理器运行时存在：退出时只结束「我们自己启动的」那一个，用户
自己开的 Everything 不受影响。
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import threading
import time
from ctypes import wintypes

from .everything import find_everything_exe

CREATE_NO_WINDOW = 0x08000000
SERVICE_NAME = "Everything"
ENGINE_DIRNAME = "engine"
MARKER = "engine_service.json"

# 私有配置（放在内核同目录，app_data=0 即「便携模式」，不干扰用户自己的
# %APPDATA%\Everything）。show_tray_icon=0：引擎完全隐形，不占托盘。
BOOT_INI = """[Everything]
app_data=0
run_as_admin=0
show_tray_icon=0
minimize_to_tray=1
run_in_background=1
allow_multiple_instances=0
check_for_updates_on_startup=0
http_server_enabled=0
etp_server_enabled=0
db_location=
"""

SC_MANAGER_CONNECT = 0x0001
SERVICE_QUERY_STATUS = 0x0004
SERVICE_QUERY_CONFIG = 0x0001
SERVICE_STATUS_RUNNING = 4
SERVICE_STATUS_STOPPED = 1


class _SERVICE_STATUS(ctypes.Structure):
    _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
                ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
                ("dwServiceSpecificExitCode", wintypes.DWORD),
                ("dwCheckPoint", wintypes.DWORD), ("dwWaitHint", wintypes.DWORD)]


class _QUERY_SERVICE_CONFIG(ctypes.Structure):
    _fields_ = [("dwServiceType", wintypes.DWORD), ("dwStartType", wintypes.DWORD),
                ("dwErrorControl", wintypes.DWORD), ("lpBinaryPathName", wintypes.LPWSTR),
                ("lpLoadOrderGroup", wintypes.LPWSTR), ("dwTagId", wintypes.DWORD),
                ("lpDependencies", wintypes.LPWSTR), ("lpServiceStartName", wintypes.LPWSTR),
                ("lpDisplayName", wintypes.LPWSTR)]


def _advapi():
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    a.OpenSCManagerW.restype = wintypes.HANDLE
    a.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    a.OpenServiceW.restype = wintypes.HANDLE
    a.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(_SERVICE_STATUS)]
    a.QueryServiceStatus.restype = wintypes.BOOL
    a.QueryServiceConfigW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    a.QueryServiceConfigW.restype = wintypes.BOOL
    a.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    a.CloseServiceHandle.restype = wintypes.BOOL
    return a


def _open_service():
    """返回 (scm, svc)；服务不存在时两者都是 None。标准用户也能查询。"""
    a = _advapi()
    scm = a.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not scm:
        return None, None
    svc = a.OpenServiceW(scm, SERVICE_NAME, SERVICE_QUERY_STATUS | SERVICE_QUERY_CONFIG)
    if not svc:
        a.CloseServiceHandle(scm)
        return None, None
    return scm, svc


def service_state() -> str:
    """"running" / "stopped" / "absent" / "unknown"（查询失败）。"""
    try:
        scm, svc = _open_service()
        if not scm:
            return "unknown"
        if not svc:
            return "absent"
        try:
            st = _SERVICE_STATUS()
            if not _advapi().QueryServiceStatus(svc, ctypes.byref(st)):
                return "unknown"
            if st.dwCurrentState == SERVICE_STATUS_RUNNING:
                return "running"
            return "stopped" if st.dwCurrentState == SERVICE_STATUS_STOPPED else "unknown"
        finally:
            _advapi().CloseServiceHandle(svc)
            _advapi().CloseServiceHandle(scm)
    except Exception:
        return "unknown"


def service_image_path() -> str:
    """服务实际执行的命令行（判断这个服务是不是我们装的）。"""
    try:
        scm, svc = _open_service()
        if not scm or not svc:
            return ""
        try:
            buf = ctypes.create_string_buffer(8192)
            need = wintypes.DWORD(0)
            if not _advapi().QueryServiceConfigW(svc, buf, len(buf), ctypes.byref(need)):
                return ""
            cfg = ctypes.cast(buf, ctypes.POINTER(_QUERY_SERVICE_CONFIG)).contents
            return cfg.lpBinaryPathName or ""
        finally:
            _advapi().CloseServiceHandle(svc)
            _advapi().CloseServiceHandle(scm)
    except Exception:
        return ""


def is_elevated() -> bool:
    try:
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.HANDLE)]
        a.OpenProcessToken.restype = wintypes.BOOL
        a.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        a.GetTokenInformation.restype = wintypes.BOOL
        k.GetCurrentProcess.restype = wintypes.HANDLE
        tok = wintypes.HANDLE()
        if not a.OpenProcessToken(k.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):
            return False
        try:
            # TOKEN_ELEVATION = 20 → DWORD
            val = wintypes.DWORD(0)
            got = wintypes.DWORD(0)
            if not a.GetTokenInformation(tok, 20, ctypes.byref(val),
                                        ctypes.sizeof(val), ctypes.byref(got)):
                return False
            return bool(val.value)
        finally:
            k.CloseHandle(tok)
    except Exception:
        return False


def shell_runas(exe: str, args: str, cwd: str) -> tuple[bool, str]:
    """以管理员身份运行（会弹一次 UAC）。返回 (是否已启动, 说明)。"""
    try:
        sh = ctypes.WinDLL("shell32", use_last_error=True)
        sh.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
        sh.ShellExecuteW.restype = ctypes.c_void_p
        rc = sh.ShellExecuteW(None, "runas", exe, args, cwd, 0)
        if rc and int(rc) > 32:
            return True, ""
        if int(rc or 0) == 5:
            return False, "已取消管理员授权"
        return False, f"启动授权进程失败（{rc}）"
    except Exception as ex:
        return False, f"启动授权进程失败：{ex}"


class EngineManager:
    def __init__(self, assets_dir: str, data_dir: str, sdk=None):
        self.assets_dir = assets_dir
        self.data_dir = data_dir
        self.sdk = sdk
        self.dir = os.path.join(data_dir, ENGINE_DIRNAME)
        self.exe = os.path.join(self.dir, "Everything.exe")
        self.ini = os.path.join(self.dir, "Everything.ini")
        self.dll = os.path.join(self.dir, "Everything64.dll")
        self._proc = None
        self._bundled = False           # True 表示 _proc 是我们自己的内核
        self._lock = threading.Lock()
        self.state = "unknown"          # external / bundled / needs_auth / missing / local
        self.last_error = ""
        self.started_at = 0.0

    # ---------- 部署 ----------
    def deploy(self) -> str:
        """把安装包里的内核释放到数据目录；返回 exe 路径，缺文件返回空串。"""
        src_exe = os.path.join(self.assets_dir, ENGINE_DIRNAME, "Everything.exe")
        if not os.path.isfile(src_exe):
            self.last_error = "安装包内缺少内置搜索引擎内核"
            return ""
        try:
            os.makedirs(self.dir, exist_ok=True)
            if self._need_copy(src_exe, self.exe):
                # 正在运行时无法覆盖，先结束我们自己启动的实例
                self.stop()
                shutil.copyfile(src_exe, self.exe)
            for name in ("Everything64.dll",):
                s = os.path.join(self.assets_dir, ENGINE_DIRNAME, name)
                if os.path.isfile(s) and self._need_copy(s, os.path.join(self.dir, name)):
                    shutil.copyfile(s, os.path.join(self.dir, name))
            # 许可证要跟内核放在一起（Everything 为 MIT 许可，允许随包分发）
            lic = os.path.join(self.assets_dir, ENGINE_DIRNAME, "Everything-License.txt")
            if os.path.isfile(lic) and self._need_copy(lic, os.path.join(self.dir, "Everything-License.txt")):
                try:
                    shutil.copyfile(lic, os.path.join(self.dir, "Everything-License.txt"))
                except OSError:
                    pass
            if not os.path.isfile(self.ini):
                with open(self.ini, "w", encoding="utf-8") as f:
                    f.write(BOOT_INI)
            return self.exe if os.path.isfile(self.exe) else ""
        except OSError as ex:
            self.last_error = f"释放内置搜索引擎失败：{ex}"
            return ""

    @staticmethod
    def _need_copy(src, dst) -> bool:
        try:
            if not os.path.isfile(dst):
                return True
            a, b = os.stat(src), os.stat(dst)
            return a.st_size != b.st_size or abs(a.st_mtime - b.st_mtime) > 1
        except OSError:
            return True

    # ---------- 运行 ----------
    def _launch(self, exe: str, cwd: str, bundled: bool):
        args = [exe, "-startup"]
        if bundled:
            args[1:1] = ["-config", self.ini]
        self._proc = subprocess.Popen(args, cwd=cwd, close_fds=True,
                                      creationflags=CREATE_NO_WINDOW,
                                      stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        self.started_at = time.time()
        self._bundled = bool(bundled)
        self.state = "bundled" if bundled else "external"

    def _wait_ready(self, seconds=8.0) -> bool:
        """等实例能应答；每次探测都带超时，别被启动期的 IPC 拖住。"""
        t0 = time.time()
        while time.time() - t0 < seconds:
            if self.sdk and self.sdk.available(timeout=0.9):
                return True
            time.sleep(0.5)
        return False

    def ensure(self, wait=8.0, prefer_bundled=False) -> dict:
        """确保有一个能应答 SDK 的实例；返回状态。不弹 UAC。"""
        st = self.status()
        if st["sdk"]:
            return st
        if st["needs_auth"]:
            self.state = "needs_auth"
            return self.status()
        with self._lock:
            if self.sdk and self.sdk.available():
                return self.status()
            # 上一轮已经把内核拉起来了（只是还在读 MFT 建索引）→ 只等，别再起一个。
            # 否则第二个进程会被单实例机制弹回，_proc 指向那个空壳，
            # 状态就会误报成「复用外部 Everything」。
            if self._proc and self._proc.poll() is None:
                self._wait_ready(wait)
                return self.status()
            # 1) 用户自己装的 Everything 优先，绝不碰它的配置。
            #    冷启动要读全盘 MFT，实测 5–6 秒才应答，所以给足 12 秒，
            #    期间不要抢着起内置内核（同一个默认实例，抢也只会立刻退出）。
            ext = None if prefer_bundled else find_everything_exe()
            if ext:
                launched = True
                try:
                    self._launch(ext, os.path.dirname(ext), bundled=False)
                except OSError as ex:
                    launched = False
                    self.last_error = f"启动 Everything 失败：{ex}"
                if self._wait_ready(max(wait, 12.0)):
                    return self.status()
                if launched:
                    # 还活着就说明只是在预热，交给界面稍后重连即可
                    self.state = "external"
                    return self.status()
            # 2) 随包内核
            exe = self.deploy()
            if not exe:
                self.state = "missing"
                return self.status()
            # 没装服务又没提权时，Everything 自己会弹一个 UAC；不替用户决定，
            # 交给界面上的「启用全盘秒搜」显式授权。
            if service_state() != "running" and not is_elevated():
                self.state = "needs_auth"
                self.last_error = "内置搜索引擎需要一次管理员授权（安装索引服务）"
                return self.status()
            try:
                self._launch(exe, self.dir, bundled=True)
            except OSError as ex:
                self.last_error = f"启动内置引擎失败：{ex}"
                self.state = "missing"
                return self.status()
            self._wait_ready(wait)
        return self.status()

    def enable(self, interactive=True) -> dict:
        """一次性授权：安装（或复用）索引服务，然后启动内置引擎。"""
        exe = self.deploy()
        if not exe:
            return self.status()
        state = service_state()
        if state != "running":
            if is_elevated():
                try:
                    subprocess.run([exe, "-install-service"], cwd=self.dir, timeout=90,
                                   creationflags=CREATE_NO_WINDOW,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as ex:
                    self.last_error = f"安装索引服务失败：{ex}"
            elif interactive:
                ok, msg = shell_runas(exe, "-install-service", self.dir)
                if not ok:
                    self.last_error = msg
                    return self.status()
                self._write_marker()
            else:
                self.last_error = "需要管理员授权才能安装索引服务"
                return self.status()
            self._wait_service(60)
        self.state = "bundled"
        self.ensure(wait=10.0)
        return self.status()

    def _wait_service(self, seconds=60) -> bool:
        t0 = time.time()
        while time.time() - t0 < seconds:
            if service_state() == "running":
                return True
            time.sleep(0.5)
        return False

    def _write_marker(self):
        try:
            with open(os.path.join(self.data_dir, MARKER), "w", encoding="utf-8") as f:
                json.dump({"service": SERVICE_NAME, "exe": self.exe,
                           "installed_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def marker(self) -> dict:
        try:
            with open(os.path.join(self.data_dir, MARKER), encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def remove_service_if_ours(self) -> bool:
        """卸载时清理：只删「指向我们内核目录」的那个服务，别人的不动。"""
        img = service_image_path()
        if not img or os.path.normcase(self.dir) not in os.path.normcase(img):
            return False
        exe = self.exe if os.path.isfile(self.exe) else ""
        if not exe:
            return False
        try:
            self.stop()
            if is_elevated():
                subprocess.run([exe, "-uninstall-service"], cwd=self.dir, timeout=60,
                               creationflags=CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            ok, _ = shell_runas(exe, "-uninstall-service", self.dir)
            return ok
        except Exception:
            return False

    def stop(self):
        """只结束我们自己启动的内核进程；用户自己开的 Everything 不动。

        _launch(ext, bundled=False) 也会记下 _proc（那是用户的 Everything），
        退出时绝不能顺手把它关掉 —— 只有 _bundled 为真才 terminate。
        """
        p = self._proc
        bundled = self._bundled
        self._proc = None
        self._bundled = False
        if not p or not bundled:
            return
        try:
            if p.poll() is None:
                p.terminate()
                for _ in range(20):
                    if p.poll() is not None:
                        break
                    time.sleep(0.1)
                if p.poll() is None:
                    p.kill()
        except Exception:
            pass

    # ---------- 状态 ----------
    def owns_running(self) -> bool:
        """当前应答的实例是不是「我们自己启动的内核」。"""
        try:
            return bool(self._bundled and self._proc and self._proc.poll() is None)
        except Exception:
            return False

    def running_label(self) -> str:
        """便宜版后端名（每次搜索都要用，不查注册表/服务）。"""
        return "内置引擎" if self.owns_running() else "Everything SDK"

    def warming(self) -> bool:
        """内核刚起来、索引还在建立（MFT 首次读取通常 3–15 秒）。"""
        try:
            return bool(self.owns_running() and time.time() - self.started_at < 60)
        except Exception:
            return False

    def status(self) -> dict:
        deployed = os.path.isfile(self.exe)
        ext = find_everything_exe()
        sdk_ok = bool(self.sdk and self.sdk.available())
        svc = service_state()
        elevated = is_elevated()
        st = {
            "deployed": deployed, "exe": self.exe if deployed else "",
            "dir": self.dir, "external": ext or "", "service": svc,
            "elevated": elevated, "sdk": sdk_ok,
            "running": sdk_ok, "source": self.state,
            "needs_auth": bool(deployed and not ext and not sdk_ok
                               and svc != "running" and not elevated),
            "version": "", "last_error": self.last_error,
            "warming": self.warming(),
        }
        if sdk_ok:
            st["source"] = "bundled" if self.owns_running() else "external"
            st["needs_auth"] = False
            st["version"] = self.sdk.version()
        st["service_ours"] = bool(svc != "absent" and deployed and
                                  self.dir.lower() in (service_image_path() or "").lower())
        st["label"] = {"bundled": "内置引擎", "external": "Everything SDK"}.get(
            st["source"], "本地索引")
        return st
