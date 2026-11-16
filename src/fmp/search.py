# -*- coding: utf-8 -*-
"""统一搜索服务。

唯一入口 run(req)：全局搜索与文件夹内搜索只是 scope 不同，
返回结构完全一致（每条都带绝对 path），前端因此共用一套打开/右键逻辑。
后端优先级：Everything SDK → Everything HTTP → 本地索引。
"""
from __future__ import annotations

import fnmatch
import os
import threading
import time

from .engine import EngineManager
from .everything import EverythingHTTP, EverythingSDK
from .fs import read_text_head, drives
from .model import FileEntry, long_path, norm_path

SKIP_DIRS = {"$recycle.bin", "system volume information", "windows", "programdata",
             "node_modules", ".git", "__pycache__", "appdata", "temp", "cache",
             "site-packages", ".venv", "venv", "dist", "build", "obj",
             "recovery", "perflogs", "msocache", "$windows.~ws"}


class LocalIndex:
    """本地兜底索引（后台构建，只在 Everything 不可用时启用）。"""

    def __init__(self, max_items=250000, max_seconds=50):
        self.max_items = max_items
        self.max_seconds = max_seconds
        self.rows = []                 # (path, name_lower, is_dir, size, mtime)
        self.ready = False
        self.building = False
        self.progress = 0
        self._lock = threading.Lock()
        self._gen = 0
        self._folder_cache = {}

    def build_async(self):
        if self.building or self.ready:
            return
        self.building = True
        threading.Thread(target=self._build, daemon=True, name="fmp-local-index").start()

    def _build(self):
        t0 = time.time()
        rows = []
        roots = []
        for d in drives():
            if d["type"] in ("本地磁盘", "可移动", "网络驱动器"):
                roots.append(d["path"])
        home = os.path.expanduser("~")
        if home.lower() not in [r.lower() for r in roots]:
            roots.insert(0, home)
        for root in roots:
            try:
                for cur, dirs, files in os.walk(long_path(root)):
                    low = cur.lower()
                    dirs[:] = [x for x in dirs if not (x.lower() in SKIP_DIRS or
                               any((low + "\\" + x.lower()).endswith(s) for s in SKIP_DIRS))]
                    for n in files:
                        p = norm_path(os.path.join(cur, n))
                        try:
                            st = os.stat(long_path(p))
                            rows.append((p, n.lower(), False, int(st.st_size), float(st.st_mtime)))
                        except OSError:
                            continue
                    for n in dirs:
                        p = norm_path(os.path.join(cur, n))
                        try:
                            st = os.stat(long_path(p))
                            rows.append((p, n.lower(), True, 0, float(st.st_mtime)))
                        except OSError:
                            pass
                    self.progress = len(rows)
                    if len(rows) >= self.max_items or time.time() - t0 > self.max_seconds:
                        break
            except OSError:
                continue
            if len(rows) >= self.max_items or time.time() - t0 > self.max_seconds:
                break
        with self._lock:
            self.rows = rows
            self.ready = True
            self.building = False

    def snapshot(self):
        with self._lock:
            return list(self.rows)

    def scan_folder(self, root, limit=40000, max_seconds=8, ttl=90):
        """遍历文件夹（支持超长路径）；同目录多次搜索复用 90 秒缓存。"""
        key = root.lower()
        now = time.time()
        cached = self._folder_cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        rows = []
        t0 = time.time()
        try:
            for cur, dirs, files in os.walk(long_path(root)):
                dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS]
                for n in files:
                    p = norm_path(os.path.join(cur, n))
                    try:
                        st = os.stat(long_path(p))
                        rows.append((p, n.lower(), False, int(st.st_size), float(st.st_mtime)))
                    except OSError:
                        continue
                for n in dirs:
                    p = norm_path(os.path.join(cur, n))
                    try:
                        st = os.stat(long_path(p))
                        rows.append((p, n.lower(), True, 0, float(st.st_mtime)))
                    except OSError:
                        pass
                if len(rows) > limit or time.time() - t0 > max_seconds:
                    break
        except OSError:
            pass
        with self._lock:
            self._folder_cache[key] = (now, rows)
        return rows


def _tokens(req):
    q = (req.get("query") or "").strip()
    return [t for t in q.lower().split() if t]


def _match(name_low, path, size, mtime, req, toks):
    for t in toks:
        if "*" in t or "?" in t:
            if not fnmatch.fnmatch(name_low, t) and not fnmatch.fnmatch(path.lower(), "*" + t + "*"):
                return False
        elif t not in name_low and t not in path.lower():
            return False
    ext = (req.get("ext") or "").strip().lower().lstrip(".")
    if ext:
        exts = [x.strip() for x in ext.replace(";", ",").split(",") if x.strip()]
        if exts and not any(name_low.endswith("." + x) for x in exts):
            return False
    try:
        if req.get("size_min") and size < float(req["size_min"]):
            return False
        if req.get("size_max") and size > float(req["size_max"]):
            return False
        if req.get("date_from") and mtime and mtime < float(req["date_from"]):
            return False
        if req.get("date_to") and mtime and mtime > float(req["date_to"]):
            return False
    except (TypeError, ValueError):
        pass
    if req.get("content") and toks:
        try:
            txt = read_text_head(path, 256 * 1024).lower()
            if not all(t in txt for t in toks):
                return False
        except Exception:
            return False
    return True


class SearchService:
    def __init__(self, cfg, assets_dir, data_dir):
        self.cfg = cfg
        self.sdk = EverythingSDK(assets_dir, data_dir)
        self.http = EverythingHTTP()
        self.local = LocalIndex()
        # 内置引擎：随包分发的 Everything 内核（无需用户单独安装）
        self.engine = EngineManager(assets_dir, data_dir, self.sdk)
        self._lock = threading.Lock()
        self._gen = 0
        self.last_backend = "未检测"
        self.note = ""

    def status(self, probe=True):
        sdk = self.sdk.available() if probe else bool(self.sdk.dll)
        http = self.http.probe() if probe else bool(self.http.base)
        eng = self.engine.status()
        label = eng["label"] if sdk else ("Everything HTTP" if http else "本地索引")
        return {"sdk": sdk, "http": http, "pinyin": self.sdk.pinyin_ok,
                "version": self.sdk.version(), "backend": label, "engine": eng,
                "source": eng["source"], "needs_auth": eng["needs_auth"],
                "index_ready": self.local.ready, "index_building": self.local.building,
                "index_count": self.local.progress,
                "last_error": self.sdk.last_error or eng["last_error"]}

    def connect(self, prefer_bundled=False, wait=8.0):
        """确保有一个可用的搜索内核：外部 Everything → 内置引擎 → 本地索引。"""
        try:
            self.engine.ensure(wait=wait, prefer_bundled=bool(prefer_bundled))
        except Exception:
            pass
        return self.status()

    def enable_engine(self, interactive=True):
        """一次性授权并启动内置引擎（界面上的「启用全盘秒搜」）。"""
        self.engine.enable(interactive=bool(interactive))
        return self.status()

    def stop_engine(self):
        self.engine.stop()
        return self.status()

    def build_query(self, req):
        toks = _tokens(req)
        parts = []
        q = (req.get("query") or "").strip()
        if q:
            if req.get("pinyin"):
                parts.append("pinyin:" + q)
            elif req.get("content"):
                parts.append('content:"' + q + '"')
            else:
                parts.append(q)
        if req.get("case"):
            parts.append("case:")
        if req.get("whole_word"):
            parts.append("wholeword:")
        ext = (req.get("ext") or "").strip()
        if ext:
            parts.append("ext:" + ext.replace(",", ";"))
        if req.get("scope") == "folder" and req.get("root"):
            parts.append('path:"' + norm_path(req["root"]) + '"')
        if req.get("size_min"):
            parts.append("size:>" + str(req["size_min"]))
        if req.get("size_max"):
            parts.append("size:<" + str(req["size_max"]))
        if req.get("dm"):
            parts.append("dm:" + str(req["dm"]))
        return " ".join(parts)

    def run(self, req):
        t0 = time.time()
        with self._lock:
            self._gen += 1
            gen = self._gen
        limit = max(10, min(int(req.get("limit") or 500), 3000))
        root = norm_path(req.get("root") or "")
        scope = req.get("scope") or "global"
        toks = _tokens(req)
        query = self.build_query(req)
        raw = []
        backend = ""
        note = ""
        if query.strip():
            try:
                if self.sdk.available():
                    raw = self.sdk.search(query, limit, req.get("case", False), req.get("whole_word", False))
                    backend = self.engine.running_label()
                elif self.http.probe() or self.http.base:
                    raw = self.http.search(query, limit)
                    backend = "Everything HTTP"
            except Exception as ex:
                note = str(ex)
                raw = []
        if not backend and (toks or req.get("ext") or req.get("content")):
            backend = "本地索引"
            if scope == "folder" and root and os.path.isdir(root):
                rows = self.local.scan_folder(root)
            else:
                self.local.build_async()
                rows = self.local.snapshot()
                if not self.local.ready:
                    note = ("本地索引构建中，结果可能不完整；"
                            "可点状态栏「本地索引」启用内置全盘引擎获得秒搜")
            for p, nl, isd, sz, mt in rows:
                if len(raw) >= limit:
                    break
                if scope == "folder" and root and not p.lower().startswith(root.lower() + "\\") and p.lower() != root.lower():
                    continue
                if _match(nl, p, sz, mt, req, toks):
                    raw.append((p, isd, sz, mt))
            raw = raw[:limit]
        elif not backend:
            backend = "待输入"
        # 内核刚启动、索引还在建时，先给一句人话，避免用户以为搜索坏了
        if not note and self.engine.warming():
            note = "内置引擎正在建立首次索引（通常 10–30 秒），完成前结果可能不完整"
        self.last_backend = backend
        # 统一构造 FileEntry —— path 是唯一身份
        entries = []
        for item in raw[:limit]:
            p, isd, sz, mt = item
            p = norm_path(p)
            if scope == "folder" and root and not (p.lower() == root.lower() or p.lower().startswith(root.lower() + "\\")):
                continue
            rel = ""
            if scope == "folder" and root and (
                    p.lower() == root.lower() or p.lower().startswith(root.lower() + "\\")):
                rel = p[len(root):].lstrip("\\") or (os.path.basename(p) or p)
            # 搜索后端已给出 size/mtime，直接构造 FileEntry，避免对每条结果再 stat
            e = FileEntry(path=p, name=os.path.basename(p) or p, is_dir=isd,
                          size=0 if isd else int(sz or 0), mtime=float(mt or 0),
                          rel=rel, source=backend)
            entries.append(e.to_dict())
        if scope == "folder" and root:
            entries.sort(key=lambda x: (not x["is_dir"], -(x["mtime"] or 0), x["name"].lower()))
        self.note = note
        return {"entries": entries, "backend": backend, "elapsed": int((time.time() - t0) * 1000),
                "total": len(entries), "note": note, "query": query,
                "scope": scope, "root": root, "gen": gen,
                "index_ready": self.local.ready, "index_count": self.local.progress}
