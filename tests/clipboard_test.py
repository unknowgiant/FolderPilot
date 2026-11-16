# -*- coding: utf-8 -*-
"""剪贴板跨程序兼容性自测：CF_HDROP / FileNameW / DropEffect / ANSI 读取 / 路径诊断。

用法：py -3.14 tests/clipboard_test.py
产物：tests/output/clipboard_report.json
注意：本测试会临时改写系统剪贴板。
"""
from __future__ import annotations

import ctypes
import json
import os
import struct
import sys
import tempfile
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fmp import clipboard  # noqa: E402

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def main():
    tmp = tempfile.mkdtemp(prefix="fmp_cliptest_")
    deep = os.path.join(tmp, "8、2024年高价值宽带用户覆盖提升工程", "1、施工图设计",
                        "第一批设计", "快扩", "家客")
    os.makedirs(deep, exist_ok=True)
    f1 = os.path.join(deep, "中国移动河南公司洛阳分公司2025年商务宽带一期工程-说明（含预算及图纸）.pdf")
    f2 = os.path.join(tmp, "普通文件.txt")
    for p in (f1, f2):
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4 test content")

    # 1) 路径规范化：外部程序只接受普通 Win32 路径
    s = clipboard.shell_path("\\\\?\\" + f1.replace("/", "\\"))
    check("长路径前缀被剥离", not s.startswith("\\\\?\\") and os.path.isabs(s), s[:60])
    check("中文长路径可规范化", len(s) == len(f1) and os.path.exists(s), len(s))

    # 2) 可读性诊断
    info = clipboard.check_access(f1)
    check("可访问性诊断判定为可读", info["readable"] and info["exists"], json.dumps(
        {k: info[k] for k in ("length", "exists", "readable", "error")}, ensure_ascii=False))
    check("诊断未误判特殊属性", info["unsafe_attrs"] == [], str(info["unsafe_attrs"]))

    # 3) 写入 CF_HDROP 后由完全独立的读取代码验证（模拟外部程序）
    r = clipboard.write_files([f1, f2], False)
    check("write_files 返回写入数量", r.get("count") == 2, str(r.get("count")))
    u32, k32 = clipboard._fns()          # 复用模块内已正确声明 argtypes 的 API
    check("外部程序可见 CF_HDROP", bool(u32.IsClipboardFormatAvailable(15)))
    read_back = []
    if u32.OpenClipboard(0):
        try:
            h = u32.GetClipboardData(15)
            if h:
                p = k32.GlobalLock(h)
                if p:
                    buf = ctypes.string_at(p, k32.GlobalSize(h))
                    off, _x, _y, _nc, wide = struct.unpack_from("IIIii", buf, 0)
                    check("DROPFILES 头正确(fWide=1, offset=20)", off == 20 and wide == 1,
                          f"off={off} wide={wide}")
                    read_back = [x for x in buf[off:].decode("utf-16-le", "replace").split("\x00") if x]
                    k32.GlobalUnlock(h)
            fmt = u32.RegisterClipboardFormatW("FileNameW")
            check("提供 FileNameW 兼容格式", bool(fmt) and
                  bool(u32.IsClipboardFormatAvailable(fmt)), "fmt=" + str(fmt))
            eff = u32.RegisterClipboardFormatW("Preferred DropEffect")
            check("提供 Preferred DropEffect 格式", bool(eff) and
                  bool(u32.IsClipboardFormatAvailable(eff)), "fmt=" + str(eff))
        finally:
            u32.CloseClipboard()
    check("两个中文长路径完整往返", read_back == [f1, f2], str(read_back))
    check("本模块 read_files 往返一致", clipboard.read_files()[0] == [f1, f2])

    # 4) 剪切标记
    clipboard.write_files([f2], True)
    check("剪切标记 DROPEFFECT_MOVE", clipboard.read_files()[1] is True)

    # 5) 兼容其他程序写入的 ANSI(fWide=0) DROPFILES
    ansi = clipboard.shell_path(f2).encode("mbcs") + b"\x00\x00"
    blob = struct.pack("IIIii", 20, 0, 0, 0, 0) + ansi
    if u32.OpenClipboard(0):
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(0x0002, len(blob))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, blob, len(blob))
            k32.GlobalUnlock(h)
            u32.SetClipboardData(15, h)
        finally:
            u32.CloseClipboard()
    check("可读取 ANSI 版 CF_HDROP", clipboard.read_files()[0] == [f2],
          str(clipboard.read_files()[0]))

    # 6) 坏路径给出明确错误而不是静默写坏剪贴板
    missing = os.path.join(tmp, "不存在的文件.pdf")
    try:
        clipboard.write_files([missing])
        check("不可读文件被拒绝", False, "未抛异常")
    except RuntimeError as ex:
        check("不可读文件被拒绝并给出原因", "不可读" in str(ex), str(ex))

    report["passed"] = not report["errors"]
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "clipboard_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
