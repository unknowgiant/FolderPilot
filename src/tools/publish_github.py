# -*- coding: utf-8 -*-
"""把当前版本同步到 GitHub：源码提交 + 打 tag + 建 Release + 传两个 exe。

用法：
    py src/tools/publish_github.py --dry-run     只看会做什么，不写不改
    py src/tools/publish_github.py               正式发布
    py src/tools/publish_github.py --work D:\\path  指定仓库工作副本

前置：
    · 版本号已递增（否则 release_guard 会拒绝，先跑 bump_version.py --minor）
    · 便携版与安装版 exe 已构建在项目上一级目录
    · 本机有 GitHub 凭证（git credential 可填出 token）

做什么：
    1. 校验版本状态（源码改过却没升版 → 直接退出）
    2. 同步 src / tests / 文档到仓库工作副本，旧版 1.0 归入 legacy-1.0
    3. commit + push
    4. 创建 Release vX.Y（不存在时），上传 portable / Setup 两个 exe
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

TOOLS = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(TOOLS)
ROOT = os.path.dirname(SRC)

sys.path.insert(0, TOOLS)
sys.path.insert(0, SRC)

import release_guard  # noqa: E402
from fmp.version import (APP_VERSION, ASSET_PORTABLE, ASSET_SETUP,  # noqa: E402
                         EXE_NAME, SETUP_NAME)

OWNER, REPO = "unknowgiant", "FolderPilot"
DEFAULT_WORK = r"E:\软件开发\_publish_FolderPilot"
# 文档都在项目根，不在 src/ 下（曾经误用 SRC 拼路径，导致文档全被跳过，
# 而 LEGACY 又把根目录的 README/使用说明搬进了 legacy-1.0 —— 已修）。
FILES = ["使用说明.txt", "更新日志.txt", "架构与修复说明.txt", "版本信息.txt",
         "启动-文件管理多面手.bat"]
# 只搬 1.0 专有的旧文件。README.md / 使用说明.txt 是当前版本的文档，
# 不能进这个清单，否则每发布一次就把现役文档搬去存档。
LEGACY = [("FolderPilot.pyw", "FolderPilot.pyw"),
          ("启动 FolderPilot.bat", "启动 FolderPilot.bat")]


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit("命令失败：%s\n%s\n%s" % (" ".join(cmd), r.stdout, r.stderr))
    return r


def token() -> str:
    env = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    r = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith("password="):
            return line[9:].strip()
    raise SystemExit("拿不到 GitHub 凭证：请先 git push 一次，或设置 GH_TOKEN")


def api(method, path, payload=None, tok=None, base="https://api.github.com"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", "token " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit("GitHub API %s %s → %s\n%s"
                         % (method, path, e.code, e.read().decode("utf-8", "replace")[:400]))


def copy_tree(src, dst, skip_top):
    if not os.path.isdir(src):
        # os.walk 对不存在的目录一声不响地什么都不做，静默漏传最难查
        raise SystemExit("源目录不存在：%s" % src)
    for base, dirs, names in os.walk(src):
        rel = os.path.relpath(base, src).replace("\\", "/")
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")
                   and (d if rel == "." else rel + "/" + d) not in skip_top]
        for n in names:
            if n.endswith((".pyc", ".pyo", ".log")):
                continue
            s = os.path.join(base, n)
            t = os.path.join(dst, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(t), exist_ok=True)
            shutil.copy2(s, t)


def sync(work: str, dry: bool) -> None:
    if not os.path.isdir(os.path.join(work, ".git")):
        if dry:
            print("  [dry] 工作副本不存在，正式运行时会 clone：%s" % work)
            return
        os.makedirs(os.path.dirname(work), exist_ok=True)
        run(["git", "clone", "https://github.com/%s/%s.git" % (OWNER, REPO), work])

    legacy = os.path.join(work, "legacy-1.0")
    if not dry:
        os.makedirs(legacy, exist_ok=True)
        for old, new in LEGACY:
            p = os.path.join(work, old)
            if os.path.isfile(p):
                shutil.move(p, os.path.join(legacy, new))

    if dry:
        print("  [dry] 将同步 src/ tests/ licenses/ 与 %d 份文档" % len(FILES))
        return
    copy_tree(os.path.join(ROOT, "src"), os.path.join(work, "src"), {"tests"})
    copy_tree(os.path.join(ROOT, "tests"), os.path.join(work, "tests"), {"output"})
    copy_tree(os.path.join(ROOT, "licenses"), os.path.join(work, "licenses"), set())
    for f in FILES:
        s = os.path.join(ROOT, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(work, f))
        else:
            raise SystemExit("源工程缺少文档：%s —— 发布前请先补齐，别让仓库里的"
                             "文档停在上一版" % s)


def to_md(section: str) -> str:
    """把更新日志里「  · …」样式的纯文本段落转成 Markdown 列表。"""
    out = []
    for line in section.splitlines():
        s = line.rstrip()
        t = s.strip()
        if not t:
            out.append("")
            continue
        if t in ("新增", "修复", "变更", "移除", "已知问题", "说明"):
            out.append("\n### " + t)
            continue
        if t.startswith("·"):
            out.append("- " + t.lstrip("· ").strip())
        elif s.startswith(("    ", "\t")) and out and out[-1].startswith("- "):
            out[-1] += "<br>" + t      # 续行保留换行，避免拼成一大段
        else:
            out.append(t)
    text = "\n".join(out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def release_body(tok: str) -> str:
    log = os.path.join(ROOT, "更新日志.txt")
    section = ""
    try:
        text = open(log, encoding="utf-8").read()
        m = re.search(r"^## %s[^\n]*\n-+\n(.*?)(?=\n-{10,}|\Z)" % re.escape(APP_VERSION),
                      text, re.S | re.M)
        if m:
            section = to_md(m.group(1))
    except OSError:
        pass
    head = ("## 文件管理多面手 %s\n\n"
            "Windows 多窗格文件管理器，免安装单文件。下载后双击即可运行"
            "（Win10 1903+ / Win11 64 位，需 WebView2）。\n\n"
            "版本号不写在文件名里：下载后右键 → 属性 → 详细信息，"
            "「文件版本」即本版号；程序内标题栏与「关于」也能看到。\n\n"
            "| 下载 | 说明 |\n| --- | --- |\n"
            "| `%s` | 便携版，不写注册表 |\n"
            "| `%s` | 安装版，可就地升级（安装时会显示版本对比） |\n\n"
            % (APP_VERSION, ASSET_PORTABLE, ASSET_SETUP))
    return head + section


def publish(work: str, dry: bool, tok: str) -> None:
    ver = APP_VERSION
    tag = "v" + ver

    st = release_guard.status()
    if st["state"] == "stale-version":
        if not dry:
            print("拒绝发布：源码改动 %d 个文件但版本号仍是 %s。" % (len(st["changed"]), ver))
            print("先执行 py src/tools/bump_version.py --minor")
            raise SystemExit(3)
        print("  ! 注意：源码已改动而版本号未变，正式发布会拒绝（需先 --minor）")

    exe = os.path.join(ROOT, EXE_NAME)
    setup = os.path.join(ROOT, SETUP_NAME)
    for p in (exe, setup):
        if not os.path.isfile(p):
            raise SystemExit("缺少产物：%s（先跑 build.py / build_setup.py）" % p)

    print("[1/4] 同步源码到工作副本")
    sync(work, dry)

    print("[2/4] 提交并推送")
    if dry:
        print("  [dry] git add -A && commit && push origin main")
    else:
        run(["git", "add", "-A"], cwd=work)
        r = run(["git", "status", "--porcelain"], cwd=work)
        if r.stdout.strip():
            run(["git", "commit", "-m", "发布 %s" % ver], cwd=work)
            print("  已提交 %d 个变更" % len(r.stdout.strip().splitlines()))
        else:
            print("  源码无变化，跳过提交")
        run(["git", "push", "origin", "HEAD:main"], cwd=work)
        print("  已推送 main")

    print("[3/4] Release %s" % tag)
    if dry:
        print("  [dry] 不存在则创建 Release 并上传两个 exe")
        return
    rel = api("GET", "/repos/%s/%s/releases/tags/%s" % (OWNER, REPO, tag), tok=tok)
    if rel is None:
        head = api("GET", "/repos/%s/%s/commits/main" % (OWNER, REPO), tok=tok)
        rel = api("POST", "/repos/%s/%s/releases" % (OWNER, REPO), {
            "tag_name": tag, "target_commitish": head["sha"],
            "name": "文件管理多面手 %s" % ver, "body": release_body(tok),
            "draft": False, "prerelease": False}, tok=tok)
        print("  已创建：", rel["html_url"])
    else:
        print("  Release 已存在：", rel["html_url"])

    print("[4/4] 上传安装包")
    up = rel["upload_url"].split("{")[0]
    have = {a["name"] for a in rel.get("assets", [])}
    plan = [(exe, ASSET_PORTABLE), (setup, ASSET_SETUP)]
    for path, name in plan:
        if name in have:
            print("  已存在，跳过：", name)
            continue
        size = os.path.getsize(path)
        print("  上传 %s（%.1f MB）…" % (name, size / 1048576), flush=True)
        req = urllib.request.Request(up + "?name=" + urllib.parse.quote(name),
                                     data=open(path, "rb").read(), method="POST")
        req.add_header("Authorization", "token " + tok)
        req.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(req, timeout=600) as r:
            print("   ok", json.load(r)["browser_download_url"])

    print("\n完成：https://github.com/%s/%s/releases/tag/%s" % (OWNER, REPO, tag))


def main(argv) -> int:
    dry = "--dry-run" in argv
    work = DEFAULT_WORK
    if "--work" in argv:
        work = argv[argv.index("--work") + 1]
    print("版本 %s → %s%s" % (APP_VERSION, work, "（dry-run）" if dry else ""))
    publish(work, dry, "" if dry else token())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
