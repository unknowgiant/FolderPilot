# 文件管理多面手（FolderPilot）

Windows 桌面多窗格文件管理器，Python + pywebview 单文件应用。**当前版本 1.5**。

免安装、单文件 exe，内置 Everything 搜索引擎（无需另装），启动即用。

## 下载

到 [Releases](../../releases) 下载最新版：

| 文件 | 说明 |
| --- | --- |
| `FolderPilot-1.5-portable.exe` | 便携版，双击即用，不写注册表 |
| `FolderPilot-1.5-Setup.exe` | 安装版，写入开始菜单与卸载项，可就地升级 |

文件名用 ASCII 是为了在各系统下载时不乱码，下载后可自行改回「文件管理多面手 1.5.exe」，不影响运行。

运行环境：Windows 10 1903+ / Windows 11 64 位，需系统自带 WebView2（Win11 默认已装）。

## 功能

- **五种布局**：单栏 / 左右分屏 / 上下分屏 / 三栏 / 四宫格（Ctrl+1~5）
- **多标签**：每个窗格独立标签页，会话自动恢复，视图与排序按目录记忆
- **双重搜索**：全盘搜索（Ctrl+F / Alt+Space 命令面板）+ 文件夹内搜索，共用结果管线，可一键互转范围；支持类型、大小区间、区分大小写、全字匹配、内容搜索
- **文件操作**：复制 / 剪切 / 粘贴（与资源管理器剪贴板互认）、重命名、新建、回收站、属性、以管理员运行、在终端打开、ZIP 压缩解压
- **窗格间拖拽**：默认复制，按住 Shift 移动，后台任务带实时进度
- **暂存盘**：跨目录收集，一键复制 / 移动到活动窗格
- **空格预览**：文件夹列内部条目 / 图片 / 视频 / 音频 / PDF / 文本 / Markdown / 压缩包目录树 / Excel 表格 / Word 段落 / PPT 分页文字
- **鼠标侧键**：后退键退一步（历史到头则回上一级目录），前进键前进；只在本程序窗口前台时生效
- **七色标签、收藏夹、搜索历史**，可导出 CSV
- **列宽与窗格宽度**可拖动并记忆，支持「仅显示名称列」「文件名两行显示」

## 主题皮肤（1.3 新增）

10 套皮肤，按主题色板生成——不是简单换背景色，而是由 `bg / surface / text / accent` 四个令牌推导出全部 22 个界面变量，每套都按 WCAG AA 核过对比度（正文 8.98:1 – 17.06:1）。

| 分组 | 皮肤 |
| --- | --- |
| 风景 | 云海初醒 / 星河入梦 / 湖畔微风 |
| 国风 | 墨色千山 / 竹影清风 / 青花山河 |
| 红色 | 红日东方 / 赤诚 |
| 复古 | 窑洞灯火 / 实事求是 |

磨砂玻璃界面：顶栏、侧栏、状态栏与内容窗格半透，壁纸整窗贯通。皮肤面板可调**工作区不透明度**（0–100%）——调的是面板厚度，主题图始终按原图显示；面板越薄磨砂模糊也越小，风景才真的看得清。也可整张关掉壁纸只留配色。壁纸随包附带（WebP，不联网也能用）。

明暗切换只作用于默认皮肤「晨雾蓝」；不选主题时外观与 1.2 一致。

## 1.5 增强

**工作面透明度可调**。1.4 的滑杆装错了层——它只改壁纸层的 `opacity`，面板仍是 48% 厚 + 10px 模糊，拉到 0 也只是背景露白，所以抱怨「主题图看不见」。现在：

| 滑杆（工作区不透明度） | 面板 alpha（深色主题） | 磨砂模糊 | 效果 |
| --- | --- | --- | --- |
| 100%（默认） | 0.48 | 10px | 与 1.4 外观一致 |
| 70% | 0.34 | 7px | 照片轮廓透出来，文字仍有底 |
| 40% | 0.19 | 4px | 照片很清楚，只剩一层薄色 |
| 0% | 0 | 0 | 字直接写在照片上 |

壁纸层恒为原图，不再随滑杆变淡。实现上面板底色拆成 `--plate-rgb` + 基准 alpha，运行时乘 `--plate-k`，换滑杆不必重算皮肤 CSS。

## 1.4 增强

**空格预览补全**。原先文件夹只回一个子项数量、前端没有对应分支，于是提示「此格式不提供内嵌预览」；Office 文档因为「小于 256 KB 一律按文本读」被当成 zip 二进制解码，满屏乱码。现在：

| 文件类型 | 预览内容 |
| --- | --- |
| 文件夹 | 列出内部全部条目（目录在前），点目录进去、点文件继续预览，超过 500 项截断 |
| `.xlsx` / `.xlsm` | 按工作表解析成单元格表格（共享字符串、内联字符串、日期格式都还原），前 3 表 × 各 80 行 |
| `.docx` | 按段落提取正文，表格文字按顺序并入 |
| `.pptx` | 按页列出文字并标注页码 |
| `.exe` / `.dll` 等 | 先做 NUL 探测，判定为二进制就给明确提示，不再念乱码 |

解析器是零依赖的 `src/fmp/office.py`（只用 `zipfile` + `ElementTree`），打包体积不变。

**鼠标侧键导航**。用 `WH_MOUSE_LL` 低级钩子接 `XBUTTON1/2`，只在本程序窗口位于前台时才转发给界面，不影响其它程序；`src/fmp/mouse_nav.py` 里带节流，长按不会连发。

## 源码运行

需要 Python 3.10+ 与 `pywebview`：

```bat
py -m pip install pywebview
py src/main.py
```

或双击 `启动-文件管理多面手.bat`。

内置搜索引擎依赖 `src/assets/engine/Everything.exe`（随仓库附带，许可见 `src/assets/engine/Everything-License.txt`）。缺少该文件时引擎功能不可用，搜索自动降级为本地索引。

## 构建

```bat
py src\build.py           :: 便携版单文件 exe
py src\build_setup.py     :: 安装版 Setup.exe（需先有便携版）
```

产物输出到仓库上一级目录，文件名取自 `src/fmp/version.py`。

## 版本规则

**每次更新都必须递增编号**，不允许用同一版本号覆盖已发布的包。

- 唯一来源：`src/fmp/version.py` 的 `APP_VERSION`，窗口标题、exe 名、安装目录、快捷方式、注册表项、交付包名全部由它派生
- 升版：`py src/tools/bump_version.py --minor`（大版本 `--major`，指定 `--set 1.5`）
- 自检：`py src/tools/bump_version.py --check`
- 发布：`py src/tools/publish_github.py`（同步源码 → 推送 → 建 Release 并上传两个 exe）
- 拦截：`src/tools/release_guard.py` 记录源码指纹，`build.py` 在源码改动过而版本号没变时拒绝出包（退出码 3），并列出改动文件

固定发版顺序：升版 → 补写 `更新日志.txt` → 构建 → 回归测试 → 打交付包。

## 目录结构

```
src/
  fmp/            领域层与服务层：model / config / fs / everything / search /
                  ops / clipboard / server / bridge / version
  ui/             前端：index.html + app.css + ES 模块 + skins/（10 套皮肤与壁纸）
  tools/          gen_skins.py 皮肤生成、make_bg.py 壁纸取景、bump_version.py 升版、
                  release_guard.py 发版守卫、publish_github.py 一键发布
  assets/         图标与内置引擎
  main.py         启动、单实例、全局热键
  build.py        便携版打包
  build_setup.py  安装器打包
tests/            自测脚本：后端 / 界面 / 皮肤 / 引擎 / 安装 / 拖放 / 剪贴板 / 关闭 / 预览 / 侧键
使用说明.txt        功能明细与快捷键
更新日志.txt        版本改动记录
架构与修复说明.txt   分层设计、关键修复与坑的记录
legacy-1.0/       1.0 旧版单文件存档（FolderPilot.pyw）
```

## 架构要点

旧版是单个 385 KB 的 `.pyw`，前端 base64 内嵌、业务逻辑混在 HTTP 路由里。新版拆成四层：领域层（FileEntry 模型，绝对路径为唯一身份）、服务层（文件操作 / 搜索 / 剪贴板 / 配置）、传输层（127.0.0.1 + 每次启动随机 token 的 HTTP `/api`）、界面层（独立 HTML / CSS / ES 模块）。

命令通道不走 `js_api`，改用本地 HTTP POST，消除 pywebview 注入时序导致的启动竞态；关闭时不做跨线程 JS 调用，会话由页面 `pagehide` 用 `sendBeacon` 异步保存，避免 WebView2 销毁阶段的「未响应」。

## 第三方组件

- Everything SDK / Everything.exe — 见 `src/assets/engine/Everything-License.txt` 与 `licenses/`
- pywebview、WebView2 运行时

## 旧版

`legacy-1.0/` 存放 1.0 的单文件版本（`FolderPilot.pyw`，385 KB，界面资源内嵌），仅作存档，不再更新。

> 本项目在 AI 辅助下开发。
