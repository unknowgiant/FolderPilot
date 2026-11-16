# -*- coding: utf-8 -*-
"""安装版端到端测试：静默安装 → 校验文件/注册表/快捷方式 → 静默卸载 → 校验清理。

用法：py -3.14 tests/install_test.py
产物：tests/output/install_report.json
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fmp.version import APP_TITLE, APP_VERSION, EXE_NAME, SETUP_NAME, UNINSTALL_KEY  # noqa: E402

SETUP = os.path.join(ROOT, SETUP_NAME)
KEY = UNINSTALL_KEY

report = {"checks": [], "errors": []}
def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def reg_exists():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            v, _ = winreg.QueryValueEx(k, "DisplayName")
        return v
    except OSError:
        return None


def main():
    if not os.path.isfile(SETUP):
        print("缺少安装器：", SETUP)
        return 1
    tmp = tempfile.mkdtemp(prefix="fmp_setup_test_")
    install_dir = os.path.join(tmp, "installed")
    report_path = os.path.join(tmp, "install_result.json")
    manifest_shortcuts = []
    try:
        r = subprocess.run([SETUP, "--silent", "--dir=" + install_dir,
                            "--report=" + report_path], timeout=90)
        check("静默安装退出码为 0", r.returncode == 0, r.returncode)
        data = {}
        if os.path.isfile(report_path):
            data = json.load(open(report_path, encoding="utf-8"))
        check("安装报告标记成功", data.get("ok") is True, json.dumps(data, ensure_ascii=False)[:200])
        exe = os.path.join(install_dir, EXE_NAME)
        check("主程序已释放", os.path.isfile(exe) and os.path.getsize(exe) > 10_000_000,
              os.path.getsize(exe) if os.path.isfile(exe) else "缺失")
        for f in ["使用说明.txt", "架构与修复说明.txt", "更新日志.txt",
                  os.path.join("licenses", "Everything-SDK-License.txt")]:
            check("已释放 " + f, os.path.isfile(os.path.join(install_dir, f)))
        mf = os.path.join(install_dir, "install.json")
        check("安装清单已生成", os.path.isfile(mf))
        if os.path.isfile(mf):
            manifest_shortcuts = json.load(open(mf, encoding="utf-8")).get("shortcuts", [])
        check("卸载项已写入 HKCU", reg_exists() == APP_TITLE, reg_exists())
        check("快捷方式已创建", len(manifest_shortcuts) >= 1, manifest_shortcuts)

        # 静默卸载（主程序 --uninstall --yes，不弹确认框）
        u = subprocess.run([exe, "--uninstall", "--yes"], timeout=60)
        check("静默卸载退出码为 0", u.returncode == 0, u.returncode)
        check("卸载项已删除", reg_exists() is None, reg_exists())
        for s in manifest_shortcuts:
            check("快捷方式已删除 " + os.path.basename(s), not os.path.exists(s))
        time.sleep(4.5)      # PowerShell 延时清理安装目录
        check("安装目录已自动清除", not os.path.isdir(install_dir), install_dir)

        # 安装向导 GUI 能正常打开并关闭
        u32 = ctypes.windll.user32
        u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.FindWindowW.restype = wintypes.HWND
        p = subprocess.Popen([SETUP], cwd=ROOT)
        hwnd = 0
        for _ in range(100):
            hwnd = u32.FindWindowW(None, APP_TITLE + " 安装")
            if hwnd:
                break
            time.sleep(0.1)
        check("安装向导窗口可正常显示", bool(hwnd))
        if hwnd:
            u32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
            try:
                p.wait(timeout=8)
                check("安装向导可正常关闭", True)
            except subprocess.TimeoutExpired:
                p.kill()
                check("安装向导可正常关闭", False, "关闭超时")
        else:
            p.kill()
    except Exception as ex:
        check("流程异常", False, f"{type(ex).__name__}: {ex}")
    finally:
        for s in manifest_shortcuts:
            try:
                if os.path.isfile(s):
                    os.remove(s)
            except OSError:
                pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY)
        except OSError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    report["passed"] = not report["errors"]
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "install_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
