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
    echo        请把本文件放到 app.py 所在的文件夹里运行。
    echo.
    pause
    exit /b 1
)

rem ---------- 1. 优先使用目录里已有的虚拟环境 ----------
set "PYEXE="
if exist "%~dp0.venv\Scripts\python.exe" set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0venv\Scripts\python.exe"  set "PYEXE=%~dp0venv\Scripts\python.exe"
if defined PYEXE goto :checkdeps

rem ---------- 2. 找系统 Python（跳过微软商店的 0 字节假 python.exe） ----------
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3"
if not defined PYEXE (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        if not defined PYEXE if not "%%~zi"=="0" set "PYEXE="%%i""
    )
)
if not defined PYEXE goto :nopython

echo [首次运行] 正在创建运行环境，约需 10 秒……
%PYEXE% -m venv "%~dp0.venv"
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYEXE=%~dp0.venv\Scripts\python.exe"
    goto :checkdeps
)

echo [提示] 虚拟环境创建失败，改为直接使用系统 Python。
for /f "delims=" %%i in ('%PYEXE% -c "import sys;print(sys.executable)"') do set "PYEXE=%%i"
if not defined PYEXE goto :nopython

rem ---------- 3. 检查依赖，缺了自动安装 ----------
:checkdeps
"%PYEXE%" -c "import fastapi, uvicorn, edge_tts, imageio_ffmpeg" >nul 2>nul
if not errorlevel 1 goto :run

echo [提示] 首次运行需要安装依赖，约 1-3 分钟，请保持联网……
"%PYEXE%" -m pip install -q --upgrade pip >nul 2>nul
"%PYEXE%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [提示] 默认源失败，改用清华镜像重试。
    "%PYEXE%" -m pip install -r "%~dp0requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
)
if errorlevel 1 goto :depfail

rem ---------- 4. 启动 ----------
:run
echo.
echo 服务启动后浏览器会自动打开。
echo 使用期间请不要关闭本窗口，关闭窗口即停止服务。
echo.
"%PYEXE%" app.py
echo.
echo 服务已停止。
pause
exit /b 0

:depfail
echo.
echo [错误] 依赖安装失败，请检查网络后重试。
echo        也可手动执行：
echo        "%PYEXE%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
pause
exit /b 1

:nopython
echo.
echo [错误] 没有找到可用的 Python，无法启动。
echo        可能原因：
echo        1. 电脑上没装 Python。请到下面网址安装 3.10 或更高版本：
echo           https://www.python.org/downloads/
echo           安装时务必勾选 "Add python.exe to PATH"。
echo        2. 装过 Python 但仍提示本错误：可能是系统里只剩下
echo           微软商店的假 python（占位程序）。请打开
echo           设置 - 应用 - 高级应用设置 - 应用执行别名，
echo           把 python.exe 和 python3.exe 两个别名关闭，
echo           然后重新安装 Python 并勾选 "Add python.exe to PATH"。
echo.
pause
exit /b 1
