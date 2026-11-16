# -*- coding: utf-8 -*-
"""统一领域模型。

架构约定（1.0 起强制）：
  * 任何出现在列表里的条目都是 FileEntry；
  * `path` 是**绝对路径**，是条目的唯一身份，绝不用「当前目录 + 名称」二次拼装；
  * `name` 只用于显示，`rel` 只用于搜索结果的副标题；
  * 目录列表 / 全盘搜索 / 文件夹内搜索 / 暂存盘 / 剪贴板，全部产出同一种结构。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

EXT_KIND = {
    "txt": "文本文档", "md": "Markdown", "log": "日志", "ini": "配置", "json": "JSON",
    "xml": "XML", "csv": "CSV", "py": "Python", "js": "JavaScript", "ts": "TypeScript",
    "html": "网页", "htm": "网页", "css": "样式表", "bat": "批处理", "cmd": "批处理",
    "ps1": "PowerShell", "sh": "Shell 脚本", "sql": "SQL", "yaml": "YAML", "yml": "YAML",
    "png": "图片", "jpg": "图片", "jpeg": "图片", "gif": "图片", "bmp": "图片",
    "webp": "图片", "svg": "图片", "ico": "图标", "tif": "图片", "tiff": "图片",
    "psd": "Photoshop", "dwg": "CAD 图纸", "dxf": "CAD 图纸", "vsdx": "Visio",
    "pdf": "PDF 文档", "doc": "Word 文档", "docx": "Word 文档", "xls": "Excel",
    "xlsx": "Excel", "ppt": "PowerPoint", "pptx": "PowerPoint", "wps": "WPS 文档",
    "zip": "压缩文件", "rar": "压缩文件", "7z": "压缩文件", "tar": "压缩文件", "gz": "压缩文件",
    "mp4": "视频", "mkv": "视频", "avi": "视频", "mov": "视频", "wmv": "视频",
    "mp3": "音频", "wav": "音频", "flac": "音频", "aac": "音频", "m4a": "音频",
    "exe": "应用程序", "msi": "安装包", "dll": "动态链接库", "lnk": "快捷方式",
}

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "ico", "avif"}
TEXT_EXT = {"txt", "md", "log", "ini", "json", "xml", "csv", "py", "js", "ts", "html",
            "htm", "css", "bat", "cmd", "ps1", "sh", "sql", "yaml", "yml", "properties",
            "toml", "c", "cpp", "h", "java", "go", "rs", "vue", "jsx", "tsx", "reg"}
ARCHIVE_EXT = {"zip", "rar", "7z", "tar", "gz"}


def long_path(p: str) -> str:
    """Windows 长路径前缀，仅用于本地 stat，不暴露给 UI / Shell。"""
    if not p:
        return p
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p
    return "\\\\?\\" + p.replace("/", "\\")


def norm_path(p: str) -> str:
    if not p:
        return ""
    p = p.replace("/", "\\")
    if p.startswith("\\\\?\\"):
        p = p[4:]
    while p.endswith("\\") and not p.endswith(":\\"):
        p = p[:-1]
    return p


def parent_of(p: str) -> str:
    return os.path.dirname(norm_path(p)) or norm_path(p)


def key_of(p: str) -> str:
    return norm_path(p).lower()


@dataclass
class FileEntry:
    path: str
    name: str = ""
    parent: str = ""
    is_dir: bool = False
    size: int = 0
    mtime: float = 0.0
    ctime: float = 0.0
    ext: str = ""
    kind: str = ""
    rel: str = ""
    source: str = "fs"          # fs | everything | http | local | clip | tray
    tags: list = field(default_factory=list)

    def __post_init__(self):
        self.path = norm_path(self.path)
        if not self.name:
            self.name = os.path.basename(self.path) or self.path
        if not self.parent:
            self.parent = parent_of(self.path)
        if not self.ext and not self.is_dir:
            e = os.path.splitext(self.name)[1].lstrip(".").lower()
            self.ext = e
        if not self.kind:
            self.kind = "文件夹" if self.is_dir else EXT_KIND.get(self.ext.lower(), (self.ext.upper() + " 文件") if self.ext else "文件")

    @classmethod
    def from_path(cls, path: str, *, rel_root: str = "", source: str = "fs",
                  stat_result=None, name: str = "", is_dir=None) -> "FileEntry":
        path = norm_path(path)
        st = stat_result
        if st is None:
            try:
                st = os.stat(long_path(path))
            except OSError:
                st = None
        import stat as _stat
        d = bool(is_dir) if is_dir is not None else (bool(st and _stat.S_ISDIR(st.st_mode)))
        nm = name or (os.path.basename(path) or path)
        rel = ""
        if rel_root:
            rr = norm_path(rel_root)
            if path.lower().startswith(rr.lower()):
                rel = path[len(rr):].lstrip("\\") or nm
        return cls(
            path=path, name=nm, parent=parent_of(path), is_dir=d,
            size=0 if d else int(st.st_size if st else 0),
            mtime=float(st.st_mtime if st else 0), ctime=float(st.st_ctime if st else 0),
            ext="" if d else os.path.splitext(nm)[1].lstrip(".").lower(),
            kind="文件夹" if d else EXT_KIND.get(os.path.splitext(nm)[1].lstrip(".").lower(),
                                              (os.path.splitext(nm)[1].lstrip(".").upper() + " 文件") or "文件"),
            rel=rel, source=source,
        )

    def to_dict(self) -> dict:
        return {
            "path": self.path, "name": self.name, "parent": self.parent,
            "is_dir": self.is_dir, "size": self.size, "mtime": self.mtime,
            "ctime": self.ctime, "ext": self.ext, "kind": self.kind,
            "rel": self.rel, "source": self.source, "tags": self.tags,
        }


def entries_to_dict(items) -> list:
    return [e.to_dict() if isinstance(e, FileEntry) else dict(e) for e in items]
