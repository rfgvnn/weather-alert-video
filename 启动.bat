@echo off
chcp 936 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

set "PY=C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

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

if exist "%PY%" goto :run

echo [提示] 未找到内置 Python：%PY%
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 系统里也没有可用的 Python，无法启动。
    echo.
    pause
    exit /b 1
)
echo         改用系统 Python 启动。
set "PY=python"

:run
echo 正在启动服务，浏览器会自动打开。
echo 使用期间请不要关闭本窗口，关闭窗口即停止服务。
echo.
"%PY%" app.py

echo.
echo 服务已停止。
pause
