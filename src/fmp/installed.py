# -*- coding: utf-8 -*-
"""本机已安装版本侦测：给安装向导做「即将安装 vs 系统当前」的对比。

安装向导要在动手之前就回答用户两个问题——这台机器上原本是什么版本、
这一装会把它变成什么版本——所以这里只做只读探测，不写任何东西。
探测来源按可信度从高到低：

  1. HKCU 卸载项（DisplayVersion / InstallLocation）——正常安装都会有
  2. 安装目录里的 install.json ——注册表被清理过时的兜底
  3. 安装目录内的主程序文件名（老版本把版本号写进了文件名，形如
     项目名 + 空格 + 版本号 + .exe）

版本号一律按数字段比较（1.10 > 1.9）。字符串比较会把 1.10 判成比 1.9 旧，
这在安装向导里会给出「降级安装」的错误结论。
"""
from __future__ import annotations

import json
import os
import re
import winreg

from .version import (APP_ID, LEGACY_UNINSTALL_PREFIX, PROJECT_CODE,
                      UNINSTALL_KEY)

UNINST_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

# 安装目录名：正式名（不带版本），或历史遗留的「名称 + 空格 + 版本号」
DIR_PAT = re.compile(r"^" + re.escape(PROJECT_CODE) + r"(?: \d+(?:\.\d+)*)?$", re.I)
# 主程序文件名里的版本（老版本命名方式，仅用于兜底识别）
EXE_VER_PAT = re.compile(r"^" + re.escape(PROJECT_CODE) + r" (\d+(?:\.\d+)*)\.exe$", re.I)


def parse_version(text) -> tuple[int, int, int] | None:
    """把 '1.7' / 'v1.7' / '1.7.0' 归一成 (1, 7, 0)；解析不出来返回 None。"""
    if text is None:
        return None
    m = re.search(r"\d+(?:\.\d+)*", str(text))
    if not m:
        return None
    parts = [int(x) for x in m.group(0).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])  # type: ignore[return-value]


def cmp_version(a, b) -> int:
    """a 比 b 旧返回 -1，相同 0，更新 +1；任一侧解析失败按「相同」处理。"""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return 0
    return (pa > pb) - (pa < pb)


def short_version(text) -> str:
    """统一显示成 主.次（1.6.0 → 1.6）。"""
    v = parse_version(text)
    return "%d.%d" % (v[0], v[1]) if v else ""


def programs_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Programs")


def _read_values(subkey: str) -> dict:
    """读一个注册表键的全部值；键不存在返回空字典（不抛异常）。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as k:
            out, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value
                i += 1
            return out
    except OSError:
        return {}


def _from_registry() -> list[dict]:
    found = []
    cur = _read_values(UNINSTALL_KEY)
    if cur.get("DisplayVersion"):
        found.append({"version": short_version(cur["DisplayVersion"]),
                      "dir": str(cur.get("InstallLocation") or ""),
                      "how": "注册表"})
    # 1.0 时代按版本号拆分的老键（FileManagerMulti_1_0），只做兜底展示
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINST_ROOT) as k:
            names, i = [], 0
            while True:
                try:
                    names.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        names = []
    for name in names:
        if not name.startswith(LEGACY_UNINSTALL_PREFIX):
            continue
        vals = _read_values(UNINST_ROOT + "\\" + name)
        ver = vals.get("DisplayVersion") or name[len(LEGACY_UNINSTALL_PREFIX):]
        if parse_version(ver):
            found.append({"version": short_version(ver),
                          "dir": str(vals.get("InstallLocation") or ""),
                          "how": "旧版注册表"})
    return found


def _from_dirs() -> list[dict]:
    root = programs_root()
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found = []
    for name in names:
        if not DIR_PAT.match(name):
            continue
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        manifest = os.path.join(d, "install.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, encoding="utf-8") as f:
                    j = json.load(f)
                if j.get("version"):
                    found.append({"version": short_version(j["version"]),
                                  "dir": d, "how": "安装清单"})
                    continue
            except (OSError, ValueError):
                pass
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for n in files:
            m = EXE_VER_PAT.match(n)
            if m:
                found.append({"version": short_version(m.group(1)),
                              "dir": d, "how": "主程序文件名"})
                break
    return found


def scan_installed() -> list[dict]:
    """本机所有已安装实例，按版本从新到旧。同版本只留一条（优先带目录的）。"""
    best: dict[str, dict] = {}
    for item in _from_registry() + _from_dirs():
        ver = item.get("version")
        if not parse_version(ver):
            continue
        old = best.get(ver)
        if old is None or (not old.get("dir") and item.get("dir")):
            best[ver] = item
    return sorted(best.values(), key=lambda x: parse_version(x["version"]),
                  reverse=True)


def latest_installed() -> dict | None:
    items = scan_installed()
    return items[0] if items else None


_UNSET = object()          # 区分「没传」与「明确告知本机没装」


def compare(new_version: str, found=_UNSET) -> dict:
    """把「即将安装的版本」和「本机已有的版本」摆成一句可直接渲染的结论。

    返回字段：
        kind   fresh / upgrade / same / downgrade
        old    已有版本（全新安装为 None）
        new    即将安装的版本
        title  大字标签：全新安装 / 升级安装 / 同版本重装 / 降级安装
        arrow  中间那行连接语：如「覆盖 1.6」「无需升级」
        note   一句人话解释会发生什么
        dir    已安装目录（可能为空）
        how    版本来源（注册表 / 安装清单 / 主程序文件名）
        level  info / ok / warn ——界面据此选配色
    """
    if found is _UNSET:
        found = latest_installed()
    new_ver = short_version(new_version) or str(new_version)
    if not found:
        return {"kind": "fresh", "old": None, "new": new_ver, "title": "全新安装",
                "arrow": "首次安装", "dir": "", "how": "",
                "note": "本机没有检测到已安装的版本，本次为首次安装。", "level": "info"}

    old = found["version"]
    c = cmp_version(old, new_ver)
    base = {"old": old, "new": new_ver, "dir": found.get("dir", ""),
            "how": found.get("how", "")}
    if c < 0:
        return {**base, "kind": "upgrade", "title": "升级安装",
                "arrow": "%s → %s" % (old, new_ver), "level": "ok",
                "note": "本机已装 %s，本次升级到 %s：就地覆盖，安装位置、快捷方式与个人设置都保持不动。" % (old, new_ver)}
    if c == 0:
        return {**base, "kind": "same", "title": "同版本重装",
                "arrow": "覆盖 %s" % old, "level": "info",
                "note": "本机已是 %s，本次会用同一版本重装一遍（文件被重新释放，设置不受影响）。" % old}
    return {**base, "kind": "downgrade", "title": "降级安装",
            "arrow": "%s → %s" % (old, new_ver), "level": "warn",
            "note": "本机已有更新版本 %s，本次装的是更旧的 %s。旧版可能读不懂新版配置，建议改装 %s。"
                    % (old, new_ver, old)}


__all__ = ["parse_version", "cmp_version", "short_version", "programs_root",
           "scan_installed", "latest_installed", "compare", "APP_ID"]
