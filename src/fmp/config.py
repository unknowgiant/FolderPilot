# -*- coding: utf-8 -*-
"""配置与会话持久化：原子写入，绝不因崩溃写坏配置。"""
from __future__ import annotations

import json
import os
import threading

from .version import (APP_ID, APP_TITLE, APP_VERSION, PROJECT_CODE,  # noqa: F401
                      DATA_DIR_DISPLAY)

DEFAULTS = {
    "theme": "light",              # light | dark | system
    # 皮肤 key 见 ui/js/skins.js（由 tools/gen_skins.py 生成）：
    # default | yunhai xinghe hupan mose zhuying qinghua hongri chicheng yaodong shishi
    "skin": "default",
    "skin_wallpaper": True,        # 皮肤壁纸；关掉只留配色
    "skin_opacity": 100,           # 壁纸层不透明度（0-100）：只降这一层，图不会被洗白
    "density": "comfortable",      # comfortable | compact
    "layout": 2,                   # 1..5 窗格数
    "sidebar_width": 208,
    "show_hidden": False,
    "show_ext": True,
    "confirm_delete": True,
    "hover_preview": True,
    "ev_max": 500,
    "ev_autostart": True,
    # name=0 表示名称列自动填满剩余宽度；pane_ratio 为左右分屏左栏占比
    "colw": {"name": 0, "size": 96, "mtime": 146, "type": 108, "parent": 220},
    "pane_ratio": 50,
    "name_only": False,            # 一键隐藏其他列，名称占满整栏
    "name_wrap": False,            # 长名称两行显示
    "favorites": [],
    "tags": {},                    # path.lower() -> color index
    "tray": [],                    # 暂存盘，存绝对路径
    "history": [],                 # 搜索历史
    "session": None,               # {panes:[{tabs:[...],active}],active_pane,layout}
    "folder_memory": {},           # path.lower() -> {view, sort}
    "last_paths": [],
}

_lock = threading.Lock()


class Config:
    def __init__(self, data_dir: str):
        self.dir = data_dir
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "config.json")
        self.data = dict(DEFAULTS)
        existed = os.path.isfile(self.path)
        self.load()
        if not existed:
            self._flush()   # 首次启动即落盘，避免「配置目录为空」

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    self.data[k] = v
        except Exception:
            pass
        # 补齐新增字段
        for k, v in DEFAULTS.items():
            self.data.setdefault(k, v)
        return self.data

    def get(self, key: str = None, default=None):
        if key is None:
            return dict(self.data)
        return self.data.get(key, default)

    def set(self, key: str, value):
        with _lock:
            self.data[key] = value
            self._flush()

    def patch(self, patch: dict):
        with _lock:
            self.data.update(patch or {})
            self._flush()
        return self.data

    def _flush(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def export_csv(self, name: str) -> str:
        import csv
        out = os.path.join(self.dir, "exports")
        os.makedirs(out, exist_ok=True)
        p = os.path.join(out, name + ".csv")
        rows = []
        if name == "tags":
            rows = [("路径", "颜色")] + list(self.data.get("tags", {}).items())
        elif name == "favorites":
            rows = [("路径",)] + [(x,) for x in self.data.get("favorites", [])]
        elif name == "tray":
            rows = [("路径",)] + [(x,) for x in self.data.get("tray", [])]
        elif name == "history":
            rows = [("关键字",)] + [(x,) for x in self.data.get("history", [])]
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        return p
