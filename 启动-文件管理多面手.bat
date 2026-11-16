@echo off
rem 文件管理多面手 - 启动器（自动识别当前版本的便携版 exe）
cd /d "%~dp0"
set "APP="
for /f "delims=" %%F in ('dir /b /o-d "文件管理多面手 *.exe" 2^>nul ^| findstr /v /i "\-Setup\.exe"') do (
  if not defined APP set "APP=%%F"
)
if defined APP (
  start "" "%APP%"
  exit /b 0
)
echo [文件管理多面手] 未找到便携版 exe，尝试用 Python 脚本启动...
set "PYW="
for /f "usebackq delims=" %%P in (`py -3.14 -c "import sys;print(sys.executable)" 2^>nul`) do set "PYW=%%P"
if defined PYW set "PYW=%PYW:python.exe=pythonw.exe%"
if not defined PYW (
  echo 需要 Python 3.10+ 与 pywebview，或直接使用便携版 exe。
  pause
  exit /b 1
)
start "" "%PYW%" "%~dp0src\main.py"
exit /b 0
