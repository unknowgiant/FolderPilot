@echo off
rem FolderPilot 启动器：自动定位本机 Python 并以无窗口方式运行
setlocal enabledelayedexpansion
set "EXE="
for /f "usebackq delims=" %%P in (`py -3.14 -c "import sys;print(sys.executable)" 2^>nul`) do set "EXE=%%P"
if not defined EXE for /f "usebackq delims=" %%P in (`py -3 -c "import sys;print(sys.executable)" 2^>nul`) do set "EXE=%%P"
if not defined EXE for /f "delims=" %%P in ('where pythonw 2^>nul') do (set "EXE=%%P" & goto :run)
if not defined EXE (
  echo [FolderPilot] 未检测到 Python 3.10+，请先安装 Python，并执行： py -3.14 -m pip install pywebview
  pause
  exit /b 1
)
set "EXE=%EXE:python.exe=pythonw.exe%"
:run
if not exist "%EXE%" (
  echo [FolderPilot] 找不到 pythonw.exe: %EXE%
  pause
  exit /b 1
)
start "" "%EXE%" "%~dp0FolderPilot.pyw"