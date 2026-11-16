# -*- coding: utf-8 -*-
"""内置搜索引擎（随包 Everything 内核）回归测试。

验证点：
  1. 内核三件套能从 assets 释放到数据目录（exe / dll / 私有 ini / 许可证）
  2. 私有 ini 是便携模式（app_data=0）且隐形（show_tray_icon=0）
  3. 服务探测、提权探测不抛异常，取值在允许集合内
  4. ensure() 后 SDK 可用，全盘搜索能命中真实文件
  5. stop() 只结束我们自己启动的内核，不影响用户自己的 Everything

用法：py -3.14 tests/engine_test.py
产物：tests/output/engine_report.json
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from fmp.config import Config                        # noqa: E402
from fmp.engine import EngineManager, service_state  # noqa: E402
from fmp.search import SearchService                 # noqa: E402

ASSETS = os.path.join(SRC, "assets")
report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(f"{name}: {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="fmp_engine_")
    cfg = Config(tmp)
    cfg.set("ev_max", 100)
    svc = SearchService(cfg, ASSETS, tmp)
    eng = svc.engine

    # 1) 释放
    exe = eng.deploy()
    check("deploy.exE", bool(exe) and os.path.isfile(exe), exe)
    check("deploy.dll", os.path.isfile(os.path.join(eng.dir, "Everything64.dll")), eng.dir)
    check("deploy.ini", os.path.isfile(eng.ini), eng.ini)
    check("deploy.license", os.path.isfile(os.path.join(eng.dir, "Everything-License.txt")), "")
    ini = open(eng.ini, encoding="utf-8").read() if os.path.isfile(eng.ini) else ""
    check("ini.portable", "app_data=0" in ini, ini.replace("\n", " "))
    check("ini.hidden", "show_tray_icon=0" in ini, "")
    check("ini.no_http", "http_server_enabled=0" in ini, "")

    # 2) 系统状态探测
    st = eng.status()
    check("service.state", st["service"] in ("running", "stopped", "absent", "unknown"), st["service"])
    check("elevated.bool", isinstance(st["elevated"], bool), st["elevated"])
    check("status.keys", all(k in st for k in ("deployed", "external", "needs_auth", "label")), "")

    # 3) 确保内核可用并真搜一次
    t0 = time.time()
    st = eng.ensure(wait=12)
    ready_s = round(time.time() - t0, 2)
    # 外部 Everything 冷启动时 ensure 可能先返回「预热中」，与程序启动那几轮重试一致
    for _ in range(3):
        if st["sdk"]:
            break
        time.sleep(3)
        st = svc.connect(wait=8)
    check("ensure.sdk", st["sdk"], json.dumps(st, ensure_ascii=False)[:300])
    # 探测必须有上限：客户端启动期「窗口在但不响应」时不能把界面拖住
    t1 = time.time()
    svc.sdk.available(timeout=0.9)
    probe_s = round(time.time() - t1, 2)
    check("probe.bounded", probe_s < 1.6, f"{probe_s}s")
    backend = ""
    if st["sdk"]:
        r = svc.run({"query": "Everything.exe", "scope": "global", "limit": 20})
        backend = r["backend"]
        check("search.hits", r["total"] >= 1, f"{r['total']} 条 / {r['elapsed']}ms")
        check("search.paths", all(os.path.isabs(e["path"]) for e in r["entries"]),
              r["entries"][0]["path"] if r["entries"] else "")
        check("search.backend_label", backend in ("内置引擎", "Everything SDK", "Everything HTTP"), backend)
        # 文件夹内搜索（走同一入口）也要能用后端索引。
        # 注意：不能拿刚创建的临时目录当靶子 —— 内核靠 USN 日志增量感知新增目录，
        # 建目录后 1 秒内查不到属于正常现象，这里用已存在的工程目录。
        tdir = os.path.join(ROOT, "tests")
        r2 = {"total": 0, "entries": []}
        for _ in range(20):
            r2 = svc.run({"query": "engine_test", "scope": "folder", "root": tdir, "limit": 20})
            if r2["total"]:
                break
            time.sleep(0.5)
        check("search.folder_scope", r2["total"] >= 1 and
              all(e["path"].lower().startswith(tdir.lower()) for e in r2["entries"]),
              f"{r2['total']} 条")

    # 4) 停掉自己启动的内核；外部实例（如果用户装了）应继续可用
    external_alive = bool(st.get("external"))
    was_external = st.get("source") == "external"
    est = eng.status()          # 引擎视角的状态（st 是 SearchService.status）
    eng.stop()
    time.sleep(0.6)
    st2 = eng.status()
    check("stop.no_crash", True, "")
    if was_external and st["sdk"]:
        # 复用用户自己的 Everything 时，退出绝不能顺手把它关掉
        check("stop.keep_external", st2["sdk"], "外部 Everything 应仍在运行")
    if not external_alive:
        check("stop.released", not (eng._proc and eng._proc.poll() is None), "")
    check("stop.status_shape", "sdk" in st2, "")

    # 5) 未授权路径只能明确拒绝，不能偷偷弹 UAC
    if est["service"] != "running":
        r = eng.enable(interactive=False)
        check("enable.needs_auth_msg", "授权" in (r.get("last_error") or ""), r.get("last_error"))
    # 6) 卸装清理只针对「指向我们内核目录」的服务，别人的绝不动
    check("service.not_ours", eng.remove_service_if_ours() is False or est["service_ours"],
          f"service_ours={est['service_ours']}")

    report["summary"] = {
        "ready_seconds": ready_s, "backend": backend,
        "service": est["service"], "external": bool(est.get("external")),
        "engine_exe": exe, "tmp": tmp,
        "passed": sum(1 for c in report["checks"] if c["ok"]),
        "total": len(report["checks"]),
    }
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "engine_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    for c in report["checks"]:
        print(("PASS  " if c["ok"] else "FAIL  ") + c["name"] + ("  " + c["detail"] if c["detail"] else ""))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
