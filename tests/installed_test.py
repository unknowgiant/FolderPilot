# -*- coding: utf-8 -*-
"""安装向导版本对比专项：版本解析、比较、场景判定、本机探测。

用法：py tests/installed_test.py
产物：tests/output/installed_report.json
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fmp import installed  # noqa: E402
from fmp.version import APP_TITLE, APP_VERSION  # noqa: E402

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def main():
    # 1) 版本解析
    cases = {"1.7": (1, 7, 0), "v1.7": (1, 7, 0), "1.7.0": (1, 7, 0),
             "1.10": (1, 10, 0), "2": (2, 0, 0), "": None, "abc": None, None: None}
    for raw, want in cases.items():
        check("解析 %r" % (raw,), installed.parse_version(raw) == want,
              installed.parse_version(raw))

    # 2) 版本比较：1.10 必须比 1.9 新（字符串比较会判反）
    pairs = [("1.6", "1.7", -1), ("1.7", "1.7", 0), ("1.10", "1.9", 1),
             ("2.0", "1.99", 1), ("1.7.0", "1.7", 0)]
    for a, b, want in pairs:
        got = installed.cmp_version(a, b)
        check("比较 %s vs %s" % (a, b), got == want, got)

    # 3) 显示归一
    check("1.7.0 显示为 1.7", installed.short_version("1.7.0") == "1.7",
          installed.short_version("1.7.0"))

    # 4) 四种场景
    fresh = installed.compare(APP_VERSION, None)
    check("未安装 → 全新安装", fresh["kind"] == "fresh" and fresh["old"] is None,
          fresh["kind"])
    check("全新安装不改写已有版本", fresh["new"] == APP_VERSION, fresh["new"])

    up = installed.compare("1.7", {"version": "1.6", "dir": r"C:\x\y", "how": "注册表"})
    check("1.6 → 1.7 判为升级", up["kind"] == "upgrade" and up["level"] == "ok", up["kind"])
    check("升级文案含两端版本", "1.6" in up["note"] and "1.7" in up["note"], up["note"])
    check("升级保留安装目录", up["dir"] == r"C:\x\y", up["dir"])

    same = installed.compare("1.7", {"version": "1.7", "dir": "", "how": "安装清单"})
    check("1.7 → 1.7 判为同版本重装", same["kind"] == "same", same["kind"])

    down = installed.compare("1.7", {"version": "1.8", "dir": "", "how": "注册表"})
    check("1.8 → 1.7 判为降级", down["kind"] == "downgrade" and down["level"] == "warn",
          down["kind"])

    # 5) 用临时 LOCALAPPDATA 模拟一套安装目录，验证目录扫描与去重
    tmp = tempfile.mkdtemp(prefix="fmp_installed_test_")
    old_env = os.environ.get("LOCALAPPDATA")
    try:
        programs = os.path.join(tmp, "Programs")
        # 5a) 正式安装目录 + install.json
        d1 = os.path.join(programs, APP_TITLE)
        os.makedirs(d1)
        with open(os.path.join(d1, "install.json"), "w", encoding="utf-8") as f:
            json.dump({"version": "1.6", "install_dir": d1}, f)
        # 5b) 老式带版本号目录，只有主程序文件名可依据
        d2 = os.path.join(programs, APP_TITLE + " 1.5")
        os.makedirs(d2)
        open(os.path.join(d2, APP_TITLE + " 1.5.exe"), "wb").close()
        os.environ["LOCALAPPDATA"] = tmp
        items = installed._from_dirs()
        vers = [x["version"] for x in items]
        check("扫描到 install.json 里的版本", "1.6" in vers, vers)
        check("扫描到老目录文件名里的版本", "1.5" in vers, vers)
        check("没把 Programs 本身当安装目录",
              all(os.path.basename(x["dir"]) != "Programs" for x in items), items)

        # 去重只看注入数据：临时屏蔽真实注册表，避免本机已装版本混进来
        real_reg = installed._from_registry
        installed._from_registry = lambda: []
        try:
            merged = installed.scan_installed()
            latest = installed.latest_installed()
        finally:
            installed._from_registry = real_reg
        counts = {}
        for x in merged:
            counts[x["version"]] = counts.get(x["version"], 0) + 1
        check("同版本只保留一条", all(v == 1 for v in counts.values()), counts)
        check("按版本从新到旧排序",
              [x["version"] for x in merged] == sorted(
                  [x["version"] for x in merged],
                  key=installed.parse_version, reverse=True),
              [x["version"] for x in merged])
        check("取到最高已装版本", latest and latest["version"] == "1.6",
              latest and latest["version"])
    finally:
        if old_env is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)

    # 6) 真实本机探测不得抛异常，且结论自洽
    try:
        real = installed.scan_installed()
        ok = isinstance(real, list)
    except Exception as ex:            # noqa: BLE001
        real, ok = "%s: %s" % (type(ex).__name__, ex), False
    check("真实注册表/目录探测不抛异常", ok, real)
    real_cmp = installed.compare(APP_VERSION)
    check("真实场景结论类型合法",
          real_cmp["kind"] in ("fresh", "upgrade", "same", "downgrade"), real_cmp["kind"])
    check("真实场景 new 版本正确", real_cmp["new"] == APP_VERSION, real_cmp["new"])

    report["passed"] = not report["errors"]
    report["env"] = {"real_installed": real if ok else [], "verdict": real_cmp}
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "installed_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
