@echo off
chcp 936 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%~dp0"
title 文本转语音 - 视频合成

echo ============================================================
echo   文本转语音 - 视频合成
echo ============================================================
echo.

if not exist "%~dp0app.py" (
    echo [错误] 当前目录找不到 app.py
    echo        请把本文件放在 app.py 所在的文件夹里再运行。
    echo.
    pause
    exit /b 1
)

rem ---------- 1. 优先使用目录内已有的虚拟环境 ----------
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe"  set "PY=%~dp0venv\Scripts\python.exe"
if defined PY goto :checkdeps

rem ---------- 2. 用系统 Python 建一个独立环境 ----------
set "LAUNCH="
where py >nul 2>nul
if not errorlevel 1 set "LAUNCH=py -3"
if not defined LAUNCH (
    where python >nul 2>nul
    if not errorlevel 1 set "LAUNCH=python"
)
if not defined LAUNCH goto :nopython

echo [首次运行] 正在创建运行环境，约需 10 秒……
%LAUNCH% -m venv "%~dp0.venv"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
    goto :checkdeps
)

echo [提示] 虚拟环境创建失败，改为直接使用系统 Python。
for /f "delims=" %%i in ('%LAUNCH% -c "import sys;print(sys.executable)"') do set "PY=%%i"
if not defined PY goto :nopython

rem ---------- 3. 检查依赖，缺了自动安装 ----------
:checkdeps
"%PY%" -c "import fastapi, uvicorn, edge_tts, imageio_ffmpeg" >nul 2>nul
if not errorlevel 1 goto :run

echo [依赖] 首次运行需要安装依赖，约 1-3 分钟，请保持联网……
"%PY%" -m pip install -q --upgrade pip >nul 2>nul
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [提示] 默认源失败，改用清华镜像重试……
    "%PY%" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
)
if errorlevel 1 goto :depfail

rem ---------- 4. 启动 ----------
:run
echo.
echo 正在启动服务，浏览器会自动打开。
echo 使用期间请不要关闭本窗口，关闭窗口即停止服务。
echo.
"%PY%" app.py
echo.
echo 服务已停止。
pause
exit /b 0

:depfail
echo.
echo [错误] 依赖安装失败，请检查网络后重试。
echo        也可手动执行：
echo        "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:nopython
echo.
echo [错误] 没找到 Python，无法启动。
echo        请先安装 Python 3.10 或更高版本：
echo        https://www.python.org/downloads/
echo        安装时务必勾选 "Add python.exe to PATH"，然后重新双击本文件。
echo.
pause
exit /b 1
