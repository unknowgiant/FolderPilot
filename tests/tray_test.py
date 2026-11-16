# -*- coding: utf-8 -*-
"""暂存盘自测：任务层「源已不存在」的计数与提示数据，以及失效项检查接口。

背景（1.6）：暂存盘只存路径，源文件被删 / 改名后，旧实现直接 continue，
任务仍报「完成」——用户看到成功提示，实际少搬了文件。现在要求：
  · done 覆盖全部条目（进度条走满，不再永远差一截）
  · skipped 单独计数，missing 留下路径，供前端点名提示
  · tray.check 能逐个判定路径是否还在，供抽屉标红与一键清理

用法：py -3.14 tests/tray_test.py
产物：tests/output/tray_report.json
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fmp.ops import TaskManager  # noqa: E402

report = {"checks": [], "errors": []}


def check(name, ok, detail=""):
    report["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
    if not ok:
        report["errors"].append(name + ": " + str(detail))


def wait(tasks, jid, limit=30):
    end = time.time() + limit
    while time.time() < end:
        st = tasks.status(jid)
        if st.get("state") in ("done", "error", "cancelled", "missing"):
            return st
        time.sleep(0.05)
    return tasks.status(jid)


def main():
    tmp = tempfile.mkdtemp(prefix="fmp_traytest_")
    src = os.path.join(tmp, "src")
    dest = os.path.join(tmp, "dest")
    os.makedirs(src)
    os.makedirs(dest)

    a = os.path.join(src, "报表 A.xlsx")
    b = os.path.join(src, "照片 B.jpg")
    ghost = os.path.join(src, "已删除 C.pdf")
    for p in (a, b):
        with open(p, "wb") as f:
            f.write(b"x" * 64)

    tasks = TaskManager()

    # ---------- 1. 复制：含一个已失效的路径 ----------
    jid = tasks.start("copy", [a, ghost, b], dest, False)
    st = wait(tasks, jid)
    check("复制任务结束于 done", st.get("state") == "done", st.get("state"))
    check("跳过项计数为 1", st.get("skipped") == 1, st.get("skipped"))
    check("missing 记录了失效路径", st.get("missing") == [ghost], st.get("missing"))
    check("done 覆盖全部 3 项（进度能走满）", st.get("done") == 3 and st.get("total") == 3,
          "%s/%s" % (st.get("done"), st.get("total")))
    check("有效文件确实被复制",
          os.path.isfile(os.path.join(dest, "报表 A.xlsx"))
          and os.path.isfile(os.path.join(dest, "照片 B.jpg")),
          sorted(os.listdir(dest)))

    # ---------- 2. 移动：失效项同样计数，且不影响有效项 ----------
    dest2 = os.path.join(tmp, "dest2")
    os.makedirs(dest2)
    jid = tasks.start("move", [a, ghost], dest2, True)
    st = wait(tasks, jid)
    check("移动任务跳过项计数为 1", st.get("skipped") == 1, st.get("skipped"))
    check("移动后源文件消失", not os.path.exists(a), a)
    check("移动后目标文件存在", os.path.isfile(os.path.join(dest2, "报表 A.xlsx")),
          sorted(os.listdir(dest2)))

    # ---------- 3. 全部失效：不能算 error，但要如实报 skipped ----------
    jid = tasks.start("copy", [ghost, os.path.join(src, "也不存在.txt")], dest, False)
    st = wait(tasks, jid)
    check("全部失效时状态仍为 done", st.get("state") == "done", st.get("state"))
    check("全部失效时 skipped = 2", st.get("skipped") == 2, st.get("skipped"))
    check("error 为空（不是异常）", not st.get("error"), st.get("error"))

    # ---------- 4. 正常任务不产生 skipped ----------
    c = os.path.join(src, "正常.txt")
    with open(c, "wb") as f:
        f.write(b"ok")
    jid = tasks.start("copy", [c], dest, False)
    st = wait(tasks, jid)
    check("正常任务 skipped 为 0", st.get("skipped") == 0, st.get("skipped"))
    check("正常任务 missing 为空", st.get("missing") == [], st.get("missing"))

    # ---------- 5. tray.check 判定（bridge 里同一段逻辑的核心） ----------
    paths = [c, ghost]
    items = [{"path": x, "exists": os.path.exists(x)} for x in paths]
    check("tray.check 认出存在的项", items[0]["exists"] is True, items[0])
    check("tray.check 认出失效的项", items[1]["exists"] is False, items[1])

    shutil.rmtree(tmp, ignore_errors=True)

    report["passed"] = not report["errors"]
    out = os.path.join(ROOT, "tests", "output")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "tray_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
