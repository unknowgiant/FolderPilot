# -*- coding: utf-8 -*-
"""生成 PyInstaller 的 --version-file 内容：把版本号写进 exe 本体。

命名规则是「文件名不带版本、版本放进软件包里」，那 exe 右键 → 属性 →
详细信息里就必须能读到版本号，否则用户根本不知道手里这一个是哪一版。
PyInstaller 的版本资源只认一个 Python 字面量（VSVersionInfo(...)），
这里按当前版本拼出来，构建时写到 _build/ 下即可。
"""
from __future__ import annotations

import os

# 中文（简体）＋ Unicode 代码页：0804 = zh-CN，04B0 = 1200
LANG_TABLE = "080404B0"
TRANSLATION = "[2052, 1200]"

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(tuple)s,
    prodvers=%(tuple)s,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '%(table)s',
        [%(strings)s])
    ]),
    VarFileInfo([VarStruct('Translation', %(translation)s)])
  ]
)
"""


def _quad(version: str) -> str:
    parts = [int(x) for x in str(version).split(".") if x.strip().isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return "(" + ", ".join(str(x) for x in parts[:4]) + ")"


def content(version: str, filename: str, product: str = "文件管理多面手",
            description: str = "双窗格文件管理器") -> str:
    fields = [
        ("CompanyName", product),
        ("FileDescription", "%s · %s" % (product, description)),
        ("FileVersion", str(version)),
        ("InternalName", "FileManagerMulti"),
        ("LegalCopyright", "Copyright (C) 2026 %s" % product),
        ("OriginalFilename", filename),
        ("ProductName", product),
        ("ProductVersion", str(version)),
    ]
    lines = ",\n         ".join(
        "StringStruct(%r, %r)" % (k, v) for k, v in fields)
    return TEMPLATE % {"tuple": _quad(version), "table": LANG_TABLE,
                       "strings": "\n         " + lines + "\n        ",
                       "translation": TRANSLATION}


def write(path: str, version: str, filename: str, **kw) -> str:
    """把版本资源写到 path（utf-8），返回该路径供 --version-file 使用。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content(version, filename, **kw))
    return path


if __name__ == "__main__":
    import sys
    v = sys.argv[1] if len(sys.argv) > 1 else "0.0"
    print(content(v, "文件管理多面手.exe"))
