# -*- coding: utf-8 -*-
"""文件管理多面手 —— 安装向导（用户级安装，免管理员权限）。

单文件 Setup.exe 内嵌便携版主程序与说明文档；安装后写入 HKCU 卸载项，
可在 Windows「设置 → 应用」中直接卸载。卸载入口为主程序的 --uninstall 参数。
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import winreg
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fmp.version import (APP_ID, APP_TITLE, APP_VERSION, DATA_DIR_DISPLAY,  # noqa: E402
                         EXE_NAME, LEGACY_UNINSTALL_PREFIX, PROJECT_CODE,
                         SHORTCUT_NAME, UNINSTALL_KEY)

# 安装目录不带版本号：同一台机器上就地升级，只保留一份安装
INSTALL_ROOT_NAME = PROJECT_CODE

BG = "#F7F9FC"
ACC = "#4A7FD0"
TXT = "#26364C"
TXT2 = "#61758E"


def base_dir():
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
PAYLOAD = os.path.join(BASE, "payload")
DEFAULT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                           "Programs", INSTALL_ROOT_NAME)


def desktop_dir():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "Desktop")
        return os.path.expandvars(v)
    except OSError:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def start_menu_dir():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "Microsoft", "Windows", "Start Menu", "Programs")


def run_ps(script: str):
    """用 EncodedCommand 执行 PowerShell，彻底避开中文路径与引号转义问题。

    PowerShell 冷启动在低配机器或系统繁忙时可能超过 30 秒，这里给 60 秒
    并对超时重试一次：快捷方式建不出来会让安装白跑，宁可多等。
    """
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-WindowStyle", "Hidden", "-EncodedCommand", enc]
    last = None
    for attempt in range(2):
        try:
            return subprocess.run(cmd, capture_output=True,
                                  creationflags=0x08000000, timeout=60)
        except subprocess.TimeoutExpired as ex:
            last = ex
    raise last


def make_shortcuts(exe_path, install_dir, want_desktop, want_start):
    made = []
    lines = ['$ws = New-Object -ComObject WScript.Shell']
    targets = []
    if want_desktop:
        targets.append(os.path.join(desktop_dir(), SHORTCUT_NAME))
    if want_start:
        targets.append(os.path.join(start_menu_dir(), SHORTCUT_NAME))
    for lnk in targets:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        lines.append(f'$s = $ws.CreateShortcut("{lnk}")')
        lines.append(f'$s.TargetPath = "{exe_path}"')
        lines.append(f'$s.WorkingDirectory = "{install_dir}"')
        lines.append(f'$s.IconLocation = "{exe_path},0"')
        lines.append('$s.Save()')
        made.append(lnk)
    if made:
        # 让 COM 失败时直接抛错（而不是静默继续），再按「文件是否真的落地」
        # 判定成败；脚本宿主首次冷启动加载 WScript.Shell 偶尔慢到超时，故重试。
        script = "$ErrorActionPreference='Stop'\n" + "\n".join(lines)
        for _ in range(3):
            try:
                run_ps(script)
            except Exception:
                pass
            if all(os.path.isfile(p) for p in made):
                break
            time.sleep(0.5)
    return [p for p in made if os.path.isfile(p)]


def write_uninstall_entry(install_dir, exe_path, shortcuts, size_kb):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_WRITE) as k:
        vals = {
            "DisplayName": APP_TITLE, "DisplayVersion": APP_VERSION,
            "Publisher": "文件管理多面手", "InstallLocation": install_dir,
            "DisplayIcon": exe_path + ",0",
            "UninstallString": f'"{exe_path}" --uninstall',
            "URLInfoAbout": "", "HelpLink": "",
        }
        for n, v in vals.items():
            winreg.SetValueEx(k, n, 0, winreg.REG_SZ, v)
        for n, v in {"NoModify": 1, "NoRepair": 1, "EstimatedSize": int(size_kb)}.items():
            winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, v)
    manifest = {"version": APP_VERSION, "install_dir": install_dir,
                "shortcuts": shortcuts, "installed_at": datetime.datetime.now().isoformat()}
    with open(os.path.join(install_dir, "install.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _shortcut_dirs():
    return [desktop_dir(), start_menu_dir()]


def cleanup_previous_versions(install_dir, keep_exe, keep_links=()):
    """就地升级清理：旧 exe、旧快捷方式、旧注册表键、旧版本目录。

    从 1.1 起安装目录固定为 …\\Programs\\文件管理多面手（不带版本号），
    程序文件名带版本号。升级时把上一版的 exe 与快捷方式清掉，避免桌面上
    堆一串不同版本号的同名图标。只删本项目自己的东西：
      · 安装目录内形如「文件管理多面手 X.Y.exe」的文件
      · 桌面与开始菜单里以本项目名开头且以 .lnk 结尾的快捷方式
      · HKCU 卸载项里以 FileManagerMulti_ 开头的旧键
      · %LOCALAPPDATA%\\Programs\\文件管理多面手 X.Y 这类旧版本安装目录
    任何一步失败都只跳过，不影响本次安装。
    """
    removed = {"exe": [], "lnk": [], "reg": [], "dir": []}
    pat = re.compile(r"^" + re.escape(PROJECT_CODE) + r" \d+(\.\d+)*\.exe$", re.I)

    # 1) 安装目录内的旧版本主程序
    try:
        for name in os.listdir(install_dir):
            p = os.path.join(install_dir, name)
            if p == keep_exe or not pat.match(name):
                continue
            try:
                os.remove(p)
                removed["exe"].append(p)
            except OSError:
                pass
    except OSError:
        pass

    # 2) 旧快捷方式（保留本次刚建的）
    lnk_pat = re.compile(r"^" + re.escape(PROJECT_CODE) + r".*\.lnk$", re.I)
    keep = {os.path.normcase(os.path.abspath(x)) for x in keep_links}
    for d in _shortcut_dirs():
        try:
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if not lnk_pat.match(name):
                    continue
                if os.path.normcase(os.path.abspath(p)) in keep:
                    continue
                try:
                    os.remove(p)
                    removed["lnk"].append(p)
                except OSError:
                    pass
        except OSError:
            pass

    # 3) 旧版版本化卸载键（FileManagerMulti_1_0 之类）
    uninst_root = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, uninst_root) as k:
            names, i = [], 0
            while True:
                try:
                    names.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
        for name in names:
            if name.startswith(LEGACY_UNINSTALL_PREFIX):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, uninst_root + "\\" + name)
                    removed["reg"].append(name)
                except OSError:
                    pass
    except OSError:
        pass

    # 4) 旧版本安装目录（…\Programs\文件管理多面手 X.Y 这种带版本号的）
    parent = os.path.dirname(install_dir)
    dir_pat = re.compile(r"^" + re.escape(PROJECT_CODE) + r" \d+(\.\d+)*$", re.I)
    try:
        for name in os.listdir(parent):
            p = os.path.join(parent, name)
            if os.path.normcase(p) == os.path.normcase(install_dir):
                continue
            if os.path.isdir(p) and dir_pat.match(name):
                shutil.rmtree(p, ignore_errors=True)
                if not os.path.isdir(p):
                    removed["dir"].append(p)
    except OSError:
        pass

    return removed


def perform_install(install_dir, want_desktop=True, want_start=True, progress=None):
    def step(msg, pct):
        if progress:
            progress(msg, pct)
    step("正在准备安装目录…", 8)
    os.makedirs(install_dir, exist_ok=True)
    probe = os.path.join(install_dir, ".fmp_write_test")
    with open(probe, "w", encoding="utf-8") as f:
        f.write("ok")
    os.remove(probe)
    src_exe = os.path.join(PAYLOAD, EXE_NAME)
    if not os.path.isfile(src_exe):
        raise RuntimeError("安装包内缺少主程序")
    dst_exe = os.path.join(install_dir, EXE_NAME)
    if os.path.isfile(dst_exe):
        try:
            os.remove(dst_exe)
        except OSError:
            raise RuntimeError("目标程序正在运行，请先关闭它再安装")
    step("正在释放主程序…", 35)
    shutil.copy2(src_exe, dst_exe)
    step("正在复制说明与许可文件…", 60)
    for root, _, files in os.walk(PAYLOAD):
        rel = os.path.relpath(root, PAYLOAD)
        out = install_dir if rel == "." else os.path.join(install_dir, rel)
        os.makedirs(out, exist_ok=True)
        for name in files:
            if name == EXE_NAME:
                continue
            try:
                shutil.copy2(os.path.join(root, name), os.path.join(out, name))
            except OSError:
                pass
    step("正在创建快捷方式…", 78)
    shortcuts = make_shortcuts(dst_exe, install_dir, want_desktop, want_start)
    step("正在清理旧版本…", 86)
    removed = cleanup_previous_versions(install_dir, dst_exe, shortcuts)
    step("正在注册卸载信息…", 90)
    write_uninstall_entry(install_dir, dst_exe, shortcuts, os.path.getsize(dst_exe) / 1024)
    step("安装完成", 100)
    return {"install_dir": install_dir, "exe": dst_exe, "shortcuts": shortcuts,
            "removed": removed}


def silent_install():
    """无人值守安装，供自动化验证与批量部署；结果可写入 --report= 文件。"""
    d = DEFAULT_DIR
    for a in sys.argv:
        if a.startswith("--dir="):
            d = a[6:].strip('"')
    no_sc = "--no-shortcuts" in sys.argv
    result = {}
    try:
        result = perform_install(d, not no_sc, not no_sc)
        result["ok"] = True
    except Exception as ex:
        result = {"ok": False, "error": str(ex)}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    for a in sys.argv:
        if a.startswith("--report="):
            try:
                with open(a[9:].strip('"'), "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError:
                pass
    print(text)
    return 0 if result.get("ok") else 1


class Wizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE + " 安装")
        self.root.geometry("600x430")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        try:
            icon = os.path.join(PAYLOAD, "app_icon.ico")
            if os.path.isfile(icon):
                self.root.iconbitmap(default=icon)
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TButton", padding=6, font=("Microsoft YaHei UI", 10))
        style.configure("TCheckbutton", background=BG, font=("Microsoft YaHei UI", 10))
        style.configure("TProgressbar", troughcolor="#E9EFF8", background=ACC)

        head = tk.Frame(self.root, bg=ACC, height=76)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="◆", bg=ACC, fg="white", font=("Microsoft YaHei UI", 24)).pack(side="left", padx=(22, 12))
        box = tk.Frame(head, bg=ACC)
        box.pack(side="left", fill="y", pady=12)
        tk.Label(box, text=APP_TITLE, bg=ACC, fg="white",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        tk.Label(box, text="双窗格文件管理 · Everything 全盘秒搜 · 本地数据不上传",
                 bg=ACC, fg="#DCE9FA", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(2, 0))

        self.page = tk.Frame(self.root, bg=BG)
        self.page.pack(fill="both", expand=True, padx=24, pady=16)
        self.page_install()

    def page_install(self):
        for w in self.page.winfo_children():
            w.destroy()
        tk.Label(self.page, text="安装位置", bg=BG, fg=TXT,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        tk.Label(self.page, text="安装到个人目录，无需管理员权限；不会写入系统目录或开机启动项。",
                 bg=BG, fg=TXT2, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(2, 10))
        row = tk.Frame(self.page, bg=BG)
        row.pack(fill="x")
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        e = ttk.Entry(row, textvariable=self.dir_var, font=("Microsoft YaHei UI", 10))
        e.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left", padx=(8, 0))

        self.desk_var = tk.BooleanVar(value=True)
        self.start_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.page, text="创建桌面快捷方式", variable=self.desk_var,
                        style="TCheckbutton").pack(anchor="w", pady=(16, 2))
        ttk.Checkbutton(self.page, text="创建开始菜单快捷方式", variable=self.start_var,
                        style="TCheckbutton").pack(anchor="w")

        tk.Label(self.page, text="版本 " + APP_VERSION + " · Windows 10 / 11 64 位 · 依赖系统自带 WebView2",
                 bg=BG, fg=TXT2, font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(18, 0))
        self.status = tk.Label(self.page, text="", bg=BG, fg=ACC,
                               font=("Microsoft YaHei UI", 9), wraplength=540, justify="left")
        self.status.pack(anchor="w", pady=(6, 0))
        self.prog = ttk.Progressbar(self.page, mode="determinate", maximum=100)
        self.prog.pack(fill="x", pady=(6, 0))

        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=24, pady=(0, 18))
        self.btn_cancel = ttk.Button(bar, text="取消", command=self.root.destroy)
        self.btn_cancel.pack(side="right")
        self.btn_install = ttk.Button(bar, text="立即安装", command=self.install)
        self.btn_install.pack(side="right", padx=(0, 10))

    def browse(self):
        p = filedialog.askdirectory(initialdir=self.dir_var.get() or DEFAULT_DIR)
        if p:
            self.dir_var.set(os.path.normpath(p))

    def set_status(self, text, pct):
        self.status.configure(text=text)
        self.prog["value"] = pct
        self.root.update_idletasks()

    def install(self):
        d = self.dir_var.get().strip()
        if not d:
            return messagebox.showwarning("提示", "请选择安装目录", parent=self.root)
        self.btn_install.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        threading.Thread(target=self.worker, args=(d,), daemon=True).start()

    def worker(self, install_dir):
        def progress(msg, pct):
            self.root.after(0, lambda m=msg, p=pct: self.set_status(m, p))
        try:
            r = perform_install(install_dir, self.desk_var.get(), self.start_var.get(), progress)
            self.installed_exe = r["exe"]
            self.root.after(0, self.page_done)
        except Exception as ex:
            self.root.after(0, lambda: self.fail(str(ex)))

    def fail(self, msg):
        self.set_status("安装失败：" + msg, 0)
        self.btn_install.configure(state="normal")
        self.btn_cancel.configure(state="normal")
        messagebox.showerror("安装失败", msg, parent=self.root)

    def page_done(self):
        for w in self.page.winfo_children():
            w.destroy()
        tk.Label(self.page, text="✓ 安装完成", bg=BG, fg="#2F8F63",
                 font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(12, 8))
        tk.Label(self.page, text="安装位置：" + os.path.dirname(self.installed_exe),
                 bg=BG, fg=TXT, font=("Microsoft YaHei UI", 10), wraplength=540,
                 justify="left").pack(anchor="w")
        tk.Label(self.page,
                 text="已在 Windows「设置 → 应用」中登记，可随时一键卸载。\n"
                      "个人数据保存在 " + DATA_DIR_DISPLAY + "，卸载不会删除。",
                 bg=BG, fg=TXT2, font=("Microsoft YaHei UI", 9), justify="left",
                 wraplength=540).pack(anchor="w", pady=(14, 0))
        self.run_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.page, text="立即运行 " + APP_TITLE,
                        variable=self.run_var, style="TCheckbutton").pack(anchor="w", pady=(20, 0))
        self.btn_install.configure(text="完成", state="normal", command=self.finish)
        self.btn_cancel.configure(state="normal", command=self.finish)

    def finish(self):
        if getattr(self, "run_var", None) and self.run_var.get():
            try:
                subprocess.Popen([self.installed_exe], cwd=os.path.dirname(self.installed_exe))
            except Exception:
                pass
        self.root.destroy()


def main():
    if "--silent" in sys.argv:
        return silent_install()
    Wizard().root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
