# -*- coding: utf-8 -*-
"""
环境自检（Windows / Linux / macOS 通用）

检查项：Python 版本、ffmpeg 与编码器、中文字体、规则与图标配置、素材文件、网络连通性。
用法： python 自检.py
"""
from __future__ import annotations

import os
import sys

OK = "[OK]  "
BAD = "[缺失]"
WARN = "[提示]"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
project_ok = True


def head(title: str) -> None:
    print(f"\n--- {title} ---")


def main() -> int:
    global project_ok
    print("=" * 60)
    print("  运行环境自检   ·  文本转语音 + 视频合成")
    print(f"  系统平台: {sys.platform}   Python: {sys.version.split()[0]}")
    print("=" * 60)

    # 1) Python 版本
    head("Python")
    if sys.version_info >= (3, 9):
        print(f"{OK} Python {sys.version.split()[0]}")
    else:
        print(f"{BAD} Python 版本过低（{sys.version.split()[0]}），请升级到 3.9+")
        project_ok = False

    # 2) 第三方依赖
    head("依赖包")
    for mod, pip_name in [
        ("edge_tts", "edge-tts"), ("imageio_ffmpeg", "imageio-ffmpeg"),
        ("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
    ]:
        try:
            __import__(mod)
            print(f"{OK} {pip_name}")
        except ImportError:
            print(f"{BAD} {pip_name}   安装：pip install -r requirements.txt")
            project_ok = False

    # 3) ffmpeg 与编码器
    head("ffmpeg")
    try:
        import core
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} 无法加载 core.py：{e}")
        return 1
    print(f"{OK} ffmpeg 路径: {core.FFMPEG}")
    import subprocess
    try:
        ver = subprocess.run([core.FFMPEG, "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="ignore", timeout=20)
        print(f"{OK} {ver.stdout.splitlines()[0] if ver.stdout else '(版本未知)'}")
    except Exception as e:  # noqa: BLE001
        print(f"{WARN} 读取版本失败：{e}")
    try:
        enc_out = subprocess.run([core.FFMPEG, "-hide_banner", "-encoders"],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="ignore", timeout=20)
        enc_txt = (enc_out.stdout or "") + (enc_out.stderr or "")
    except Exception:  # noqa: BLE001
        enc_txt = ""
    for enc, need in (("libx264", "叠加文字/图标时需要"), ("aac", "音轨编码时需要")):
        has = enc in enc_txt
        print(f"{OK if has else WARN} 编码器 {enc}（{need}）")
        if not has:
            print(f"{WARN} 缺少 {enc}，建议安装系统 ffmpeg：Debian/Ubuntu: sudo apt install ffmpeg")

    # 4) 中文字体
    head("中文字体（画面文字/字幕用）")
    try:
        import caption
        try:
            print(f"{OK} {caption.pick_font()}")
        except RuntimeError as e:
            print(f"{BAD} {e}")
            project_ok = False
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} 无法加载 caption.py：{e}")
        project_ok = False

    # 5) 规则与素材
    head("规则与素材")
    rules = core.load_rules(force=True)
    signals = core.load_signals(force=True)
    print(f"{OK if rules else BAD} 视频规则 {len(rules)} 条；预警图标 {len(signals)} 个")
    print(f"     配置文件: {core.RULES_FILE}")
    for r in rules:
        exists = os.path.exists(r["video"])
        print(f"    {OK if exists else WARN} {r['keywords']} → {r['video']}")
    for s in signals:
        exists = os.path.exists(s["icon"])
        print(f"    {OK if exists else WARN} 图标 {s['keywords']} → {s['icon']}")
    if not any(os.path.exists(r["video"]) for r in rules):
        print(f"{WARN} 没有任何可用视频。把视频放进 {core.VIDEO_DIR} 目录，"
              f"或在 rules.json 里改成 Linux 上的实际路径。")

    # 6) 输出目录可写
    head("输出目录")
    try:
        os.makedirs(core.OUTPUT_DIR, exist_ok=True)
        probe = os.path.join(core.OUTPUT_DIR, ".write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        print(f"{OK} 可写: {core.OUTPUT_DIR}")
    except Exception as e:  # noqa: BLE001
        print(f"{BAD} 不可写: {core.OUTPUT_DIR}  ({e})")
        project_ok = False

    # 7) 文件名编码（成片文件名含中文）
    head("文件名编码")
    fs_enc = sys.getfilesystemencoding().lower()
    if "utf" in fs_enc:
        print(f"{OK} 文件系统编码 {fs_enc}，中文文件名可用")
    else:
        print(f"{WARN} 文件系统编码为 {fs_enc}，成片的中文文件名可能失败")
        print(f"{WARN} 解决：启动时加 export PYTHONUTF8=1（启动.sh 已自带），或 export LANG=zh_CN.UTF-8")
        project_ok = False

    # 8) 语音引擎
    head("语音引擎")
    try:
        import tts
    except Exception as e:  # noqa: BLE001
        print(f"{ERR} tts.py 加载失败：{e}")
        project_ok = False
        engines = []
    else:
        engines = tts.list_engines()
        cur = tts.current_engine_id()
        print(f"    当前引擎：{cur}（改 tts_config.json 的 engine 字段切换）")
        for e in engines:
            mark = OK if e["ready"] else WARN
            flag = " ← 当前" if e["id"] == cur else ""
            print(f"{mark} {e['id']:<10} {e['label']}  音色 {len(tts.get_provider(e['id']).voices())} 个{flag}")
            if not e["ready"]:
                print(f"           {e['reason']}")
        usable = [e for e in engines if e["ready"]]
        if not usable:
            print(f"{ERR} 没有任何可用语音引擎，无法合成语音")
            project_ok = False
        elif not any(e["id"] == cur for e in usable):
            print(f"{WARN} 当前引擎 {cur} 不可用，请换用可用引擎或补全密钥")
            project_ok = False

    # 9) 网络连通性（按当前引擎判断该连哪里）
    head("网络连通性")
    cur = tts.current_engine_id() if engines else "edge"
    probes = []
    if cur == "edge":
        probes = [("speech.platform.bing.com", 443, "微软语音服务")]
    else:
        probes = [("speech.platform.bing.com", 443, "微软语音服务")]
    for host, port, label in probes:
        try:
            import socket
            socket.create_connection((host, port), timeout=6).close()
            print(f"{OK} 可访问 {label}（{host}）")
        except Exception:  # noqa: BLE001
            print(f"{WARN} 无法访问 {host}:{port}，{label} 的语音合成会失败（检查网络/代理）")

    print("\n" + "=" * 60)
    print("  自检完成" + ("：环境正常" if project_ok else "：存在缺失项，请按上面提示处理"))
    print("=" * 60)
    return 0 if project_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("自检脚本异常：", e)
        sys.exit(1)
