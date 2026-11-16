# -*- coding: utf-8 -*-
"""打包安装版 Setup.exe（单文件，内嵌便携版主程序与说明文档）。

前置条件：先运行 build.py 生成当前版本的便携版 exe。
用法：py -3.14 build_setup.py
产物：../<文件管理多面手 X.Y>-Setup.exe（版本号取自 fmp/version.py）
"""
import os
import shutil
import subprocess
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from fmp.version import APP_VERSION, EXE_NAME, SETUP_NAME  # noqa: E402

BUILD = os.path.join(ROOT, "_build_setup")
DIST = os.path.join(BUILD, "dist")
MAIN = os.path.join(ROOT, EXE_NAME)
FINAL = os.path.join(ROOT, SETUP_NAME)

PAYLOAD_FILES = [
    (MAIN, "payload"),
    (os.path.join(SRC, "assets", "app_icon.ico"), "payload"),
    (os.path.join(ROOT, "使用说明.txt"), "payload"),
    (os.path.join(ROOT, "架构与修复说明.txt"), "payload"),
    (os.path.join(ROOT, "更新日志.txt"), "payload"),
    (os.path.join(ROOT, "licenses", "Everything-SDK-License.txt"), "payload/licenses"),
]


def main():
    if not os.path.isfile(MAIN):
        print("请先运行 build.py 生成主程序：", MAIN)
        return 1
    os.makedirs(DIST, exist_ok=True)
    args = []
    for src, dest in PAYLOAD_FILES:
        if not os.path.isfile(src):
            print("缺少待打包文件：", src)
            return 1
        args += ["--add-data", src + os.pathsep + dest]
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "FileManagerMultiSetup",
        "--icon", os.path.join(SRC, "assets", "app_icon.ico"),
        "--distpath", DIST, "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        "--exclude-module", "webview", "--exclude-module", "clr",
        "--exclude-module", "numpy", "--exclude-module", "PIL",
        *args,
        os.path.join(SRC, "setup_app.py"),
    ]
    print(">>> 版本 %s → %s" % (APP_VERSION, os.path.basename(FINAL)), flush=True)
    print(">>> 打包安装器…", flush=True)
    r = subprocess.run(cmd, cwd=SRC)
    if r.returncode != 0:
        print("安装器打包失败，退出码", r.returncode)
        return r.returncode
    built = os.path.join(DIST, "FileManagerMultiSetup.exe")
    if not os.path.isfile(built):
        print("未找到产物", built)
        return 1
    shutil.copyfile(built, FINAL)
    print("完成：", FINAL, os.path.getsize(FINAL), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
