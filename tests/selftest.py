# -*- coding: utf-8 -*-
"""后端自检（无需图形界面）：重点验证「搜索结果路径可直接打开」这一契约。

用法：py -3.14 tests/selftest.py
产物：tests/output/backend_report.json
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from fmp.bridge import Bridge                     # noqa: E402
from fmp.config import Config                    # noqa: E402
from fmp.model import FileEntry, long_path       # noqa: E402
from fmp.ops import TaskManager                  # noqa: E402
from fmp.search import SearchService             # noqa: E402
from fmp.server import UIServer                  # noqa: E402
from fmp import fs                               # noqa: E402
from fmp.version import APP_TITLE, APP_VERSION    # noqa: E402

report = {"checks": [], "errors": []}
def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def main():
    tmp = tempfile.mkdtemp(prefix="fmp10_selftest_")
    # 复现用户场景：中文长名 + 多层嵌套 + 关键字命中
    deep = os.path.join(tmp, "8、2024年高价值宽带用户覆盖提升工程", "1、施工图设计",
                        "第一批设计", "快扩", "家客")
    os.makedirs(deep, exist_ok=True)
    files = [
        os.path.join(deep, "伊川扩容施工图说明.docx"),
        os.path.join(deep, "伊川材料表.xlsx"),
        os.path.join(tmp, "2、2025年商宽带一期工程-第二批施工图设计-单段落资料-伊川.txt"),
    ]
    for p in files:
        with open(long_path(p), "w", encoding="utf-8") as f:
            f.write("伊川 test content")

    cfg = Config(os.path.join(tmp, "cfg"))
    check("首次启动即生成配置文件", os.path.isfile(cfg.path))
    # 列宽 / 窗格比例 / 名称显示偏好需要能跨会话持久化
    cfg.patch({"colw": {"name": 700, "size": 110, "mtime": 146, "type": 108},
               "pane_ratio": 65, "name_only": True, "name_wrap": True})
    reloaded = Config(os.path.join(tmp, "cfg")).load()
    check("列宽与窗格偏好可持久化", reloaded.get("pane_ratio") == 65 and
          reloaded.get("colw", {}).get("name") == 700 and
          reloaded.get("name_only") is True and reloaded.get("name_wrap") is True,
          json.dumps({k: reloaded.get(k) for k in ("colw", "pane_ratio", "name_only", "name_wrap")},
                     ensure_ascii=False))

    svc = SearchService(cfg, os.path.join(SRC, "assets"), cfg.dir)
    svc.sdk.available = lambda: False           # 强制走本地兜底，模拟未装 Everything
    svc.http.probe = lambda: False
    svc.http.base = ""

    # 1) 目录列表
    listing = fs.list_dir(tmp, True)
    check("目录列表返回 FileEntry", all(isinstance(x, FileEntry) for x in listing))
    check("目录列表路径为绝对路径", all(os.path.isabs(x.path) for x in listing), len(listing))

    # 2) 文件夹内搜索：每条结果必须存在、带相对路径、来源一致
    t0 = time.time()
    r = svc.run({"query": "伊川", "scope": "folder", "root": tmp, "limit": 200})
    first_ms = int((time.time() - t0) * 1000)
    check("文件夹内搜索命中", r["total"] > 0, f"total={r['total']} backend={r['backend']}")
    ok = True
    for e in r["entries"]:
        ok &= os.path.isfile(long_path(e["path"]))
        ok &= bool(e["rel"])
        ok &= e["path"].lower().startswith(tmp.lower())
    check("每条搜索结果都是可直接打开的真实路径", ok,
          r["entries"][0]["path"] if r["entries"] else "无结果")
    check("本地兜底后端标注正确", r["backend"] == "本地索引", r["backend"])

    # 3) 同目录二次搜索应命中缓存
    t0 = time.time()
    r2 = svc.run({"query": "材料表", "scope": "folder", "root": tmp, "limit": 200})
    second_ms = int((time.time() - t0) * 1000)
    check("文件夹扫描缓存生效", second_ms <= first_ms + 20, f"{first_ms}ms -> {second_ms}ms")
    check("缓存后结果路径依然有效", all(os.path.isfile(long_path(e["path"])) for e in r2["entries"]))

    # 4) 全局范围（本地索引）同样产出绝对路径
    rg = svc.run({"query": "伊川", "scope": "global", "limit": 50})
    check("全局搜索返回结构一致", all("path" in e and "name" in e for e in rg["entries"]),
          f"backend={rg['backend']} total={rg['total']}")

    # 5) 超长路径（>260 字符）能被扫描且路径可还原
    very_deep = tmp
    for i in range(9):
        very_deep = os.path.join(very_deep, "深层目录%02d_中文名称占位内容" % i)
    os.makedirs(long_path(very_deep), exist_ok=True)
    lp = os.path.join(very_deep, "伊川超长路径验证.txt")
    with open(long_path(lp), "w", encoding="utf-8") as f:
        f.write("ok")
    svc.local._folder_cache.clear()
    rl = svc.run({"query": "伊川超长路径", "scope": "folder", "root": tmp, "limit": 200})
    check("超长中文路径可被搜索", any(os.path.isfile(long_path(e["path"])) for e in rl["entries"]),
          f"len={len(lp)} hits={rl['total']}")

    # 6) Bridge 命令路由
    b = Bridge(cfg, svc, TaskManager()).setup()
    def call(m, p=None):
        return json.loads(b.call(m, json.dumps(p or {}, ensure_ascii=False)))
    info = call("app.info")
    check("app.info 返回项目信息",
          info["ok"] and info["data"]["version"] == APP_VERSION
          and info["data"]["name"] == APP_TITLE,
          "%s / %s" % (info.get("data", {}).get("name"), info.get("data", {}).get("version")))
    d = call("dir.list", {"path": tmp, "show_hidden": True})
    check("bridge dir.list 可用", d["ok"] and d["data"]["count"] >= 3)
    s = call("search.run", {"query": "伊川", "scope": "folder", "root": tmp, "limit": 50})
    check("bridge search.run 可用", s["ok"] and all(os.path.isfile(long_path(e["path"])) for e in s["data"]["entries"]))
    nd = call("ops.mkdir", {"parent": tmp, "name": "自检新建文件夹"})
    check("新建文件夹可用", nd["ok"] and os.path.isdir(long_path(nd["data"]["path"])))
    rn = call("ops.rename", {"path": nd["data"]["path"], "name": "自检重命名"})
    check("重命名可用", rn["ok"] and os.path.isdir(long_path(rn["data"]["path"])))
    st = call("state.set", {"patch": {"selftest": True}})
    check("状态持久化可用", st["ok"] and cfg.get("selftest") is True)
    bad = call("no.such.command")
    check("未知命令返回结构化错误", (not bad["ok"]) and "error" in bad)

    # 7) 传输层：静态资源 + token 注入 + 文件流
    token = "selftest-token-123"
    server = UIServer(os.path.join(SRC, "ui"), token, long_path, api_handler=b.call)
    try:
        html = urllib.request.urlopen(server.url, timeout=5).read().decode("utf-8")
        check("首页注入随机 token", token in html and "__FMP_TOKEN__" not in html)
        # 版本占位符必须被替换，否则界面会露出 __FMP_VERSION__
        check("首页注入版本与标题",
              "__FMP_VERSION__" not in html and "__FMP_TITLE__" not in html
              and '<span class="brand-ver">%s</span>' % APP_VERSION in html
              and "<title>%s</title>" % APP_TITLE in html,
              APP_TITLE)
        css = urllib.request.urlopen(server.url + "app.css", timeout=5).read()
        check("样式资源可访问", len(css) > 10000, len(css))
        denied = False
        try:
            urllib.request.urlopen(server.url + "file?p=" + files[0], timeout=5)
        except Exception:
            denied = True
        check("文件流拒绝无 token 访问", denied)
        data = urllib.request.urlopen(server.url + "file?p=" +
                                      urllib.parse.quote(files[0]) + "&t=" + token, timeout=5).read()
        check("文件流按 token 正常输出", data.startswith(b"\xe4\xbc\x8a\xe5\xb7\x9d") or len(data) > 0, len(data))
        req = urllib.request.Request(
            server.url + "api?t=" + token,
            data=json.dumps({"method": "dir.list", "params": {"path": tmp}}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        ar = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        check("HTTP 命令通道可用（不依赖 js_api）",
              bool(ar.get("ok")) and ar.get("data", {}).get("count", 0) >= 3)
        no_token = False
        try:
            urllib.request.urlopen(server.url + "api?m=app.info", timeout=5)
        except Exception:
            no_token = True
        check("命令通道拒绝无 token 访问", no_token)
    finally:
        server.stop()

    report["passed"] = not report["errors"]
    report["tmp_dir"] = tmp
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "backend_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    import urllib.parse  # noqa: E402
    sys.exit(main())
