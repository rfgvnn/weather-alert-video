# -*- coding: utf-8 -*-
"""
文本转语音 + 智能视频合成 · Web 服务
启动后浏览器访问 http://127.0.0.1:8765
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import core
import tts as tts_

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
OUTPUT_DIR = core.OUTPUT_DIR

app = FastAPI(title="文本转语音 · 视频合成")

# 简单内存任务池
JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()


def open_path(target: str) -> None:
    """跨平台在文件管理器里打开目录 / 选中文件（Windows 资源管理器、Linux xdg-open、macOS open）。"""
    target = os.path.normpath(target)
    if sys.platform.startswith("win") and hasattr(os, "startfile"):
        if os.path.isdir(target):
            os.startfile(target)  # noqa: S606
        else:
            subprocess.Popen(["explorer", "/select,", target])
        return
    if sys.platform == "darwin":
        cmd = ["open", target] if os.path.isdir(target) else ["open", "-R", target]
    else:
        # Linux：目录用 xdg-open；文件则打开它所在的目录
        if not os.path.isdir(target):
            target = os.path.dirname(target) or "."
        opener = shutil.which("xdg-open") or shutil.which("nautilus") or shutil.which("dolphin")
        if not opener:
            raise RuntimeError("Linux 上未找到 xdg-open，无法打开文件管理器（服务端可能是纯命令行环境）")
        cmd = [opener, target]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class GenerateRequest(BaseModel):
    text: str = Field(..., description="要朗读的文本")
    voice: str = core.DEFAULT_VOICE
    rate: int = 0
    volume: int = 0
    overflow: str = "loop"
    underflow: str = "pad"
    resolution: str = "source"
    caption: bool = True
    caption_size: str = "medium"
    caption_opacity: float = 0.55
    signal: bool = True
    signal_size: float | None = None
    engine: str | None = None


# ---------------------------------------------------------------- API


@app.get("/api/tts-engines")
def api_tts_engines():
    """可用的语音引擎列表（含是否配置好密钥）。"""
    return {
        "engines": tts_.list_engines(),
        "current": tts_.current_engine_id(),
    }


@app.get("/api/voices")
def api_voices(engine: str | None = None):
    """某引擎可用的音色列表；不传 engine 则用当前配置的引擎。"""
    try:
        pairs = core.current_voices(engine)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"读取音色列表失败：{e}") from e
    return {
        "engine": engine or tts_.current_engine_id(),
        "voices": [{"id": v, "name": n} for v, n in pairs],
    }


@app.get("/api/config")
def api_config():
    rules = []
    for r in core.load_rules():
        exists = os.path.exists(r["video"])
        info = None
        if exists:
            try:
                vi = core.inspect_video(r["video"])
                info = {"duration": round(vi.duration, 2), "width": vi.width, "height": vi.height}
            except Exception:  # noqa: BLE001
                info = None
        rules.append({
            "keyword": r["keyword"],
            "keywords": r["keywords"],
            "label": r["label"],
            "video": r["video"],
            "exists": exists,
            "info": info,
        })
    signals = []
    for s in core.load_signals():
        signals.append({
            "keyword": s["keyword"],
            "keywords": s["keywords"],
            "label": s["label"],
            "icon": s["icon"],
            "attach": s.get("attach", ""),
            "size": s["size"],
            "margin_x": s["margin_x"],
            "margin_y": s["margin_y"],
            "exists": os.path.exists(s["icon"]),
        })
    return {
        "rules": rules,
        "signals": signals,
        "output_dir": OUTPUT_DIR,
        "rules_file": core.RULES_FILE,
        "video_dir": core.VIDEO_DIR,
        "signal_dir": core.SIGNAL_DIR,
    }


@app.post("/api/reload-rules")
def api_reload_rules():
    """重新读取 rules.json（改完配置不用重启服务）。"""
    try:
        rules = core.load_rules(force=True)
        signals = core.load_signals(force=True)
    except core.TaskError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "ok": True,
        "count": len(rules),
        "signal_count": len(signals),
        "rules": [r["label"] for r in rules],
        "signals": [s["label"] for s in signals],
    }


@app.post("/api/open-file")
def api_open_file(which: str = "rules"):
    """在资源管理器中定位 rules.json / 打开视频目录。"""
    if which == "rules":
        target = core.RULES_FILE
    else:
        target = core.VIDEO_DIR
        os.makedirs(target, exist_ok=True)
    open_path(target)  # 失败直接抛 500
    return {"ok": True, "path": target}


@app.post("/api/preview-audio")
def api_preview_audio(req: GenerateRequest):
    """只做试听，不合成视频。"""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "请输入文本")
    tmpdir = os.path.join(core.OUTPUT_DIR, "_preview")
    os.makedirs(tmpdir, exist_ok=True)
    out = os.path.join(tmpdir, f"preview_{uuid.uuid4().hex[:8]}.mp3")
    try:
        core.synth_speech(text, req.voice, req.rate, req.volume, out, engine=req.engine)
    except core.TaskError as e:
        raise HTTPException(400, str(e)) from e
    return FileResponse(out, media_type="audio/mpeg", filename="preview.mp3")


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "请输入文本")
    if not core.match_rules(text):
        kws = [k for r in core.load_rules() for k in r["keywords"]]
        hint = "、".join(f"“{k}”" for k in kws) or "（尚未配置任何关键词）"
        raise HTTPException(400, f"文本中未检测到关键词（{hint}），无法确定要插入哪个视频。")

    job_id = uuid.uuid4().hex[:12]
    with LOCK:
        JOBS[job_id] = {"status": "running", "progress": 0, "message": "排队中", "results": None, "error": None}

    def worker() -> None:
        def hook(p: int, msg: str) -> None:
            with LOCK:
                if job_id in JOBS:
                    JOBS[job_id]["progress"] = p
                    JOBS[job_id]["message"] = msg

        try:
            results = core.generate(
                text=text,
                voice=req.voice,
                rate=req.rate,
                volume=req.volume,
                overflow=req.overflow,
                underflow=req.underflow,
                resolution=req.resolution,
                caption_enabled=req.caption,
                caption_size=req.caption_size,
                caption_opacity=req.caption_opacity,
                signal_enabled=req.signal,
                signal_size=req.signal_size,
                engine=req.engine,
                progress=hook,
            )
            with LOCK:
                JOBS[job_id].update({"status": "done", "progress": 100, "message": "生成完成", "results": results})
        except core.TaskError as e:
            with LOCK:
                JOBS[job_id].update({"status": "error", "message": str(e), "error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                JOBS[job_id].update({"status": "error", "message": f"内部错误：{e}", "error": str(e)})

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return JSONResponse(dict(job))


@app.post("/api/open-folder")
def api_open_folder():
    try:
        open_path(OUTPUT_DIR)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"无法打开目录：{e}") from e


@app.get("/api/list")
def api_list():
    """历史产物列表。"""
    items = []
    for name in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if not name.lower().endswith(".mp4"):
            continue
        p = os.path.join(OUTPUT_DIR, name)
        try:
            st = os.stat(p)
        except OSError:
            continue
        items.append({
            "file": name,
            "url": f"/outputs/{name}",
            "size_mb": round(st.st_size / 1024 / 1024, 2),
            "modified": int(st.st_mtime),
        })
    return {"items": items[:60]}


@app.delete("/api/file/{name}")
def api_delete(name: str):
    safe = os.path.basename(name)
    p = os.path.join(OUTPUT_DIR, safe)
    if os.path.exists(p):
        os.remove(p)
        return {"ok": True}
    raise HTTPException(404, "文件不存在")


# ---------------------------------------------------------------- 静态资源

app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _fix_console_encoding() -> None:
    """把标准输出/错误统一为 UTF-8，避免 Windows 控制台中文乱码。

    要点：Python 3.6+ 在 Windows 上通过 WriteConsoleW 直接向控制台写 UTF-16
    字符串（底层 _WindowsConsoleIO 以 UTF-8 解释写入的字节）。因此 stdout 必须
    保持 utf-8；一旦把它改成 cp936（跟随控制台代码页），文字会先被编码成 GBK
    字节、再被当作 UTF-8 解读，从而变成乱码。
    输出被重定向到文件 / 管道时，utf-8 同样是更通用的选择。
    调用需早于任何 print。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    import socket
    import webbrowser

    import uvicorn

    _fix_console_encoding()

    port = int(os.environ.get("PORT", "8765"))
    # 默认只监听本机；要让局域网/其他机器访问，启动时设 HOST=0.0.0.0
    host = os.environ.get("HOST", "127.0.0.1")
    # 端口被占用时自动顺延
    while True:
        s = socket.socket()
        try:
            s.bind((host, port))
            s.close()
            break
        except OSError:
            port += 1
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass

    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown_host}:{port}"
    print("=" * 56)
    print("  文本转语音 · 视频合成  已启动")
    print(f"  访问地址: {url}")
    print("  停止服务: Ctrl+C（Windows 也可直接关闭窗口）")
    print("=" * 56)

    # 服务器/无桌面环境下不自动开浏览器；设 NO_BROWSER=1 也可关闭
    if os.environ.get("NO_BROWSER", "") not in ("1", "true", "True"):
        def _open_browser() -> None:
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass
        threading.Timer(1.2, _open_browser).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
