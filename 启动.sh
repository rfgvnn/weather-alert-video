#!/usr/bin/env bash
# 文本转语音 · 视频合成 —— Linux / macOS 启动脚本
# 用法：  ./启动.sh          （默认 8765 端口，只监听本机）
#         HOST=0.0.0.0 ./启动.sh   （允许局域网其他机器访问）
#         NO_BROWSER=1 ./启动.sh   （不自动打开浏览器）

set -e
cd "$(dirname "$0")"

# 强制 Python 以 UTF-8 处理文件名：成片文件名含中文，locale 为 C/POSIX 时会报错
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
# 若系统 locale 不是 UTF-8，可在这里改成 zh_CN.UTF-8 或 en_US.UTF-8
# export LANG=zh_CN.UTF-8

PY=""
# 依次找：同目录的 venv > python3 > python
for cand in ".venv/bin/python" "venv/bin/python" "python3" "python"; do
  if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then
    PY="$cand"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "未找到 Python，请先安装 Python 3.9 及以上版本"
  exit 1
fi

echo "使用解释器: $PY"
"$PY" -c "import fastapi, uvicorn, edge_tts, imageio_ffmpeg" 2>/dev/null || {
  echo "依赖不完整，正在安装（也可手动执行：pip install -r requirements.txt）"
  "$PY" -m pip install -r requirements.txt
}

# 中文字体缺失时给个明确提示，避免字幕变方块
"$PY" 自检.py || true

echo
exec "$PY" app.py
