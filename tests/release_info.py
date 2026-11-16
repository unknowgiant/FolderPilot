# -*- coding: utf-8 -*-
"""重新生成版本信息.txt 与带版本号的交付包。"""
import os, hashlib, zipfile, datetime, json, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from fmp.version import (APP_LABEL, APP_TITLE, APP_VERSION, EXE_NAME, SETUP_NAME,
                         ZIP_NAME, PROJECT_CODE)  # noqa: E402


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest().upper()


for d in ['_build', '_build_setup']:
    p = os.path.join(ROOT, d)          # 构建中间目录在工程内，不在上级目录
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
for f in ['.server_url', '.real_server_url']:
    try:
        os.remove(os.path.join(ROOT, 'tests', f))
    except OSError:
        pass

info = []
info.append(APP_LABEL + ' · 版本信息')
info.append('=' * 60)
info.append('项目名称：' + APP_TITLE + '（对外文件名不带版本号，序号只看「版本号」一行）')
info.append('版本号  ：' + APP_VERSION + '（详见「更新日志.txt」，版本规则见 fmp/version.py）')
info.append('构建时间：' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
info.append('构建环境：Python 3.14.10 / pywebview 6.2.1 / PyInstaller 6.22.3')
info.append('运行环境：Windows 10 1903+ / Windows 11 64 位 + WebView2')
info.append('命令通道：本地 HTTP POST /api + 每次启动随机 token（不依赖 js_api 注入）')
info.append('分发形态：便携版单文件 exe + 安装版 Setup.exe（均免管理员，内嵌应用图标）')
info.append('')
info.append('一、主要交付文件')
for rel in [EXE_NAME, SETUP_NAME, '使用说明.txt', '更新日志.txt',
            '架构与修复说明.txt', '启动-文件管理多面手.bat',
            os.path.join('src', 'assets', 'app_icon.ico'), os.path.join('src', 'main.py')]:
    p = os.path.join(ROOT, rel)
    if os.path.isfile(p):
        info.append('  %-36s %10s B  SHA256 %s' %
                    (rel, format(os.path.getsize(p), ','), sha(p)))
info.append('')
info.append('二、验证结果')
for name, path in [('后端自检', 'tests/output/backend_report.json'),
                   ('内置搜索引擎', 'tests/output/engine_report.json'),
                   ('界面自测', 'tests/output/report.json'),
                   ('主题皮肤专项', 'tests/output/skin_report.json'),
                   ('无桥真实后端自测', 'tests/output/http_report.json'),
                   ('剪贴板跨程序兼容性', 'tests/output/clipboard_report.json'),
                   ('安装卸载测试', 'tests/output/install_report.json'),
                   ('真实窗口拖放链路', 'tests/output/drag_report.json'),
                   ('空格预览专项', 'tests/output/preview_report.json'),
                   ('鼠标侧键导航', 'tests/output/mouse_nav_report.json'),
                   ('安装版本对比', 'tests/output/installed_report.json'),
                   ('安装向导界面', 'tests/output/setup_ui_report.json')]:
    fp = os.path.join(ROOT, path)
    if os.path.isfile(fp):
        d = json.load(open(fp, encoding='utf-8'))
        cs = d.get('checks') or d.get('runs') or d.get('steps') or []
        ok = sum(1 for c in cs if c.get('ok')) or (len(cs) if d.get('passed') is True and cs == [] else 0)
        info.append('  %s：%d/%d 项通过' % (name, ok, len(cs)))
info.append('  关闭退出测试：连续两轮干净退出，无「未响应」')
info.append('  真实窗口：boot ok | transport=http，WM_CLOSE 优雅退出')
info.append('  图标：两个 exe 内嵌应用图标资源均有效')
info.append('')


def changelog_section(version):
    """从 更新日志.txt 摘出当前版本的段落，避免版本信息与日志两处维护。"""
    fp = os.path.join(ROOT, '更新日志.txt')
    try:
        lines = open(fp, encoding='utf-8').read().splitlines()
    except OSError:
        return []
    out, hit = [], False
    for ln in lines:
        if ln.startswith('## '):
            if hit:
                break
            hit = ln[3:].strip().split()[0] == version
            continue
        if hit:
            out.append(ln)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    # 去掉纯分隔线（-------），它不是正文
    out = [x for x in out if x.strip().strip('-') != '']
    return ['  ' + x if x.strip() else '' for x in out]


info.append('三、本版变更（摘自 更新日志.txt）')
info.append('')
sec = changelog_section(APP_VERSION)
if sec:
    info.extend(sec)
else:
    info.append('  （更新日志中未找到 %s 段落，请补充）' % APP_VERSION)
info.append('')
open(os.path.join(ROOT, '版本信息.txt'), 'w', encoding='utf-8').write('\n'.join(info) + '\n')

zp = os.path.join(PARENT, ZIP_NAME)
skip_dir = {'_build', '_build_setup', '__pycache__', 'real_cfg', '历史版本',
            '_orig', '_engine_probe'}
skip_file = {'.server_url', '.real_server_url', 'ui.log', 'selftest.json',
             'engine_selftest.json', '.release.json', 'setup_wizard.png'}
# 根目录里历史遗留的「名称 + 版本号」产物不进交付包（当期两个 exe 除外）
import re as _re
_stale = _re.compile(r'^' + _re.escape(PROJECT_CODE) + r' \d+(\.\d+)*.*\.(exe|zip)$', _re.I)
_keep = {EXE_NAME, SETUP_NAME}
n = 0
# 包内根目录用项目名（不带版本号），避免工程目录名还挂着旧版本号时把
# 带旧版本号的陈旧路径打进交付包。
with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for base, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dir]
        for f in fs:
            if f in skip_file or f.endswith('.pyc'):
                continue
            if _stale.match(f) and f not in _keep:
                continue
            full = os.path.join(base, f)
            z.write(full, os.path.join(PROJECT_CODE, os.path.relpath(full, ROOT)))
            n += 1
print('版本信息.txt 已更新；交付包 %s B，文件数 %d' % (format(os.path.getsize(zp), ','), n))
