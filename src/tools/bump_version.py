# -*- coding: utf-8 -*-
"""版本升版与一致性自检。

用法（在项目根目录或任意目录执行均可）：
    py -3.14 src/tools/bump_version.py --check      只检查，不改文件
    py -3.14 src/tools/bump_version.py --minor      1.1 → 1.2
    py -3.14 src/tools/bump_version.py --major      1.2 → 2.0
    py -3.14 src/tools/bump_version.py --set 1.4    指定版本

做什么：
    1. 改写 src/fmp/version.py 里的 APP_VERSION（唯一来源）
    2. 在 更新日志.txt 顶部插入新版本段落骨架（带当天日期）
    3. 立刻跑一遍一致性自检，报告还有哪些地方疑似写死了版本号

只改版本号是不够的：产物名、窗口标题、安装信息、界面文案都从
version.py 派生，因此正常情况下除这两处外不需要动任何文件。
"""
from __future__ import annotations

import datetime
import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)
VERSION_PY = os.path.join(SRC, "fmp", "version.py")
CHANGELOG = os.path.join(ROOT, "更新日志.txt")

VER_RE = re.compile(r'^APP_VERSION\s*=\s*"(\d+)\.(\d+)"\s*$', re.M)

# 疑似写死版本号的形态：名称后紧跟 数字.数字
SUSPECT = [
    re.compile(r"文件管理多面手\s+\d+\.\d+"),
]
SCAN_DIRS = ["src", "tests"]
SCAN_EXT = {".py", ".js", ".mjs", ".html", ".txt", ".bat", ".md"}
SKIP_FILES = {os.path.normcase(VERSION_PY), os.path.normcase(CHANGELOG)}
# 说明文档里出现历史版本号是正常的，只扫代码与界面资源
SKIP_DIR_NAMES = {"__pycache__", "_build", "_build_setup", "output", "node_modules"}


def read_version() -> tuple[int, int]:
    text = open(VERSION_PY, encoding="utf-8").read()
    m = VER_RE.search(text)
    if not m:
        raise SystemExit("无法从 fmp/version.py 解析 APP_VERSION")
    return int(m.group(1)), int(m.group(2))


def write_version(major: int, minor: int) -> None:
    text = open(VERSION_PY, encoding="utf-8").read()
    new, n = VER_RE.subn('APP_VERSION = "%d.%d"' % (major, minor), text)
    if n != 1:
        raise SystemExit("改写 APP_VERSION 失败（匹配到 %d 处）" % n)
    open(VERSION_PY, "w", encoding="utf-8").write(new)


def insert_changelog(major: int, minor: int) -> bool:
    """在日志顶部插入新版本段落骨架；已存在则跳过。"""
    ver = "%d.%d" % (major, minor)
    if not os.path.isfile(CHANGELOG):
        return False
    text = open(CHANGELOG, encoding="utf-8").read()
    if re.search(r"^## %s(\s|$)" % re.escape(ver), text, re.M):
        return False
    today = datetime.date.today().isoformat()
    block = (
        "\n\n------------------------------------------------------------\n"
        "## %s  %s\n"
        "------------------------------------------------------------\n"
        "\n"
        "新增\n"
        "  · （待填写）\n"
        "\n"
        "修复\n"
        "  · （待填写）\n"
        "\n"
        "变更\n"
        "  · （待填写）\n" % (ver, today)
    )
    idx = text.find("\n## ")
    if idx < 0:
        text = text.rstrip() + block + "\n"
    else:
        text = text[:idx] + block + text[idx:]
    open(CHANGELOG, "w", encoding="utf-8").write(text)
    return True


def iter_files():
    for d in SCAN_DIRS:
        base_dir = os.path.join(ROOT, d)
        for base, dirs, files in os.walk(base_dir):
            dirs[:] = [x for x in dirs if x not in SKIP_DIR_NAMES]
            for f in files:
                if os.path.splitext(f)[1].lower() not in SCAN_EXT:
                    continue
                p = os.path.join(base, f)
                if os.path.normcase(p) in SKIP_FILES:
                    continue
                yield p


def check() -> int:
    major, minor = read_version()
    ver = "%d.%d" % (major, minor)
    sys.path.insert(0, SRC)
    from fmp.version import (APP_TITLE, EXE_NAME, SETUP_NAME, ZIP_NAME,  # noqa: E402
                             SHORTCUT_NAME, DATA_SERIES)

    problems = []
    print("当前版本：%s" % ver)
    print("  窗口标题    %s（不含版本号）" % APP_TITLE)
    print("  便携版      %s（exe 属性里的文件版本 = %s）" % (EXE_NAME, ver))
    print("  安装版      %s（安装向导显示版本对比）" % SETUP_NAME)
    print("  交付包      %s" % ZIP_NAME)
    print("  快捷方式    %s" % SHORTCUT_NAME)
    print("  数据目录    %%APPDATA%%\\FileManagerMulti\\%s" % DATA_SERIES)

    # 1) 更新日志必须有当前版本段落
    log_ok = False
    if os.path.isfile(CHANGELOG):
        log_ok = bool(re.search(r"^## %s(\s|$)" % re.escape(ver),
                                open(CHANGELOG, encoding="utf-8").read(), re.M))
    if not log_ok:
        problems.append("更新日志.txt 缺少 ## %s 段落" % ver)

    # 2) 界面资源必须用占位符，不能写死版本
    index = os.path.join(SRC, "ui", "index.html")
    if os.path.isfile(index):
        html = open(index, encoding="utf-8").read()
        if "__FMP_VERSION__" not in html:
            problems.append("index.html 未使用 __FMP_VERSION__ 占位符")
        if re.search(r'class="brand-ver">\s*\d+\.\d+', html):
            problems.append("index.html 品牌处写死了版本号")

    # 3) 对外名字里不许出现版本号（版本号只进软件包：exe 属性、界面、安装向导）
    for label, name in (("窗口标题", APP_TITLE), ("便携版", EXE_NAME),
                        ("安装版", SETUP_NAME), ("交付包", ZIP_NAME),
                        ("快捷方式", SHORTCUT_NAME)):
        if re.search(r"\d", name):
            problems.append("%s 名称里带了版本号，违反「序号不进名字」：%s"
                            % (label, name))

    # 4) 全仓扫「名称 + 版本号」的硬编码（排除版本模块与更新日志）
    for p in iter_files():
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for ln_no, line in enumerate(text.splitlines(), 1):
            for pat in SUSPECT:
                if pat.search(line):
                    rel = os.path.relpath(p, ROOT)
                    problems.append("%s:%d 疑似写死版本号：%s"
                                    % (rel, ln_no, line.strip()[:80]))
                    break

    if problems:
        print("\n发现 %d 处需要处理：" % len(problems))
        for x in problems:
            print("  ! " + x)
        return 1
    print("\n一致性自检通过：版本号只有一处定义。")
    _print_release_state()
    return 0


def _print_release_state() -> None:
    """提示距上次出包的源码改动（只警告，不影响退出码）。"""
    try:
        sys.path.insert(0, TOOLS)
        import release_guard
        st = release_guard.status()
    except Exception as exc:  # 守卫模块异常不该阻断自检
        print("（发版守卫不可用：%s）" % exc)
        return
    if st["state"] == "stale-version":
        print("\n注意：距上次出包已改动 %d 个文件，但版本号仍是 %s。"
              % (len(st["changed"]), st["now"]["version"]))
        print("      对外发布前请先执行 --minor 递增版本（构建脚本会拦下来）。")
        for line in st["changed"][:8]:
            print("      " + line)
        if len(st["changed"]) > 8:
            print("      …另有 %d 个" % (len(st["changed"]) - 8))
    elif st["state"] == "version-bumped":
        print("发版状态：%s → %s，源码改动已可出包。"
              % (st["last"].get("version"), st["now"]["version"]))
    elif st["state"] == "unchanged":
        print("发版状态：与上次出包（%s）源码一致。" % st["last"].get("version"))
    else:
        print("发版状态：尚无出包记录。")


def main(argv) -> int:
    if "--check" in argv or not argv:
        return check()

    major, minor = read_version()
    if "--minor" in argv:
        minor += 1
    elif "--major" in argv:
        major, minor = major + 1, 0
    elif "--set" in argv:
        try:
            v = argv[argv.index("--set") + 1]
        except IndexError:
            print("--set 后面要跟版本号，例如 --set 1.3")
            return 2
        if not re.fullmatch(r"\d+\.\d+", v):
            print("版本号格式应为 主.次，例如 1.3 / 2.0")
            return 2
        major, minor = (int(x) for x in v.split("."))
    else:
        print(__doc__)
        return 2

    old = "%d.%d" % read_version()
    write_version(major, minor)
    added = insert_changelog(major, minor)
    print("版本号：%s → %d.%d" % (old, major, minor))
    print("更新日志：%s" % ("已插入 %d.%d 段落骨架，请补写内容" % (major, minor)
                          if added else "已存在该版本段落，未改动"))
    print("")
    return check()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
