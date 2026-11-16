# -*- coding: utf-8 -*-
"""版本号唯一来源。

版本规则（自 1.0 起，详见项目根目录「更新日志.txt」）：

    常规更新（新增功能 / 修复 / 打磨）   → 次版本 +1：1.0 → 1.1 → 1.2 …
    大版本重构、破坏性变更              → 主版本 +1 且次版本归零：1.x → 2.0

约定：**只改这一个文件的 APP_VERSION**，其余一切（窗口标题、exe 文件名、
安装目录、快捷方式、注册表卸载项、交付包名、界面显示）都由它派生。
改完运行 tools/bump_version.py --check 做一致性自检。

不要在任何模块里写死版本号；需要版本相关字符串时从这里导入。

命名规则（用户 2026-11-16 定）：**版本号不进名字**。
    文件名 / 快捷方式 / 窗口标题 / 卸载项 一律只用「文件管理多面手」，
    版本号放到「软件包里」——exe 的文件版本属性、界面品牌处、关于信息、
    安装向导里的版本对比。这样桌面上永远不会堆出 1.3 / 1.4 / 1.5 一串图标，
    而看一眼程序内部就 still 知道装的是哪一版。
"""
from __future__ import annotations

APP_VERSION = "1.7"
APP_ID = "FileManagerMulti"
PROJECT_CODE = "文件管理多面手"

# 主/次版本：用户数据按主版本归档，1.x 系列共用同一份配置
_parts = APP_VERSION.split(".")
MAJOR = int(_parts[0])
MINOR = int(_parts[1]) if len(_parts) > 1 else 0

# 对外名称：不含版本号（exe / 快捷方式 / 窗口标题 / 卸载项共用）
APP_TITLE = PROJECT_CODE                              # 窗口标题 / 品牌名
# 需要「名称 + 版本」一起出现时用它（安装向导、About、exe 版本资源）
APP_LABEL = f"{PROJECT_CODE} {APP_VERSION}"
EXE_NAME = f"{APP_TITLE}.exe"                         # 便携版
SETUP_NAME = f"{APP_TITLE}-Setup.exe"                 # 安装版
ZIP_NAME = f"{APP_TITLE}-交付包.zip"                   # 交付包（放上级目录）
SHORTCUT_NAME = f"{APP_TITLE}.lnk"                    # 桌面 / 开始菜单快捷方式
# 绿色版 / 安装版在 GitHub Release 上的资产名（ASCII，GitHub 会吃掉中文）
ASSET_PORTABLE = "FolderPilot-portable.exe"
ASSET_SETUP = "FolderPilot-Setup.exe"

# 用户数据目录：%APPDATA%\FileManagerMulti\v1（1.0 与 1.1 共用，升级不丢设置）
DATA_SERIES = f"v{MAJOR}"
DATA_DIR_DISPLAY = rf"%APPDATA%\{APP_ID}\{DATA_SERIES}"

# 注册表：用固定键做就地升级，「设置 → 应用」里只留一个条目，
# DisplayVersion 随版本变化。旧版按版本号建的键会被安装器清理。
UNINSTALL_KEY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
LEGACY_UNINSTALL_PREFIX = APP_ID + "_"

__all__ = [
    "APP_VERSION", "APP_ID", "PROJECT_CODE", "APP_TITLE", "APP_LABEL",
    "EXE_NAME", "SETUP_NAME", "ZIP_NAME", "SHORTCUT_NAME",
    "ASSET_PORTABLE", "ASSET_SETUP", "MAJOR", "MINOR",
    "DATA_SERIES", "DATA_DIR_DISPLAY", "UNINSTALL_KEY", "LEGACY_UNINSTALL_PREFIX",
]
