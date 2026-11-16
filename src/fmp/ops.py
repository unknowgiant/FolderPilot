# -*- coding: utf-8 -*-
"""文件操作服务 + 后台任务进度。"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from ctypes import wintypes

from .model import long_path, norm_path


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint),
                ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]


def trash(paths):
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3  # FO_DELETE
    op.pFrom = "\x00".join([norm_path(p) for p in paths]) + "\x00\x00"
    op.pTo = None
    op.fFlags = 0x40 | 0x10 | 0x4 | 0x400  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise RuntimeError(f"移入回收站失败 (code {rc})")
    return True


def unique_dest(dst):
    if not os.path.exists(long_path(dst)):
        return dst
    base, ext = os.path.splitext(dst)
    for i in range(2, 1000):
        cand = f"{base} - 副本{i if i > 2 else ''}{ext}" if i == 2 else f"{base} - 副本{i}{ext}"
        if not os.path.exists(long_path(cand)):
            return cand
    return f"{base}-{uuid.uuid4().hex[:6]}{ext}"


def open_path(path):
    p = norm_path(path)
    if not os.path.exists(long_path(p)):
        raise FileNotFoundError(f"路径不存在：{p}")
    os.startfile(p)
    return True


def reveal(path):
    p = norm_path(path)
    subprocess.Popen(["explorer", "/select,", p], close_fds=True)
    return True


def open_parent(path):
    p = norm_path(path)
    target = os.path.dirname(p) if not os.path.isdir(long_path(p)) else os.path.dirname(p.rstrip("\\"))
    if not target:
        target = p
    os.startfile(target)
    return True


def rename(path, new_name):
    p = norm_path(path)
    if not new_name or any(c in new_name for c in '\\/:*?"<>|'):
        raise ValueError("名称不合法")
    dst = os.path.join(os.path.dirname(p), new_name)
    if os.path.exists(long_path(dst)) and dst.lower() != p.lower():
        raise FileExistsError("同名文件已存在")
    os.rename(long_path(p), long_path(dst))
    return norm_path(dst)


def make_dir(parent, name="新建文件夹"):
    parent = norm_path(parent)
    dst = unique_dest(os.path.join(parent, name))
    os.makedirs(long_path(dst))
    return norm_path(dst)


def make_text(parent, name="新建文本文档.txt"):
    parent = norm_path(parent)
    if not name.endswith(".txt"):
        name += ".txt"
    dst = unique_dest(os.path.join(parent, name))
    with open(long_path(dst), "w", encoding="utf-8") as f:
        f.write("")
    return norm_path(dst)


def run_as_admin(path, args=""):
    p = norm_path(path)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", p, args or None,
                                             os.path.dirname(p) or None, 1)
    if int(rc) <= 32:
        raise RuntimeError(f"提权启动失败 (code {rc})")
    return True


def open_terminal(path, kind="auto"):
    p = norm_path(path)
    if not os.path.isdir(long_path(p)):
        p = os.path.dirname(p)
    if kind in ("wt", "auto"):
        try:
            subprocess.Popen(["wt", "-d", p], close_fds=True, creationflags=0x00000008)
            return True
        except OSError:
            pass
    exe = "powershell.exe" if kind == "powershell" else "cmd.exe"
    subprocess.Popen([exe], cwd=p, close_fds=True, creationflags=0x00000010)
    return True


def zip_files(paths, dest):
    dest = norm_path(dest)
    with zipfile.ZipFile(long_path(dest), "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            p = norm_path(p)
            if os.path.isdir(long_path(p)):
                for root, _, files in os.walk(long_path(p)):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, long_path(os.path.dirname(p))))
            elif os.path.isfile(long_path(p)):
                z.write(long_path(p), os.path.basename(p))
    return dest


def unzip(path, dest):
    path, dest = norm_path(path), norm_path(dest)
    os.makedirs(long_path(dest), exist_ok=True)
    with zipfile.ZipFile(long_path(path)) as z:
        z.extractall(long_path(dest))
    return dest


def extract_one(path, member, dest):
    with zipfile.ZipFile(long_path(norm_path(path))) as z:
        target = os.path.join(norm_path(dest), os.path.basename(member))
        with z.open(member) as src, open(long_path(target), "wb") as out:
            shutil.copyfileobj(src, out)
    return norm_path(target)


class TaskManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def start(self, kind, paths, dest, move=False):
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "kind": kind, "done": 0, "total": len(paths), "current": "",
               "state": "running", "error": "", "started": time.time(), "cancel": False,
               "dest": norm_path(dest)}
        with self.lock:
            self.jobs[jid] = job
        threading.Thread(target=self._run, args=(job, paths, move), daemon=True,
                         name="fmp-task-" + jid).start()
        return jid

    def _run(self, job, paths, move):
        dest = job["dest"]
        try:
            for p in paths:
                if job["cancel"]:
                    job["state"] = "cancelled"
                    return
                p = norm_path(p)
                job["current"] = os.path.basename(p) or p
                if not os.path.exists(long_path(p)):
                    continue
                target = unique_dest(os.path.join(dest, os.path.basename(p.rstrip("\\")) or p))
                if job["kind"] == "zip":
                    continue
                try:
                    if os.path.isdir(long_path(p)):
                        if move:
                            shutil.move(long_path(p), long_path(target))
                        else:
                            shutil.copytree(long_path(p), long_path(target))
                    else:
                        if move:
                            shutil.move(long_path(p), long_path(target))
                        else:
                            shutil.copy2(long_path(p), long_path(target))
                except (OSError, shutil.Error) as ex:
                    job["error"] = str(ex)
                job["done"] += 1
            job["state"] = "done" if not job["error"] else "error"
        except Exception as ex:
            job["state"] = "error"
            job["error"] = str(ex)
        job["current"] = ""

    def status(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            return dict(j) if j else {"state": "missing"}

    def cancel(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if j:
                j["cancel"] = True
        return True
