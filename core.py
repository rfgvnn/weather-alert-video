# -*- coding: utf-8 -*-
"""
文本转语音 + 关键词路由 + 视频音轨合成 核心模块

关键词 → 视频 的路由规则放在 rules.json 里（改配置即可，无需改代码）：
  文本包含某个关键词 -> 把语音合成到该关键词对应的视频
  命中多个关键词     -> 同时产出多个成片

预警图标（signals）也在 rules.json 里配置：
  文本包含图标关键词（如"大雾橙色"）-> 把对应 GIF 图标叠加到成片左上角
  归属自动判断：图标关键词里包含哪个视频关键词，就贴到哪个视频的成片上
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

import imageio_ffmpeg

import caption
import tts as tts_

# ---------------------------------------------------------------- 基本配置

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def _has_encoders(exe: str) -> bool:
    """检查该 ffmpeg 是否同时支持 libx264 与 aac（叠加文字/图标时必须用）。"""
    try:
        r = subprocess.run(
            [exe, "-hide_banner", "-encoders"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=20,
        )
    except Exception:  # noqa: BLE001
        return False
    out = (r.stdout or "") + (r.stderr or "")
    return "libx264" in out and re.search(r"\baac\b", out) is not None


def _detect_ffmpeg() -> str:
    """
    选一个能用的 ffmpeg：
    优先 imageio-ffmpeg 自带的二进制，若它不带 libx264/aac 则退回系统安装的 ffmpeg。
    """
    candidates: list[str] = []
    try:
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # noqa: BLE001
        pass
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        candidates.append(sys_ff)
    for c in candidates:
        if os.path.exists(c) and _has_encoders(c):
            return c
    if candidates:
        return candidates[0]
    raise RuntimeError(
        "未找到 ffmpeg。请先安装：\n"
        "  Debian/Ubuntu: sudo apt install ffmpeg\n"
        "  CentOS/RHEL:   sudo yum install ffmpeg\n"
        "  或重新执行 pip install imageio-ffmpeg"
    )


FFMPEG = _detect_ffmpeg()

HOME = os.path.expanduser("~")


def _default_video_dir() -> str:
    """常见的视频/下载目录（Windows 下载、Linux 中文下载目录都覆盖）。"""
    for name in ("Downloads", "下载", "Videos", "视频"):
        p = os.path.join(HOME, name)
        if os.path.isdir(p):
            return p
    return os.path.join(HOME, "Downloads")


DOWNLOADS = _default_video_dir()

# 关键词 -> 视频 的路由表（改这个文件即可，无需动代码）
RULES_FILE = os.path.join(BASE_DIR, "rules.json")
# 也可以把视频放进这个目录，然后在 rules.json 里用相对路径引用
VIDEO_DIR = os.path.join(BASE_DIR, "videos")
# 预警图标（GIF/PNG）默认目录
SIGNAL_DIR = os.path.join(BASE_DIR, "signals")

# rules.json 不存在时自动生成的默认内容
DEFAULT_RULES: dict[str, Any] = {
    "_说明": [
        "关键词 → 视频 的路由表。改完保存，在网页上点“重载规则”即可生效，不用重启服务。",
        "keywords：命中其中任意一个关键词，就把语音合成到这条规则对应的视频（可写多个别名）。",
        "video：视频文件路径。可以写绝对路径，也可以写相对 app 目录的路径，例如 videos/大风.mp4。",
        "label：界面上显示的名字，可省略（默认用第一个关键词）。",
        "tag：输出文件名里的标记，可省略（默认用第一个关键词）。",
        "新增“大风”的写法示例：{ \"keywords\": [\"大风\"], \"video\": \"videos/大风.mp4\", \"label\": \"大风\" }",
        "",
        "signals 是预警图标表：文本包含图标关键词时，把对应 GIF/PNG 图标叠加到成片左上角。",
        "icon：图标文件路径，可写绝对路径或相对 app 目录，例如 signals/FOGW_O.gif。",
        "归属自动判断：图标关键词里包含哪个视频的关键词，就贴到哪个视频的成片上；",
        "  也可以用 attach 手动指定，如 { \"keywords\":[\"大风蓝色\"], \"icon\":\"signals/GALE_B.gif\", \"attach\":\"大风\" }。",
        "size：图标宽度占画面宽度的比例，可省略（默认 0.16）。",
    ],
    "rules": [
        {"keywords": ["大雾"], "video": os.path.join(DOWNLOADS, "大雾.mp4"), "label": "大雾", "tag": "大雾"},
        {"keywords": ["雷电"], "video": os.path.join(DOWNLOADS, "雷电.mp4"), "label": "雷电", "tag": "雷电"},
    ],
    "signals": [
        {"keywords": ["大雾黄色"], "icon": "signals/FOGW_Y.gif", "label": "大雾黄色预警"},
        {"keywords": ["大雾橙色"], "icon": "signals/FOGW_O.gif", "label": "大雾橙色预警"},
    ],
}


def _read_json_tolerant(path: str) -> Any:
    """兼容记事本保存成 UTF-8 / UTF-8 BOM / GBK 三种情况。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise TaskError(f"规则文件格式有误，无法解析：{path}")


def _resolve_path(path: str, fallback_dir: str) -> str:
    """
    把配置里的素材路径转成可用路径（支持相对 app 目录 / 指定目录）。
    换系统后配置里的旧绝对路径（如 C:/...）若不存在，会自动回退到本目录里的同名文件。
    """
    p = (path or "").strip().strip('"')
    if not p:
        return ""
    p = os.path.expandvars(os.path.expanduser(p))
    if os.path.isabs(p) and os.path.exists(p):
        return os.path.normpath(p)

    base = os.path.basename(p.replace("\\", "/"))
    for cand in (
        os.path.normpath(os.path.join(BASE_DIR, p)),
        os.path.normpath(os.path.join(fallback_dir, p)),
        os.path.normpath(os.path.join(fallback_dir, base)),
    ):
        if os.path.exists(cand):
            return cand

    # 都找不到：绝对路径原样返回（便于报错里显示期望路径），相对路径按指定目录拼
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(fallback_dir, base))


def _resolve_video(path: str) -> str:
    return _resolve_path(path, VIDEO_DIR)


def _normalize_rule(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kws = raw.get("keywords")
    if isinstance(kws, str):
        kws = [kws]
    if not kws:
        one = raw.get("keyword")
        kws = [one] if one else []
    kws = [str(k).strip() for k in kws if str(k).strip()]
    if not kws:
        return None
    video = _resolve_video(str(raw.get("video", "")))
    primary = kws[0]
    return {
        "keywords": kws,
        "keyword": primary,                      # 兼容旧字段
        "video": video,
        "label": str(raw.get("label") or primary).strip(),
        "tag": str(raw.get("tag") or primary).strip(),
    }


def _normalize_signal(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kws = raw.get("keywords")
    if isinstance(kws, str):
        kws = [kws]
    if not kws:
        one = raw.get("keyword")
        kws = [one] if one else []
    kws = [str(k).strip() for k in kws if str(k).strip()]
    if not kws:
        return None
    icon = _resolve_path(str(raw.get("icon", "")), SIGNAL_DIR)
    if not icon:
        return None
    def frac(key: str, default: float, lo: float, hi: float) -> float:
        v = raw.get(key)
        if v is None or v == "":
            v = default
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = default
        return min(hi, max(lo, v))

    # margin 是简写：只写一个数就同时表示距左、距上边距
    dflt_x, dflt_y = 0.05, 0.08
    margin = raw.get("margin")
    if margin not in (None, ""):
        try:
            m = float(margin)
            dflt_x = dflt_y = m
        except (TypeError, ValueError):
            pass
    return {
        "keywords": kws,
        "keyword": kws[0],                      # 兼容旧字段
        "icon": icon,
        "attach": str(raw.get("attach") or "").strip(),
        "size": frac("size", 0.33, 0.05, 0.5),
        "margin_x": frac("margin_x", dflt_x, 0.0, 0.9),
        "margin_y": frac("margin_y", dflt_y, 0.0, 0.9),
        "label": str(raw.get("label") or kws[0]).strip(),
    }


_rules_cache: dict[str, Any] = {"mtime": None, "rules": [], "signals": None}


def _load_config(force: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    读取 rules.json（视频规则 + 预警图标）。文件有变化会自动重新加载（按修改时间判断），
    所以改完配置刷新页面即可生效，不必重启服务。
    """
    if not os.path.exists(RULES_FILE):
        try:
            with open(RULES_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_RULES, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    try:
        mtime = os.path.getmtime(RULES_FILE) if os.path.exists(RULES_FILE) else None
    except OSError:
        mtime = None

    cached = (
        not force
        and _rules_cache["mtime"] == mtime
        and _rules_cache["rules"]
        and _rules_cache["signals"] is not None
    )
    if cached:
        return _rules_cache["rules"], _rules_cache["signals"]

    rules: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    try:
        data = _read_json_tolerant(RULES_FILE)
        raw_list = data.get("rules", []) if isinstance(data, dict) else data
        for raw in raw_list or []:
            rule = _normalize_rule(raw)
            if rule:
                rules.append(rule)
        if isinstance(data, dict):
            for raw in data.get("signals") or []:
                sig = _normalize_signal(raw)
                if sig:
                    signals.append(sig)
    except Exception:  # noqa: BLE001
        # 配置坏了也要让服务能用：退回内置默认规则
        rules = [r for r in (_normalize_rule(x) for x in DEFAULT_RULES["rules"]) if r]
        signals = [s for s in (_normalize_signal(x) for x in DEFAULT_RULES.get("signals", [])) if s]

    _rules_cache["mtime"] = mtime
    _rules_cache["rules"] = rules
    _rules_cache["signals"] = signals
    return rules, signals


def load_rules(force: bool = False) -> list[dict[str, Any]]:
    return _load_config(force)[0]


def load_signals(force: bool = False) -> list[dict[str, Any]]:
    return _load_config(force)[1]


RULES_FILE_HINT = RULES_FILE

def current_voices(engine: str | None = None) -> list[tuple[str, str]]:
    """当前引擎可用的音色列表 [(id, 显示名)]。"""
    p = tts_.get_provider(engine)
    return [(v.id, f"{v.name}" + (f"（{v.desc}）" if v.desc else "")) for v in p.voices()]


def current_default_voice(engine: str | None = None) -> str:
    return tts_.get_provider(engine).default_voice()


# 仅作兼容保留；实际列表走 current_voices()（按引擎动态取）。
# 这里刻意用静态表，避免模块导入时就去调网络。
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_PRESETS = [(k, v[0]) for k, v in tts_.EdgeProvider._ZH_NAMES.items()]


class TaskError(Exception):
    """面向用户的可读错误。"""


# ---------------------------------------------------------------- 工具函数


def probe_duration(path: str) -> float:
    """解析 ffmpeg -i 输出中的 Duration。"""
    r = subprocess.run(
        [FFMPEG, "-i", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not m:
        raise TaskError(f"无法读取媒体时长：{os.path.basename(path)}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _pct(value: int) -> str:
    """-50..100 的整数转为 edge-tts 需要的 '+10%' 形式。"""
    value = int(value)
    return f"{value:+d}%"


def _run(cmd: list[str], step: str, timeout: int = 1800) -> None:
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise TaskError(f"{step} 超时（>{timeout} 秒），请缩短文本或降低输出清晰度。")
    if r.returncode != 0:
        tail = "\n".join([ln for ln in r.stderr.strip().splitlines() if ln][-6:])
        raise TaskError(f"{step} 失败：{tail or '未知错误'}")


_QSV_OK: bool | None = None


def _qsv_available() -> bool:
    """探测 Intel 核显 QSV 硬件编码是否可用，结果进程内缓存（只探测一次）。
    硬编把编码交给核显，CPU 只负责滤镜，长视频实测快 20-40%；
    不支持（无 Intel 核显/驱动）时自动回退 libx264。"""
    global _QSV_OK
    if _QSV_OK is None:
        try:
            r = subprocess.run(
                [FFMPEG, "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=0.3",
                 "-c:v", "h264_qsv", "-f", "null", "-"],
                capture_output=True, timeout=20,
            )
            _QSV_OK = r.returncode == 0
        except Exception:  # noqa: BLE001
            _QSV_OK = False
    return _QSV_OK


def video_encoder_args() -> list[str]:
    if _qsv_available():
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "22", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def slugify(text: str, limit: int = 18) -> str:
    s = re.sub(r"[^\w一-鿿]+", "_", text).strip("_")
    return (s[:limit] or "voice").strip("_") or "voice"


# ---------------------------------------------------------------- 文本 -> 语音


def synth_speech(
    text: str,
    voice: str,
    rate: int,
    volume: int,
    out_path: str,
    engine: str | None = None,
) -> None:
    """把文本合成语音。具体用哪家引擎由 tts 适配层决定。"""
    provider = tts_.get_provider(engine)
    ok, reason = provider.ready()
    if not ok:
        raise TaskError(f"语音引擎不可用（{provider.label}）：{reason}")

    # 音色属于别的引擎时，退回当前引擎的默认音色，避免声音莫名其妙变掉
    ids = {v.id for v in provider.voices()}
    if voice not in ids:
        voice = provider.default_voice()

    try:
        provider.synth(text, voice, rate, volume, out_path)
    except tts_.TTSError as e:
        raise TaskError(str(e)) from e
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise TaskError("语音合成结果为空，请检查网络连通性与引擎配置。")


# ---------------------------------------------------------------- 视频时长读取


@dataclass
class VideoInfo:
    path: str
    name: str
    duration: float
    width: int = 0
    height: int = 0

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration"] = round(self.duration, 2)
        return d


def inspect_video(path: str) -> VideoInfo:
    if not os.path.exists(path):
        raise TaskError(f"源视频不存在：{path}")
    r = subprocess.run(
        [FFMPEG, "-i", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    if not dur_m:
        raise TaskError(f"无法解析视频：{os.path.basename(path)}")
    duration = int(dur_m.group(1)) * 3600 + int(dur_m.group(2)) * 60 + float(dur_m.group(3))
    size_m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", r.stderr)
    w = int(size_m.group(1)) if size_m else 0
    h = int(size_m.group(2)) if size_m else 0
    return VideoInfo(path=path, name=os.path.basename(path), duration=duration, width=w, height=h)


def probe_image_size(path: str) -> tuple[int, int]:
    """读取图片/GIF 的原始尺寸。"""
    if not os.path.exists(path):
        raise TaskError(f"图标文件不存在：{path}")
    r = subprocess.run(
        [FFMPEG, "-i", path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    size_m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", r.stderr)
    if not size_m:
        raise TaskError(f"无法解析图标尺寸：{os.path.basename(path)}")
    return int(size_m.group(1)), int(size_m.group(2))


# ---------------------------------------------------------------- 音画合成


@dataclass
class RenderOptions:
    """合成时的对齐策略。"""

    overflow: str = "loop"      # 语音长于视频：loop=循环画面 / freeze=定格末帧
    underflow: str = "trim"     # 语音短于视频：pad=画面保留+尾部静音 / trim=画面裁到语音长度
    resolution: str = "source"  # source / 1080 / 720


@dataclass
class TextStyle:
    """画面中央文字叠加。"""

    enabled: bool = True
    text: str = ""
    size: str = "medium"        # small / medium / large
    opacity: float = 0.30       # 灰色底板不透明度
    workdir: str | None = None


@dataclass
class SignalStyle:
    """叠加在画面左上角的预警图标（GIF/PNG）。"""

    path: str
    label: str = ""
    size: float = 0.33      # 图标宽度占画面宽度的比例
    margin_x: float = 0.05  # 距左边缘（占画面宽度的比例）
    margin_y: float = 0.08  # 距上边缘（占画面高度的比例）


SIZE_SCALE = {"small": 0.82, "medium": 1.0, "large": 1.25}

# 右上角标题：从文本开头提取「XX气象台…发布XX预警信号」
_ORG_RE = re.compile(
    r"^\s*([\u4e00-\u9fa5A-Za-z]{2,16}?(?:气象台|气象局|气象中心))"
)
_SIGNAL_RE = re.compile(r"([\u4e00-\u9fa5]{2,12}?(?:预警信号|预警))")


def extract_alert_title(text: str) -> str:
    """
    从文本开头提取「单位 + 发布 + 预警名称」，例如：

        磁县气象台2026年10月31日17时39分发布大风蓝色预警信号：预计…
        -> 磁县气象台发布大风蓝色预警信号

    提取不到（不是气象台发布的预警、或没有「发布XX预警信号」）时返回空串。
    """
    s = (text or "").strip()
    if not s:
        return ""

    m = _ORG_RE.match(s)
    if not m:
        return ""
    org = m.group(1)

    # 只在开头一小段里找「发布」，避免匹配到正文中间的「发布」
    head = s[m.end():][:60]
    i = head.find("发布")
    if i < 0:
        return ""
    m2 = _SIGNAL_RE.match(head[i + 2:])
    if not m2:
        return ""
    return f"{org}发布{m2.group(1)}"


def target_size(info: VideoInfo, opts: RenderOptions) -> tuple[int, int]:
    th = {"source": 0, "1080": 1080, "720": 720}.get(opts.resolution, 0)
    if th and info.height and th < info.height:
        h = th
        w = int(round(info.width * h / info.height / 2)) * 2
    else:
        w, h = info.width, info.height
    return w, h


def font_size(width: int, size: str = "medium") -> int:
    return max(14, int(round(width / 22 * SIZE_SCALE.get(size, 1.0))))


def build_video(
    video_path: str,
    audio_path: str,
    out_path: str,
    info: VideoInfo,
    audio_dur: float,
    opts: RenderOptions,
    style: TextStyle | None = None,
    signal: SignalStyle | None = None,
    corner_text: str = "",
    workdir: str | None = None,
) -> dict[str, Any]:
    """
    把语音作为音轨合成进视频，处理长度对齐，
    并可选在画面中央叠加文字、左上角叠加预警图标、右上角叠加标题。
    返回本次渲染的描述信息（供结果展示）。
    """
    style = style or TextStyle(enabled=False)
    out_w, out_h = target_size(info, opts)
    scaled = out_h != info.height

    need_freeze = audio_dur > info.duration and opts.overflow == "freeze"
    need_loop = audio_dur > info.duration and opts.overflow == "loop"
    freeze_pad = (audio_dur - info.duration + 0.05) if need_freeze else 0.0

    pad_audio = (
        (not need_loop) and (not need_freeze)
        and audio_dur < info.duration and opts.underflow == "pad"
    )

    # 图标存在时输出时长必须有确定上限（overlay 输入可能是循环 GIF）
    out_dur = audio_dur if need_loop else (
        (info.duration + freeze_pad) if need_freeze else (
            audio_dur if (opts.underflow == "trim" and audio_dur < info.duration)
            else (info.duration if pad_audio else max(audio_dur, info.duration))
        )
    )

    vf: list[str] = []
    if freeze_pad > 0:
        vf.append(f"tpad=stop_mode=clone:stop_duration={freeze_pad:.3f}")
    if scaled:
        vf.append(f"scale={out_w}:{out_h}")

    # 文字块以透明 PNG 输入 + overlay 滤镜贴图（drawtext 在部分 ffmpeg 精简版里不存在，
    # overlay 则到处都有）。overlays 依 (png 路径, x, y) 顺序叠放。
    overlays: list[tuple[str, int, int]] = []

    # ---- 右上角标题：XX气象台发布XX预警信号（先算几何，供正文避让）----
    t_lines = 0
    t_fs = 0
    top_bottom = 0.0
    if (corner_text or "").strip():
        t_fs = max(14, int(round(out_w / 18)))
        lines_top = caption.split_title_lines(corner_text)
        t_lines = len(lines_top)
        wd = workdir or style.workdir or tempfile.mkdtemp(prefix="ttslines_")
        png, px, py = caption.render_corner_png(
            out_w, out_h, lines_top, t_fs, outdir=os.path.join(wd, "title")
        )
        overlays.append((png, px, py))
        top_bottom = caption.CORNER_MARGIN_Y * out_h + caption.corner_box_height(len(lines_top), t_fs)

    # ---- 左上角预警图标 ----
    icon = signal if (signal and signal.path and os.path.exists(signal.path)) else None
    ico_w = ico_h = mx = 0
    if icon:
        try:
            src_w, src_h = probe_image_size(icon.path)
        except TaskError:  # noqa: BLE001
            src_w, src_h = 380, 323
        ico_w = max(4, int(round(out_w * icon.size / 2)) * 2)
        ico_h = max(4, int(round(ico_w * src_h / src_w / 2)) * 2)
        mx = max(2, int(round(out_w * icon.margin_x)))
        my = max(2, int(round(out_h * icon.margin_y)))
        top_bottom = max(top_bottom, my + ico_h)

    # ---- 画面中央文字（顶部有标题/图标时整体下移避让）----
    n_lines = 0
    fs = 0
    if style.enabled and (style.text or "").strip():
        fs = font_size(out_w, style.size)
        max_units = max(6.0, (out_w * 0.80) / fs)
        lines = caption.wrap_text(style.text, max_units)
        wd = style.workdir or workdir or tempfile.mkdtemp(prefix="ttslines_")
        n_lines = len(lines)
        min_y = top_bottom + out_h * 0.02 if top_bottom > 0 else 0.0
        png, bx, by = caption.render_caption_png(
            out_w, out_h, lines, fs, style.opacity, min_y=min_y,
            outdir=os.path.join(wd, "lines"),
        )
        overlays.append((png, bx, by))

    reencode = bool(vf) or bool(icon) or bool(overlays)

    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    if need_loop:
        loops = int(math.ceil(audio_dur / info.duration))
        cmd += ["-stream_loop", str(loops), "-i", video_path, "-i", audio_path]
    else:
        cmd += ["-i", video_path, "-i", audio_path]
    if icon:
        # 图标作为第 3 个输入（音频仍是第 2 个，索引不变）
        cmd += ["-i", icon.path]
    for png_path, _x, _y in overlays:
        cmd += ["-i", png_path]

    fc: list[str] = []
    if reencode:
        base_chain = ",".join(vf) if vf else "null"
        cur = "[base]" if (icon or overlays) else "[vout]"
        fc.append(f"[0:v:0]{base_chain}{cur}")
        chain_in: list[tuple[str, int, int]] = []
        png_base = 3 if icon else 2
        if icon:
            fc.append(f"[2:v:0]scale={ico_w}:{ico_h}[s0]")
            chain_in.append(("s0", mx, my))
        for k, (p, x, y) in enumerate(overlays):
            chain_in.append((f"{png_base + k}:v:0", x, y))
        for k, (src, x, y) in enumerate(chain_in):
            dst = "[vout]" if k == len(chain_in) - 1 else f"[t{k}]"
            fc.append(f"{cur}[{src}]overlay=x={x}:y={y}:eof_action=repeat{dst}")
            cur = dst
        vmap = cur
    else:
        vmap = "0:v:0"
    if pad_audio:
        # apad 必须给定精确的 whole_dur，否则会无限生成静音导致进程无法结束
        fc.append(f"[1:a:0]apad=whole_dur={info.duration:.3f}[aud]")
        amap = "[aud]"
    else:
        amap = "1:a:0"
    if fc:
        cmd += ["-filter_complex", ";".join(fc)]

    cmd += ["-map", vmap, "-map", amap]
    if reencode:
        cmd += video_encoder_args()
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-c:a", "aac", "-b:a", "192k"]

    if need_loop or need_freeze or opts.underflow == "trim":
        cmd += ["-shortest"]
    if icon:
        # 给输出时长一个硬上限，防止循环 GIF 输入导致无法收尾
        cmd += ["-t", f"{out_dur + 0.05:.3f}"]
    cmd += ["-movflags", "+faststart", out_path]

    _run(cmd, "音画合成（含画面文字/图标）" if reencode else "音画合成")
    return {
        "caption": bool(n_lines),
        "lines": n_lines,
        "fontsize": fs,
        "signal": bool(icon),
        "title_lines": t_lines,
        "title_fontsize": t_fs,
    }


# ---------------------------------------------------------------- 主流程


@dataclass
class Result:
    keyword: str
    label: str
    video: str
    voice: str
    file: str
    url: str
    size_mb: float
    video_duration: float
    audio_duration: float
    output_duration: float
    width: int
    height: int
    strategy: str
    created: str
    caption: bool = False
    lines: int = 0
    signal: str = ""
    title: str = ""


def match_rules(text: str) -> list[dict[str, Any]]:
    """找出文本命中的所有规则，命中的关键词记录在 matched 字段里。"""
    hits = []
    for rule in load_rules():
        for kw in rule["keywords"]:
            if kw and kw in text:
                hits.append({**rule, "matched": kw})
                break
    return hits


def match_signals(text: str) -> list[dict[str, Any]]:
    """找出文本命中的所有预警图标，命中的关键词记录在 matched 字段里。"""
    hits = []
    for sig in load_signals():
        for kw in sig["keywords"]:
            if kw and kw in text:
                hits.append({**sig, "matched": kw})
                break
    return hits


def signal_for_rule(rule: dict[str, Any], matched: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    为某条视频规则挑选应该叠加的图标：
      1) 图标显式用 attach 指定了这条规则 -> 直接用
      2) 图标关键词里包含这条规则的关键词 -> 自动归属，取最长匹配（更具体者优先）
      3) 图标没有指定 attach 也判断不出归属 -> 挂到所有成片上
    同一条规则命中多个图标时，取关键词在文本中出现最早的那个。
    """
    if not matched:
        return None
    kws = [k for k in rule["keywords"] if k]

    def order(s: dict[str, Any]) -> int:
        pos = text.find(s["matched"])
        return pos if pos >= 0 else 10**9

    explicit = [s for s in matched if s.get("attach")]
    for s in explicit:
        att = s["attach"]
        if att in kws or any(att and (att in k or k in att) for k in kws):
            return s

    auto = [s for s in matched if not s.get("attach")]
    best, best_len = None, -1
    for s in auto:
        for k in kws:
            if k in s["matched"] and len(k) > best_len:
                best, best_len = s, len(k)
    if best:
        return best

    return min(auto, key=order) if auto else None


def generate(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: int = 0,
    volume: int = 0,
    overflow: str = "loop",
    underflow: str = "trim",
    resolution: str = "source",
    caption_enabled: bool = True,
    caption_size: str = "medium",
    caption_opacity: float = 0.30,
    signal_enabled: bool = True,
    signal_size: float | None = None,
    title_enabled: bool = True,
    workdir: str | None = None,
    engine: str | None = None,
    progress=None,
) -> list[dict[str, Any]]:
    """
    输入文本 -> 合成语音 -> 按关键词把语音插入对应视频。
    signal_size 可覆盖配置里每条图标自己的 size（占画面宽度的比例）。
    title_enabled 为真时自动从文本开头提取「XX气象台发布XX预警信号」贴到右上角。
    engine 指定语音引擎，不传则用 tts_config.json 里的配置（默认 edge）。
    返回结果字典列表。
    """
    text = (text or "").strip()
    if not text:
        raise TaskError("请先输入文本内容。")

    hits = match_rules(text)
    if not hits:
        all_kw = [k for r in load_rules() for k in r["keywords"]]
        hint = "、".join(f"“{k}”" for k in all_kw) or "（尚未配置任何关键词）"
        raise TaskError(f"文本中未检测到关键词：需要包含 {hint} 才能匹配到视频。")

    missing = [h for h in hits if not os.path.exists(h["video"])]
    if missing:
        lines = "\n".join(f"“{h['matched']}” → {h['video']}" for h in missing)
        raise TaskError("以下关键词对应的视频文件不存在，请检查 rules.json：\n" + lines)

    # 预警图标：文本命中 + 与视频规则的归属判断，提前校验图标文件
    matched_signals = match_signals(text) if signal_enabled else []
    signal_map: dict[int, dict[str, Any]] = {}
    missing_icons: list[str] = []
    for i, h in enumerate(hits):
        sig = signal_for_rule(h, matched_signals)
        if sig:
            signal_map[i] = sig
            if not os.path.exists(sig["icon"]):
                missing_icons.append(f"“{sig['matched']}” → {sig['icon']}")
    if missing_icons:
        raise TaskError("以下预警图标文件不存在，请检查 rules.json 的 signals：\n" + "\n".join(missing_icons))

    def tick(p: int, msg: str) -> None:
        if progress:
            progress(p, msg)

    # 右上角标题：只从文本开头提取，提取不到就不贴
    corner_title = extract_alert_title(text) if title_enabled else ""

    tmpdir = workdir or tempfile.mkdtemp(prefix="ttsvideo_")
    os.makedirs(tmpdir, exist_ok=True)

    # 1) TTS
    provider = tts_.get_provider(engine)
    tick(5, f"正在用{provider.label}合成语音…")
    audio_path = os.path.join(tmpdir, "speech." + (getattr(provider, "audio_ext", "mp3") or "mp3"))
    synth_speech(text, voice, rate, volume, audio_path, engine=engine)

    tick(35, "读取语音时长…")
    audio_dur = probe_duration(audio_path)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = slugify(text)

    results: list[dict[str, Any]] = []
    total = len(hits)
    for idx, rule in enumerate(hits, start=1):
        p0 = 40 + int((idx - 1) * 55 / total)
        tick(p0, f"读取{rule['label']}…")
        info = inspect_video(rule["video"])

        opts = RenderOptions(overflow=overflow, underflow=underflow, resolution=resolution)

        if audio_dur > info.duration:
            strategy = "画面循环至语音结束" if opts.overflow == "loop" else "定格末帧至语音结束"
        elif opts.underflow == "trim":
            strategy = "画面裁剪到语音长度"
        else:
            strategy = "画面完整保留，语音末尾补静音"

        fname = f"{base}_{rule['tag']}_{stamp}.mp4"
        out_path = os.path.join(OUTPUT_DIR, fname)

        style = TextStyle(
            enabled=caption_enabled, text=text, size=caption_size,
            opacity=caption_opacity, workdir=tmpdir,
        )
        sig_raw = signal_map.get(idx - 1)
        if sig_raw:
            # 界面/调用方传入的 signal_size 优先，其次用配置里这条图标自己的 size
            ico_size = sig_raw["size"]
            if signal_size:
                ico_size = min(0.5, max(0.05, float(signal_size)))
            sig = SignalStyle(
                path=sig_raw["icon"], label=sig_raw["label"], size=ico_size,
            )
        else:
            sig = None
        extras = ""
        if sig_raw:
            extras += f"，叠加预警图标「{sig_raw['label']}」"
        if caption_enabled:
            extras += "，正在叠加画面文字"
        if corner_title:
            extras += f"，右上角标题「{corner_title}」"
        tick(p0 + 10, f"正在合成 → {rule['label']}（{strategy}{extras}）")
        render = build_video(
            rule["video"], audio_path, out_path, info, audio_dur, opts, style, sig,
            corner_text=corner_title, workdir=tmpdir,
        )

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise TaskError(f"合成结果为空：{rule['label']}")

        out_dur = probe_duration(out_path)
        w, h = target_size(info, opts)

        results.append(
            asdict(
                Result(
                    keyword=rule["matched"],
                    label=rule["label"],
                    video=rule["video"],
                    voice=voice,
                    file=fname,
                    url=f"/outputs/{fname}",
                    size_mb=round(os.path.getsize(out_path) / 1024 / 1024, 2),
                    video_duration=round(info.duration, 2),
                    audio_duration=round(audio_dur, 2),
                    output_duration=round(out_dur, 2),
                    width=w,
                    height=h,
                    strategy=strategy,
                    created=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    caption=bool(render.get("caption")),
                    lines=int(render.get("lines", 0)),
                    signal=(sig_raw["label"] if sig_raw else ""),
                    title=corner_title,
                )
            )
        )

    tick(100, "完成")
    if workdir is None:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return results


# ---------------------------------------------------------------- CLI

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="文本转语音并按关键词插入视频")
    ap.add_argument("--text", required=True, help="要朗读的文本（需包含 rules.json 里配置的关键词）")
    ap.add_argument("--voice", default=None, help="音色 ID，不传则用当前引擎的默认音色")
    ap.add_argument("--engine", default=None, choices=[c.id for c in tts_.PROVIDERS],
                    help="语音引擎，不传则用 tts_config.json 里的 engine")
    ap.add_argument("--rate", type=int, default=0)
    ap.add_argument("--volume", type=int, default=0)
    ap.add_argument("--overflow", default="loop", choices=["loop", "freeze"])
    ap.add_argument("--underflow", default="trim", choices=["pad", "trim"])
    ap.add_argument("--resolution", default="source", choices=["source", "1080", "720"])
    ap.add_argument("--no-caption", action="store_true", help="不在画面上叠加文字")
    ap.add_argument("--caption-size", default="medium", choices=["small", "medium", "large"])
    ap.add_argument("--caption-opacity", type=float, default=0.30)
    ap.add_argument("--no-signal", action="store_true", help="不叠加预警图标")
    ap.add_argument("--signal-size", type=float, default=None,
                    help="图标宽度占画面宽度的比例，如 0.22（默认 0.16）")
    ap.add_argument("--no-title", action="store_true",
                    help="不在右上角叠加「XX气象台发布XX预警信号」标题")
    args = ap.parse_args()

    for r in generate(
        args.text, args.voice or tts_.get_provider(args.engine).default_voice(),
        args.rate, args.volume,
        args.overflow, args.underflow, args.resolution,
        caption_enabled=not args.no_caption,
        caption_size=args.caption_size,
        caption_opacity=args.caption_opacity,
        signal_enabled=not args.no_signal,
        signal_size=args.signal_size,
        title_enabled=not args.no_title,
        engine=args.engine,
        progress=lambda p, m: print(f"[{p:>3}%] {m}"),
    ):
        print("✔", r["label"], "->", os.path.join(OUTPUT_DIR, r["file"]))
