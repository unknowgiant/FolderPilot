# -*- coding: utf-8 -*-
"""文件系统服务：目录枚举、磁盘、属性、预览信息。"""
from __future__ import annotations

import ctypes
import os
import stat as statmod
import zipfile
from ctypes import wintypes

from .model import (ARCHIVE_EXT, IMAGE_EXT, TEXT_EXT, FileEntry,
                    entries_to_dict, long_path, norm_path)

THIS_PC = "::{THISPC}"
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def is_hidden(path: str, st=None) -> bool:
    try:
        attrs = getattr(st, "st_file_attributes", 0) if st else ctypes.windll.kernel32.GetFileAttributesW(long_path(path))
        return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
    except Exception:
        return False


def list_dir(path: str, show_hidden: bool = False):
    if path == THIS_PC:
        return [FileEntry(d["path"], d["name"], "", True, kind="磁盘驱动器", source="fs") for d in drives()]
    path = norm_path(path)
    if not path or not os.path.isdir(long_path(path)):
        raise FileNotFoundError(f"目录不存在或不可访问：{path}")
    out = []
    with os.scandir(long_path(path)) as it:
        for de in it:
            try:
                st = de.stat(follow_symlinks=False)
                full = norm_path(os.path.join(path, de.name))
                if not show_hidden and is_hidden(full, st):
                    continue
                isd = statmod.S_ISDIR(st.st_mode)
                e = FileEntry.from_path(full, stat_result=st, name=de.name, is_dir=isd, source="fs")
                out.append(e)
            except (OSError, PermissionError):
                continue
    return out


def drives():
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    out = []
    for i in range(26):
        if not (mask >> i) & 1:
            continue
        root = chr(65 + i) + ":\\"
        dt = k32.GetDriveTypeW(ctypes.c_wchar_p(root))
        # 2=可移动 3=固定 4=网络 5=光驱 6=内存盘
        if dt == 5:
            continue
        free = total = 0
        f, t = wintypes.ULARGE_INTEGER(), wintypes.ULARGE_INTEGER()
        try:
            k32.GetDiskFreeSpaceExW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(wintypes.ULARGE_INTEGER),
                                                ctypes.POINTER(wintypes.ULARGE_INTEGER), ctypes.POINTER(wintypes.ULARGE_INTEGER)]
            if k32.GetDiskFreeSpaceExW(root, ctypes.byref(f), ctypes.byref(t), None):
                free, total = int(f.value), int(t.value)
        except Exception:
            pass
        label = ""
        buf = ctypes.create_unicode_buffer(261)
        try:
            if k32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 260, None, None, None, None, 0):
                label = buf.value
        except Exception:
            pass
        out.append({"path": root, "name": (label + f" ({root[0]}:)") if label else f"本地磁盘 ({root[0]}:)",
                    "letter": root[0], "total": total, "free": free,
                    "type": {2: "可移动", 3: "本地磁盘", 4: "网络驱动器", 6: "内存盘"}.get(dt, "驱动器")})
    return out


def special_paths():
    home = os.path.expanduser("~")
    cands = [("桌面", os.path.join(home, "Desktop")), ("下载", os.path.join(home, "Downloads")),
             ("文档", os.path.join(home, "Documents")), ("图片", os.path.join(home, "Pictures")),
             ("视频", os.path.join(home, "Videos")), ("音乐", os.path.join(home, "Music"))]
    return [{"name": n, "path": norm_path(p)} for n, p in cands if os.path.isdir(p)]


def props(path: str):
    path = norm_path(path)
    e = FileEntry.from_path(path)
    st = None
    try:
        st = os.stat(long_path(path))
        attrs = getattr(st, "st_file_attributes", 0)
    except OSError as ex:
        raise RuntimeError(f"无法读取属性：{ex}")
    flags = []
    for bit, name in ((0x1, "只读"), (0x2, "隐藏"), (0x4, "系统"), (0x20, "存档"),
                      (0x800, "压缩"), (0x400, "加密"), (0x2000, "非索引")):
        if attrs & bit:
            flags.append(name)
    import datetime
    def fmt(ts):
        try:
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"
    total = e.size
    count = 0
    if e.is_dir:
        try:
            for root, dirs, files in os.walk(long_path(path)):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                        count += 1
                    except OSError:
                        pass
                if count > 20000:
                    break
        except OSError:
            pass
    return {"path": path, "name": e.name, "is_dir": e.is_dir, "size": total,
            "file_count": count, "mtime": fmt(e.mtime), "ctime": fmt(e.ctime),
            "atime": fmt(st.st_atime), "attributes": flags, "kind": e.kind,
            "parent": e.parent, "ext": e.ext}


TEXT_LIMIT = 512 * 1024


def read_text_head(path: str, limit: int = TEXT_LIMIT):
    raw = b""
    with open(long_path(path), "rb") as f:
        raw = f.read(limit)
    for enc in ("utf-8-sig", "gb18030", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def preview_info(path: str):
    """返回前端预览所需信息（文本直接给内容，其它给 /file 直链）。"""
    e = FileEntry.from_path(path)
    d = e.to_dict()
    if e.is_dir:
        return {**d, "preview": "dir", "child_count": len(list_dir(path, True))}
    ext = e.ext.lower()
    if ext in IMAGE_EXT and e.size < 30 * 1024 * 1024:
        return {**d, "preview": "image"}
    if ext in ("mp4", "webm", "mkv", "avi", "mov"):
        return {**d, "preview": "video"}
    if ext in ("mp3", "wav", "flac", "aac", "m4a", "ogg"):
        return {**d, "preview": "audio"}
    if ext == "pdf":
        return {**d, "preview": "pdf"}
    if ext in ARCHIVE_EXT and ext == "zip":
        return {**d, "preview": "archive", "archive_entries": zip_entries(path)}
    if ext in TEXT_EXT or e.size < 256 * 1024:
        try:
            return {**d, "preview": "text", "text": read_text_head(path),
                    "lang": "markdown" if ext == "md" else ext}
        except OSError as ex:
            return {**d, "preview": "none", "error": str(ex)}
    return {**d, "preview": "none"}


def zip_entries(path: str, limit: int = 4000):
    try:
        with zipfile.ZipFile(long_path(path)) as z:
            return [{"name": i.filename, "size": i.file_size, "is_dir": i.is_dir(),
                     "compressed": i.compress_size} for i in z.infolist()[:limit]]
    except Exception as ex:
        return [{"name": f"无法读取压缩包：{ex}", "size": 0, "is_dir": False, "compressed": 0}]


def icon_key(e: FileEntry) -> str:
    if e.is_dir:
        return "folder"
    x = e.ext.lower()
    if x in IMAGE_EXT:
        return "image"
    if x == "pdf":
        return "pdf"
    if x in ("doc", "docx", "wps", "xls", "xlsx", "ppt", "pptx", "txt", "md"):
        return "doc"
    if x in ("zip", "rar", "7z"):
        return "zip"
    if x in ("mp4", "mkv", "avi", "mov"):
        return "video"
    if x in ("mp3", "wav", "flac"):
        return "audio"
    if x in ("exe", "msi", "bat", "cmd"):
        return "exe"
    if x in ("dwg", "dxf", "vsdx", "psd"):
        return "cad"
    return "file"
