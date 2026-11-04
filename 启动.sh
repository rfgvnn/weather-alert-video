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

# ---------- 首次运行：自动创建虚拟环境 ----------
# 目录里还没有 .venv / venv 时建一个，避免把依赖装进系统 Python。
# 建失败不算致命（例如 Debian 未装 python3-venv），回退沿用系统 Python。
if [ ! -x ".venv/bin/python" ] && [ ! -x "venv/bin/python" ]; then
  echo "[首次运行] 正在创建虚拟环境 .venv ……"
  if "$PY" -m venv .venv 2>/dev/null; then
    PY=".venv/bin/python"
    echo "[OK]   虚拟环境已就绪"
  else
    echo "[提示] 虚拟环境创建失败，沿用系统 Python：$PY"
    echo "        Debian/Ubuntu 可先执行： sudo apt install python3-venv"
  fi
fi

echo "使用解释器: $PY"
"$PY" -c "import fastapi, uvicorn, edge_tts, imageio_ffmpeg" 2>/dev/null || {
  echo "依赖不完整，正在安装（也可手动执行：$PY -m pip install -r requirements.txt）"
  "$PY" -m pip install -r requirements.txt || {
    echo "[提示] 默认源失败，改用清华镜像重试……"
    if ! "$PY" -m pip install -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple; then
      echo "[错误] 依赖安装失败，请检查网络后重试，或手动执行："
      echo "       $PY -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
      exit 1
    fi
  }
}

# 中文字体缺失时给个明确提示，避免字幕变方块
"$PY" 自检.py || true

echo
exec "$PY" app.py
