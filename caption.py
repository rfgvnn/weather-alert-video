# -*- coding: utf-8 -*-
"""
画面中央文字叠加（字幕板）

生成 ffmpeg 滤镜：
  drawbox  -> 半透明灰色底板，画面正中
  drawtext -> 每行一条，白色文字，水平居中对齐
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import unicodedata

# 按平台依次尝试：Windows -> Linux -> macOS -> fontconfig 查询 -> 目录扫描
FONT_CANDIDATES = [
    # Windows
    (r"C:\Windows\Fonts\msyhbd.ttc", "微软雅黑 粗体"),
    (r"C:\Windows\Fonts\msyh.ttc", "微软雅黑"),
    (r"C:\Windows\Fonts\simhei.ttf", "黑体"),
    (r"C:\Windows\Fonts\Dengb.ttf", "等线 粗体"),
    # Linux：Debian/Ubuntu 的 fonts-noto-cjk、CentOS 的 wqy / cjkuni
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK Bold"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf", "Noto Sans CJK SC Bold"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf", "Noto Sans CJK SC"),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK Bold"),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "文泉驿正黑"),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "文泉驿微米黑"),
    ("/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc", "文泉驿正黑"),
    ("/usr/share/fonts/wqy-microhei/wqy-microhei.ttc", "文泉驿微米黑"),
    ("/usr/share/fonts/cjkuni-uming/uming.ttc", "AR PL UMing"),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", "AR PL UMing"),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", "苹方"),
    ("/System/Library/Fonts/STHeiti Medium.ttc", "华文黑体"),
    ("/Library/Fonts/Arial Unicode.ttf", "Arial Unicode"),
]

# 目录兜底扫描：找名字里带 CJK/汉字库特征的字体
FONT_GLOB_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.join(os.path.expanduser("~"), ".fonts"),
    os.path.join(os.path.expanduser("~"), ".local/share/fonts"),
]
_FONT_NAME_HINTS = ("noto", "cjk", "wqy", "zenhei", "micro", "uming", "ukai", "hei", "song", "ming")

INSTALL_HINT = (
    "中文字体缺失。Linux 上请先安装：\n"
    "  Debian/Ubuntu:  sudo apt install fonts-noto-cjk    （或 fonts-wqy-zenhei）\n"
    "  CentOS/RHEL:    sudo yum install google-noto-sans-cjk-fonts  （或 wqy-zenhei-fonts）\n"
    "  Alpine:         apk add font-noto-cjk\n"
    "装完执行 fc-cache -fv 刷新字体缓存，再运行 自检.py 确认。"
)

# 行首禁则：这些字符不能出现在行首
_NO_LINE_START = "，。、；：？！》）】」』…·,%!?;:.)]}>,》"


def _fc_match_zh() -> str | None:
    """用 fontconfig 查询系统默认中文字体（Linux 上最可靠）。"""
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "-f", "%{file}", ":lang=zh"],
            capture_output=True, text=True, timeout=5,
        )
        p = (r.stdout or "").strip()
        if p and os.path.exists(p):
            return p
    except Exception:  # noqa: BLE001
        pass
    return None


def _scan_font_dirs() -> str | None:
    """在常见字体目录里找名字像中文字体的文件。"""
    for d in FONT_GLOB_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                low = f.lower()
                if not low.endswith((".ttf", ".ttc", ".otf")):
                    continue
                if any(h in low for h in _FONT_NAME_HINTS):
                    return os.path.join(root, f)
    return None


def pick_font() -> str:
    """按平台找到第一个可用的中文字体。"""
    for path, _name in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    # Linux 上用 fontconfig 兜底，最后再扫目录
    p = _fc_match_zh() or _scan_font_dirs()
    if p:
        return p
    raise RuntimeError(INSTALL_HINT)


def char_units(ch: str) -> float:
    """字符宽度估算单位，以字体大小为基准。全角=1.0。"""
    if ch in " \t":
        return 0.32
    # CJK、全角标点、日文假名、韩文都按全角处理
    try:
        name = unicodedata.name(ch, "")
    except Exception:  # noqa: BLE001
        name = ""
    if "FULLWIDTH" in name or "IDEOGRAPHIC" in name or "CJK" in name or "HIRAGANA" in name or "KATAKANA" in name:
        return 1.0
    o = ord(ch)
    if (
        0x2E80 <= o <= 0xA4CF
        or 0xAC00 <= o <= 0xD7A3
        or 0xF900 <= o <= 0xFAFF
        or 0xFE30 <= o <= 0xFE4F
        or 0xFF00 <= o <= 0xFF60
        or 0xFFE0 <= o <= 0xFFE6
    ):
        return 1.0
    if ch.isupper():
        return 0.68
    if ch.isspace():
        return 0.32
    return 0.55


def line_units(line: str) -> float:
    return sum(char_units(c) for c in line)


def wrap_text(text: str, max_units: float, hard_limit: int = 200) -> list[str]:
    """
    均衡折行：先按总宽度估算需要几行，再让每行长度尽量接近平均值，
    并优先在标点处断开、避免在感叹句/问句中间生硬截断。
    """
    flat = " ".join(t.strip() for t in text.splitlines() if t.strip())
    if not flat:
        return []

    seq = [(c, char_units(c)) for c in flat]
    total = sum(u for _, u in seq)
    if total <= max_units:
        return [flat]

    n = max(1, int(math.ceil(total / max_units)))
    target = total / n
    lines: list[str] = []
    cur = ""
    acc = 0.0
    remaining = total
    left = n

    for ch, u in seq:
        # 行首禁则：这些标点不允许出现在行首，直接并到前一行末尾
        if cur and False:
            pass
        if (not cur) and lines and ch in _NO_LINE_START:
            lines[-1] += ch
            remaining -= u
            continue

        cur += ch
        acc += u
        remaining -= u

        if left <= 1 or not cur:
            continue

        prev = cur[-2] if len(cur) >= 2 else ""
        punct_ok = prev in "。！？；，、!?;,"
        room_ok = remaining <= max_units * (left - 1) * 1.05
        hit = acc >= target or (punct_ok and acc >= target * 0.78)
        if room_ok and hit:
            lines.append(cur)
            left -= 1
            cur, acc = "", 0.0
            if left:
                target = max(remaining / left, 1.0)

    if cur:
        lines.append(cur)
    return [l for l in lines if l.strip()][:hard_limit]


def _split_sentences(s: str) -> list[str]:
    """在句号/分句处断开，得到较自然的换行点。"""
    out, buf = [], ""
    for ch in s:
        buf += ch
        if ch in "。！？；!?;" and len(buf) >= 6:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out or [s]


def _hard_wrap(s: str, max_units: float) -> list[str]:
    out, buf, units = [], "", 0.0
    for ch in s:
        u = char_units(ch)
        if units + u > max_units and buf:
            # 行首禁则：把行末的标点挪到下一行开头不合适，反之若下一个字符是标点则一起带过来
            out.append(buf)
            buf, units = "", 0.0
            if ch in _NO_LINE_START and out:
                # 标点跟上一行走
                out[-1] = out[-1] + ch
                continue
        if ch in _NO_LINE_START and out and not buf:
            out[-1] = out[-1] + ch
            continue
        buf += ch
        units += u
    if buf:
        out.append(buf)
    return out


def _compact(lines: list[str], max_units: float) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if merged and line_units(merged[-1]) + line_units(line) <= max_units * 0.96:
            merged[-1] += line
        else:
            merged.append(line)
    return merged


def esc_path(p: str) -> str:
    """转义供 ffmpeg 滤镜参数使用的路径/文本。"""
    return (
        p.replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def write_line_files(lines: list[str], outdir: str) -> list[str]:
    """每行写成一个 UTF-8 文本文件，交给 drawtext 的 textfile 读取（比 text= 更稳，无需转义中文标点）。"""
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i, line in enumerate(lines):
        p = os.path.join(outdir, f"line_{i:03d}.txt")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(line)
        paths.append(p)
    return paths


def build_caption_filters(
    width: int,
    height: int,
    line_files: list[str],
    fontsize: int,
) -> list[str]:
    """
    底部正文：无底板，白色文字 + 粗黑描边，左对齐，贴近画面底部。
    返回可以直接接在其他滤镜后面的滤镜片段列表（不含输入/输出标签）。
    """
    if not line_files:
        return []

    fs = float(fontsize)
    line_h = fs * 1.45
    margin_x = width * 0.08        # 左边距 8%
    block_bottom = height * 0.92   # 文字块底边位置
    block_h = len(line_files) * line_h
    y0 = block_bottom - block_h

    fontfile = esc_path(pick_font())
    parts = []
    for i, tf in enumerate(line_files):
        y = y0 + i * line_h + (line_h - fs) * 0.5
        parts.append(
            "drawtext=fontfile='%s':textfile='%s':reload=0"
            ":x=%.1f:y=%.1f"
            ":fontsize=%d:fontcolor=white"
            ":borderw=%d:bordercolor=black"
            % (fontfile, esc_path(tf), margin_x, y, int(fs), max(2, int(round(fs * 0.11))))
        )
    return parts


def _read_all(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            out.append(f.read())
    return out


# ---------------------------------------------------------------- 右上角标题

# 标题块的位置（占画面宽/高的比例），日期行的定位也依赖这两个值
TITLE_MARGIN_X = 0.10
TITLE_MARGIN_Y = 0.12
TITLE_LINE_H = 1.55


def split_title_lines(title: str) -> list[str]:
    """
    把「XX气象台发布XX预警信号」拆成两行。

    优先在「发布」之后断开——这通常正好在一半附近（如「磁县气象台发布」7 字 /
    「大风蓝色预警信号」8 字），而且不会把「大风」这类词拆散。
    只有当这样切出来两行比例失衡（超过 1.8 倍）时，才退回按字数平均切分。
    """
    t = (title or "").strip()
    if not t:
        return []

    i = t.find("发布")
    if 0 < i < len(t) - 2:
        a, b = t[: i + 2], t[i + 2 :]
        ua, ub = line_units(a), line_units(b)
        if ub > 0 and ua > 0 and max(ua, ub) <= min(ua, ub) * 1.8:
            return [a, b]

    half = (len(t) + 1) // 2
    return [t[:half], t[half:]]


def build_corner_filters(
    width: int,
    height: int,
    line_files: list[str],
    fontsize: int,
    margin_x: float = TITLE_MARGIN_X,
    margin_y: float = TITLE_MARGIN_Y,
) -> list[str]:
    """
    右上角两行小标题：白色文字 + 粗黑描边（无底板），右对齐。
    返回可直接接在其他滤镜后面的片段列表。
    """
    if not line_files:
        return []

    fs = float(fontsize)
    line_h = fs * TITLE_LINE_H
    mx = width * margin_x
    my = height * margin_y

    fontfile = esc_path(pick_font())
    parts = []
    for i, tf in enumerate(line_files):
        y = my + i * line_h
        parts.append(
            "drawtext=fontfile='%s':textfile='%s':reload=0"
            ":x=w-text_w-%.1f:y=%.1f"
            ":fontsize=%d:fontcolor=white"
            ":borderw=%d:bordercolor=black"
            % (fontfile, esc_path(tf), mx, y, int(fs), max(2, int(round(fs * 0.12))))
        )
    return parts


def title_block_bottom(height: int, n_lines: int, fontsize: int) -> float:
    """标题块底边的 y 坐标（日期行紧贴在它下方）。"""
    return height * TITLE_MARGIN_Y + n_lines * fontsize * TITLE_LINE_H


def build_date_filter(
    width: int,
    height: int,
    text_file: str,
    fontsize: int,
    y: float,
) -> list[str]:
    """
    发布日期行：金色粗体 + 黑描边（无底板），水平居中，显示在标题块下方。
    """
    fontfile = esc_path(pick_font())
    return [
        "drawtext=fontfile='%s':textfile='%s':reload=0"
        ":x=(w-text_w)/2:y=%.1f"
        ":fontsize=%d:fontcolor=0xFFD700"
        ":borderw=%d:bordercolor=black"
        % (fontfile, esc_path(text_file), y, int(fontsize), max(2, int(round(fontsize * 0.11))))
    ]
