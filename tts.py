# -*- coding: utf-8 -*-
"""
可插拔 TTS 引擎适配层。

新增一个引擎只需：继承 Provider 实现三个方法，然后在 PROVIDERS 里注册。
上层（core / app / 前端）只认 Provider 接口，不关心具体用的是哪家服务。

引擎与密钥配置在同级目录的 tts_config.json 里；
当前内置 Edge 引擎（免费、无需密钥）。
想要加别的引擎：继承 Provider 实现三个方法，然后加进 PROVIDERS。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "tts_config.json")


class TTSError(Exception):
    """语音合成失败。"""


@dataclass
class Voice:
    id: str
    name: str
    desc: str = ""


# ------------------------------------------------------------------ 配置读取

_DEFAULT_CONFIG: dict[str, Any] = {
    "engine": "edge",
}

_config_cache: dict[str, Any] = {"mtime": None, "data": None}


def load_config(force: bool = False) -> dict[str, Any]:
    """读取 tts_config.json，文件变更时自动重载。"""
    if not os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(_DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    try:
        mtime = os.path.getmtime(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else None
    except OSError:
        mtime = None

    if not force and _config_cache["data"] is not None and _config_cache["mtime"] == mtime:
        return _config_cache["data"]

    data: dict[str, Any] = {}
    try:
        raw = open(CONFIG_FILE, "rb").read()
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                data = json.loads(raw.decode(enc))
                break
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
    except OSError:
        data = {}

    if not isinstance(data, dict):
        data = {}
    merged = json.loads(json.dumps(_DEFAULT_CONFIG))
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v

    _config_cache["mtime"] = mtime
    _config_cache["data"] = merged
    return merged


def current_engine_id() -> str:
    return str(load_config().get("engine", "edge") or "edge").strip().lower()


# ------------------------------------------------------------------ Provider 基类


class Provider:
    id: str = ""
    label: str = ""
    note: str = ""
    audio_ext: str = "mp3"   # 合成出来的音频后缀，core 用它拼临时文件名

    def ready(self) -> tuple[bool, str]:
        """返回 (是否可用, 不可用原因)。"""
        return True, ""

    def voices(self) -> list[Voice]:
        raise NotImplementedError

    def default_voice(self) -> str:
        vs = self.voices()
        return vs[0].id if vs else ""

    def synth(self, text: str, voice: str, rate: int, volume: int, out_path: str) -> None:
        raise NotImplementedError


# ------------------------------------------------------------------ Edge（微软，当前默认）


class EdgeProvider(Provider):
    """edge-tts：免费、无需密钥，音质与 Azure TTS 同源。依赖境外服务连通性。"""

    id = "edge"
    label = "Edge 朗读（免费）"
    note = "无需密钥，依赖微软服务可达"

    _fallback = [
        Voice("zh-CN-XiaoxiaoNeural", "晓晓 · 女声", "温暖亲切"),
        Voice("zh-CN-XiaoyiNeural", "晓伊 · 女声", "活泼明快"),
        Voice("zh-CN-YunxiNeural", "云希 · 男声", "阳光年轻"),
        Voice("zh-CN-YunjianNeural", "云健 · 男声", "激昂有力"),
        Voice("zh-CN-YunyangNeural", "云扬 · 男声", "专业播报"),
        Voice("zh-CN-YunxiaNeural", "云夏 · 男声", "可爱童声"),
        Voice("zh-CN-liaoning-XiaobeiNeural", "晓北 · 女声", "东北话"),
        Voice("zh-CN-shaanxi-XiaoniNeural", "晓妮 · 女声", "陕西话"),
    ]
    # 中文显示名：微软返回的 FriendlyName 是一长串英文，界面上不好认，这里给主要音色配中文别名
    _ZH_NAMES: dict[str, tuple[str, str]] = {
        "zh-CN-XiaoxiaoNeural": ("晓晓 · 女声", "温暖亲切"),
        "zh-CN-XiaoyiNeural": ("晓伊 · 女声", "活泼明快"),
        "zh-CN-YunxiNeural": ("云希 · 男声", "阳光年轻"),
        "zh-CN-YunjianNeural": ("云健 · 男声", "激昂有力"),
        "zh-CN-YunyangNeural": ("云扬 · 男声", "专业播报"),
        "zh-CN-YunxiaNeural": ("云夏 · 男声", "可爱童声"),
        "zh-CN-liaoning-XiaobeiNeural": ("晓北 · 女声", "东北话"),
        "zh-CN-shaanxi-XiaoniNeural": ("晓妮 · 女声", "陕西话"),
        "zh-HK-HiuGaaiNeural": ("曉佳 · 女声", "粤语"),
        "zh-HK-HiuMaanNeural": ("曉曼 · 女声", "粤语"),
        "zh-HK-WanLungNeural": ("雲龍 · 男声", "粤语"),
        "zh-TW-HsiaoChenNeural": ("曉臻 · 女声", "台湾腔"),
        "zh-TW-YunJheNeural": ("雲哲 · 男声", "台湾腔"),
        "zh-TW-HsiaoYuNeural": ("曉雨 · 女声", "台湾腔"),
    }
    _cache: list[Voice] | None = None

    def ready(self) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, "缺少 edge-tts，请执行 pip install edge-tts"
        return True, ""

    def voices(self) -> list[Voice]:
        if self._cache is not None:
            return self._cache
        try:
            import asyncio

            import edge_tts

            async def _go():
                return await edge_tts.list_voices()

            all_v = asyncio.run(_go())
            zh = [v for v in all_v if str(v.get("Locale", "")).startswith("zh-")]
            # 大陆音色排前面，方言音色排后面
            zh.sort(key=lambda v: (
                0 if v.get("Locale") == "zh-CN" and "-" not in str(v.get("ShortName", "")).split("-")[-1]
                else (1 if v.get("Locale") == "zh-CN" else 2),
                str(v.get("ShortName", "")),
            ))
            out = []
            for v in zh:
                sid = str(v.get("ShortName", ""))
                loc = str(v.get("Locale", ""))
                name, desc = self._ZH_NAMES.get(sid, ("", ""))
                if not name:
                    # 没配中文名的，从 FriendlyName 里剥出可读部分
                    friendly = str(v.get("FriendlyName", sid))
                    name = friendly.replace("Microsoft ", "").split(" Online")[0].strip() or sid
                    desc = loc
                out.append(Voice(sid, name, desc))
            if out:
                self._cache = out
                return out
        except Exception:  # noqa: BLE001
            pass
        self._cache = self._fallback
        return self._fallback

    def synth(self, text: str, voice: str, rate: int, volume: int, out_path: str) -> None:
        import asyncio

        import edge_tts

        async def _go() -> None:
            comm = edge_tts.Communicate(text, voice, rate=_pct(rate), volume=_pct(volume))
            await comm.save(out_path)

        try:
            asyncio.run(_go())
        except Exception as e:  # noqa: BLE001
            raise TTSError(f"Edge 合成失败：{e}") from e


def _pct(value: int) -> str:
    return f"{int(value):+d}%"


# ------------------------------------------------------------------ 注册表

PROVIDERS: list[type[Provider]] = [EdgeProvider]


def get_provider(engine_id: str | None = None) -> Provider:
    """按 ID 取 provider；不传则用配置里的当前引擎。"""
    pid = (engine_id or current_engine_id()).strip().lower()
    for cls in PROVIDERS:
        if cls.id == pid:
            return cls()
    return EdgeProvider()


def list_engines() -> list[dict[str, Any]]:
    out = []
    for cls in PROVIDERS:
        inst = cls()
        ok, reason = inst.ready()
        out.append({
            "id": cls.id,
            "label": cls.label,
            "note": cls.note,
            "ready": ok,
            "reason": reason,
            "default_voice": inst.default_voice(),
        })
    return out
