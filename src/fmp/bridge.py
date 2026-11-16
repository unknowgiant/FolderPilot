# -*- coding: utf-8 -*-
"""命令路由：唯一入口 call(method, payloadJSON)。

由本地 HTTP 的 POST /api 调用（不再依赖 pywebview 的 js_api 注入）。
所有后端能力通过这里暴露，异常统一转换成 {ok:false,error}，前端不会拿到
半结构化的返回值。加新功能只需在 _routes 增加一项。
"""
from __future__ import annotations

import json
import os
import traceback

from . import clipboard, fs, ops
from .config import APP_ID, APP_TITLE, APP_VERSION, PROJECT_CODE
from .model import FileEntry, entries_to_dict, long_path, norm_path


class Bridge:
    def __init__(self, cfg, search_svc, tasks, drag=None):
        self.cfg = cfg
        self.search = search_svc
        self.tasks = tasks
        self.drag = drag
        self.window = None
        self._routes = {}

    def route(self, name):
        def deco(fn):
            self._routes[name] = fn
            return fn
        return deco

    # ---------- pywebview 暴露的唯一方法 ----------
    def call(self, method, payload="{}"):
        try:
            p = json.loads(payload) if isinstance(payload, str) and payload.strip() else (payload or {})
            fn = self._routes.get(method)
            if not fn:
                return self._ok(False, error=f"未知命令：{method}")
            return json.dumps({"ok": True, "data": fn(p)}, ensure_ascii=False)
        except Exception as ex:
            return json.dumps({"ok": False, "error": f"{type(ex).__name__}: {ex}",
                               "trace": traceback.format_exc(limit=3)}, ensure_ascii=False)

    @staticmethod
    def _ok(ok, **kw):
        return json.dumps({"ok": ok, **kw}, ensure_ascii=False)

    def setup(self):
        R = self.route
        cfg, svc, tasks = self.cfg, self.search, self.tasks

        @R("app.info")
        def _(p):
            return {"name": APP_TITLE, "version": APP_VERSION, "project": PROJECT_CODE,
                    "app_id": APP_ID, "python": os.sys.version.split()[0],
                    "data_dir": cfg.dir, "platform": "windows"}

        @R("state.get")
        def _(p):
            return cfg.get()

        @R("state.set")
        def _(p):
            patch = p.get("patch") if isinstance(p, dict) and "patch" in p else p
            if not isinstance(patch, dict):
                raise ValueError("state.set 需要对象参数")
            return {"saved": True, "state": cfg.patch(patch)}

        # ---------- 目录 ----------
        @R("dir.list")
        def _(p):
            path = norm_path(p.get("path") or "")
            if not path:
                path = os.path.expanduser("~")
            show = bool(p.get("show_hidden", cfg.get("show_hidden")))
            items = fs.list_dir(path, show)
            return {"path": path, "entries": entries_to_dict(items), "count": len(items)}

        @R("dir.drives")
        def _(p):
            return {"drives": fs.drives()}

        @R("dir.special")
        def _(p):
            return {"items": fs.special_paths()}

        @R("dir.exists")
        def _(p):
            path = norm_path(p.get("path") or "")
            return {"exists": os.path.exists(fs.long_path(path)) if path else False,
                    "is_dir": os.path.isdir(fs.long_path(path)) if path else False}

        # ---------- 条目（统一以 path 为身份） ----------
        @R("entry.stat")
        def _(p):
            paths = p.get("paths") or []
            out = []
            for x in paths:
                try:
                    out.append(FileEntry.from_path(x).to_dict())
                except Exception:
                    continue
            return {"entries": out}

        @R("entry.props")
        def _(p):
            return fs.props(p["path"])

        @R("entry.preview")
        def _(p):
            return fs.preview_info(p["path"])

        @R("entry.open")
        def _(p):
            return {"opened": ops.open_path(p["path"])}

        @R("entry.open_parent")
        def _(p):
            return {"opened": ops.open_parent(p["path"])}

        @R("entry.reveal")
        def _(p):
            return {"opened": ops.reveal(p["path"])}

        @R("entry.runas")
        def _(p):
            return {"ok": ops.run_as_admin(p["path"], p.get("args", ""))}

        @R("entry.terminal")
        def _(p):
            return {"ok": ops.open_terminal(p["path"], p.get("kind", "auto"))}

        @R("entry.parent")
        def _(p):
            x = norm_path(p["path"])
            return {"parent": os.path.dirname(x) or x}

        # ---------- 搜索（全局 / 文件夹内同一入口） ----------
        @R("search.run")
        def _(p):
            return svc.run(p)

        @R("search.status")
        def _(p):
            return svc.status(bool(p.get("probe", True)))

        @R("search.connect")
        def _(p):
            return svc.connect()

        # ---------- 内置搜索引擎（随包分发的 Everything 内核） ----------
        @R("engine.status")
        def _(p):
            return svc.engine.status()

        @R("engine.enable")
        def _(p):
            # 首次启用需要一次 UAC（安装 NTFS 索引服务），之后永久静默
            return svc.enable_engine(bool(p.get("interactive", True)))

        @R("engine.stop")
        def _(p):
            return svc.stop_engine()

        # ---------- 操作 ----------
        @R("ops.rename")
        def _(p):
            return {"path": ops.rename(p["path"], p["name"])}

        @R("ops.mkdir")
        def _(p):
            return {"path": ops.make_dir(p["parent"], p.get("name") or "新建文件夹")}

        @R("ops.newtext")
        def _(p):
            return {"path": ops.make_text(p["parent"], p.get("name") or "新建文本文档.txt")}

        @R("ops.trash")
        def _(p):
            return {"ok": ops.trash(p.get("paths") or [])}

        @R("ops.copy")
        def _(p):
            return {"job": tasks.start("copy", p["paths"], p["dest"], False)}

        @R("ops.move")
        def _(p):
            return {"job": tasks.start("move", p["paths"], p["dest"], True)}

        @R("ops.zip")
        def _(p):
            return {"path": ops.zip_files(p["paths"], p["dest"])}

        @R("ops.unzip")
        def _(p):
            return {"path": ops.unzip(p["path"], p["dest"])}

        @R("ops.extract")
        def _(p):
            return {"path": ops.extract_one(p["path"], p["member"], p["dest"])}

        # ---------- 剪贴板 ----------
        @R("clip.write")
        def _(p):
            return {"ok": True, **clipboard.write_files(p["paths"], bool(p.get("move")))}

        @R("clip.check")
        def _(p):
            return {"items": [clipboard.check_access(x) for x in p.get("paths", [])]}

        @R("clip.read")
        def _(p):
            paths, move = clipboard.read_files()
            return {"paths": paths, "move": move}

        @R("clip.text")
        def _(p):
            return {"ok": clipboard.write_text(p.get("text", ""))}

        # ---------- 暂存盘 ----------
        @R("tray.check")
        def _(p):
            """检查暂存盘里的路径是否还在：被删 / 改名 / 移走的项要能标出来。"""
            items = []
            for x in p.get("paths", []):
                items.append({"path": x, "exists": os.path.exists(long_path(x))})
            return {"items": items}

        # ---------- 原生拖放（拖出到资源管理器 / 云盘等外部程序） ----------
        @R("drag.start")
        def _(p):
            if not self.drag:
                raise RuntimeError("拖放服务未初始化")
            return self.drag.start(p.get("paths") or [], p.get("effect") or "copy")

        @R("drag.status")
        def _(p):
            return self.drag.status() if self.drag else {"state": "idle"}

        @R("drag.reset")
        def _(p):
            return {"ok": self.drag.reset() if self.drag else True}

        # ---------- 后台任务 ----------
        @R("task.status")
        def _(p):
            return tasks.status(p.get("id", ""))

        @R("task.cancel")
        def _(p):
            return {"ok": tasks.cancel(p.get("id", ""))}

        # ---------- 标签 / 数据 ----------
        @R("tags.set")
        def _(p):
            tags = dict(cfg.get("tags", {}))
            for path in p.get("paths") or []:
                if p.get("color"):
                    tags[norm_path(path).lower()] = p["color"]
                else:
                    tags.pop(norm_path(path).lower(), None)
            cfg.set("tags", tags)
            return {"tags": tags}

        @R("data.export")
        def _(p):
            return {"path": cfg.export_csv(p.get("name", "history"))}

        # ---------- 窗口 ----------
        @R("app.quit")
        def _(p):
            if self.window:
                try:
                    self.window.destroy()
                except Exception:
                    pass
            return {"ok": True}

        @R("app.minimize")
        def _(p):
            if self.window:
                self.window.minimize()
            return {"ok": True}

        @R("app.maximize")
        def _(p):
            if self.window:
                self.window.toggle_fullscreen()
            return {"ok": True}

        return self
