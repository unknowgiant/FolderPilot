# -*- coding: utf-8 -*-
"""发版守卫：源码一改，版本号就必须往上走。

为什么需要它：
    「每次更新版本号递增」如果只写在文档里，打包时很容易忘。这个模块把
    规则变成机械约束——构建前对比「上次出包时的源码指纹」与「当前源码指纹」，
    只要源码动过而 APP_VERSION 没变，构建直接拒绝，并列出改了哪些文件。

判定（build.py 构建前自动调用）：
    上次记录不存在            → 放行（首次出包）
    版本号比上次大            → 放行
    版本号相同、源码指纹相同   → 放行（同一版本重打包，例如只修构建脚本）
    版本号相同、源码指纹不同   → **拒绝**，提示先跑 bump_version.py --minor

记录文件：<项目根>/_build/release.json（不随交付包发布）
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
VERSION_PY = os.path.join(SRC, "fmp", "version.py")
STAMP = os.path.join(ROOT, "_build", "release.json")

# 这些目录里的东西不进交付产物，也不影响版本
SKIP_DIRS = {
    "__pycache__", "output", "node_modules", ".git", ".idea",
    "_build", "_build_setup", "_engine_probe",
}
SKIP_EXT = {".pyc", ".pyo", ".log", ".tmp", ".bak"}

VER_RE = re.compile(r'^APP_VERSION\s*=\s*"(\d+)\.(\d+)"\s*$', re.M)


def current_version() -> str:
    text = open(VERSION_PY, encoding="utf-8").read()
    m = VER_RE.search(text)
    if not m:
        raise SystemExit("无法从 fmp/version.py 解析 APP_VERSION")
    return "%s.%s" % (m.group(1), m.group(2))


def vtuple(v: str) -> tuple[int, int]:
    a, b = v.split(".")[:2]
    return int(a), int(b)


def scan() -> dict[str, str]:
    """返回 {相对路径: sha1}，用于算整体指纹并列出改动文件。"""
    files = {}
    for base, dirs, names in os.walk(SRC):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(base, name)
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            rel = os.path.relpath(path, SRC).replace("\\", "/")
            files[rel] = hashlib.sha1(data).hexdigest()
    return files


def digest_of(files: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(files[rel].encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def read_stamp() -> dict | None:
    if not os.path.isfile(STAMP):
        return None
    try:
        return json.load(open(STAMP, encoding="utf-8"))
    except (OSError, ValueError):
        return None


def changed_files(old: dict[str, str], new: dict[str, str]) -> list[str]:
    out = []
    for rel in sorted(set(old) | set(new)):
        if old.get(rel) != new.get(rel):
            mark = "新增" if rel not in old else ("删除" if rel not in new else "修改")
            out.append("%s  %s" % (mark, rel))
    return out


def status() -> dict:
    """给 --check / 构建前用的状态快照。"""
    files = scan()
    stamp = read_stamp()
    cur = {"version": current_version(), "digest": digest_of(files)}
    info = {"now": cur, "last": stamp, "changed": [], "state": "unknown"}
    if not stamp:
        info["state"] = "first"
        return info
    info["changed"] = changed_files(stamp.get("files", {}), files)
    if stamp.get("version") != cur["version"]:
        info["state"] = "version-bumped"
    elif stamp.get("digest") == cur["digest"]:
        info["state"] = "unchanged"
    else:
        info["state"] = "stale-version"
    return info


def require_new_version(allow_same: bool = False) -> bool:
    """构建前的硬校验。返回 True 表示可以出包。"""
    info = status()
    state = info["state"]
    now, last = info["now"], info["last"]

    if state in ("first", "version-bumped", "unchanged"):
        return True

    # state == "stale-version"
    if allow_same:
        print("!! 源码已改动但版本号仍是 %s；本次按 --allow-same-version 放行。" % now["version"])
        print("   这种包只能用于本机验证，不要对外发布。")
        return True

    print("=" * 60)
    print("构建被拒绝：源码变了，版本号没变。")
    print("  上次出包：%s" % last.get("version"))
    print("  当前版本：%s" % now["version"])
    print("  改动文件：%d 个" % len(info["changed"]))
    for line in info["changed"][:20]:
        print("    " + line)
    if len(info["changed"]) > 20:
        print("    …另有 %d 个" % (len(info["changed"]) - 20))
    print("")
    print("每次更新都必须递增软件编号。先执行：")
    print("    py src/tools/bump_version.py --minor")
    print("（大版本重构用 --major；仅本机验证可用 build.py --allow-same-version）")
    print("=" * 60)
    return False


def record_release() -> dict:
    """构建成功后写入本次指纹。"""
    files = scan()
    stamp = {
        "version": current_version(),
        "digest": digest_of(files),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_count": len(files),
        "files": files,
    }
    os.makedirs(os.path.dirname(STAMP), exist_ok=True)
    json.dump(stamp, open(STAMP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return stamp


if __name__ == "__main__":
    s = status()
    print("当前版本：%s" % s["now"]["version"])
    if s["state"] == "first":
        print("状态：还没有出包记录（首次构建不会拦截）")
    elif s["state"] == "unchanged":
        print("状态：与上次出包完全一致（版本 %s）" % s["last"].get("version"))
    elif s["state"] == "version-bumped":
        print("状态：版本已递增 %s → %s，可以出包"
              % (s["last"].get("version"), s["now"]["version"]))
    else:
        print("状态：源码改动 %d 个文件但版本号未变 → 构建会被拒绝"
              % len(s["changed"]))
    print("上次出包：%s" % (s["last"] or {}).get("built_at", "—"))
