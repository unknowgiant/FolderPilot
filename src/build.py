# -*- coding: utf-8 -*-
"""打包脚本：生成便携版单文件 exe（含前端资源与 Everything SDK）。

用法：py -3.14 build.py [--allow-same-version]
产物：../<文件管理多面手 X.Y>.exe（版本号取自 fmp/version.py）

构建前会比对源码指纹：源码改过但版本号没变时拒绝出包，
必须先用 tools/bump_version.py --minor 递增版本（详见 tools/release_guard.py）。
--allow-same-version 仅供本机验证，产物不要对外发布。
"""
import os
import shutil
import subprocess
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "tools"))

from fmp.version import APP_TITLE, APP_VERSION, EXE_NAME  # noqa: E402
import release_guard  # noqa: E402

BUILD = os.path.join(ROOT, "_build")
DIST = os.path.join(BUILD, "dist")
NAME = "FileManagerMulti"
FINAL = os.path.join(ROOT, EXE_NAME)


def main():
    if not release_guard.require_new_version(
            allow_same="--allow-same-version" in sys.argv):
        return 3
    for d in (BUILD, DIST):
        os.makedirs(d, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", NAME,
        "--icon", os.path.join(SRC, "assets", "app_icon.ico"),
        "--distpath", DIST, "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        "--add-data", os.path.join(SRC, "ui") + os.pathsep + "ui",
        "--add-data", os.path.join(SRC, "assets") + os.pathsep + "assets",
        "--collect-all", "webview",
        "--hidden-import", "clr",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
        os.path.join(SRC, "main.py"),
    ]
    print(">>> 版本 %s → %s" % (APP_VERSION, os.path.basename(FINAL)), flush=True)
    print(">>>", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=SRC)
    if r.returncode != 0:
        print("打包失败，退出码", r.returncode)
        return r.returncode
    built = os.path.join(DIST, NAME + ".exe")
    if not os.path.isfile(built):
        print("未找到产物", built)
        return 1
    shutil.copyfile(built, FINAL)
    stamp = release_guard.record_release()
    print("完成：", FINAL, os.path.getsize(FINAL), "bytes")
    print("发版记录：版本 %s，源码 %d 个文件，指纹 %s"
          % (stamp["version"], stamp["file_count"], stamp["digest"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
