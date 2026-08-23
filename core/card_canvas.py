# -*- coding: utf-8 -*-
"""卡片绘制共享画板（v5.41.0 自 core/broadcast_image_card.py 原样抽出）。

职责：承载与具体卡片布局无关的通用绘制原语，供各图片卡模块复用：
  - 跨平台字体池与 LRU 字体加载 font()
  - 文字测量 ts() / 按宽换行 wrap_text()
  - 颜色插值 interpolate_color() / 渐变背景 draw_gradient_background()
  - 带投影圆角矩形 draw_rounded_rect_with_shadow()

迁移纪律：本模块代码自 broadcast_image_card.py 逐字搬运，输出像素必须
与抽取前完全一致；各业务卡片的布局绘制仍留在各自模块内。
"""

from __future__ import annotations
import logging

import functools
import os
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Mory 视觉系统底色（渐变默认值） ──
BG_TOP = (252, 250, 246)        # 顶部暖奶油
BG_BOTTOM = (247, 244, 238)     # 底部浅米

# ── 字体路径 ──
# v5.38.15+：跨平台字体兜底。Windows 走微软雅黑/宋体，Linux 走 Noto CJK/WenQuanYi，
# 任何平台最后都回落仓库自带的 LXGWWenKai-Regular.ttf（deploy_vps.py 现在同步上传 assets/fonts/），
# 避免"hei"/"bold" 风格在 VPS 上全部命中 PIL 默认英文字体 → 汉字变方块豆腐块。
_FONT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "fonts"
)
FONT_KAI = os.path.join(_FONT_DIR, "LXGWWenKai-Regular.ttf")

# Windows 内置中文字体（仅在 nt 平台使用）
_WIN_FONT_HEI = "C:/Windows/Fonts/msyh.ttc"
_WIN_FONT_HEI_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
_WIN_FONT_SONG = "C:/Windows/Fonts/simsun.ttc"

# Linux 常用系统级中文字体（VPS 通过 apt 安装字体包后可命中）
_LINUX_FONT_HEI = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]
_LINUX_FONT_HEI_BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansSC-Bold.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
_LINUX_FONT_SONG = [
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifSC-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

# 对"hei/bold/song"风格，按优先级把 Windows / Linux / 仓库自带字体拼成一个有序列表。
# "kai" 风格保持只用仓库楷体（调用方语义就是要用楷体），不混系统黑体。
if os.name == "nt":
    FONT_HEI_POOL = [_WIN_FONT_HEI, _WIN_FONT_HEI_BOLD, _WIN_FONT_SONG]
    FONT_HEI_BOLD_POOL = [_WIN_FONT_HEI_BOLD, _WIN_FONT_HEI, _WIN_FONT_SONG]
    FONT_SONG_POOL = [_WIN_FONT_SONG, _WIN_FONT_HEI, _WIN_FONT_HEI_BOLD]
else:
    FONT_HEI_POOL = list(_LINUX_FONT_HEI) + list(_LINUX_FONT_SONG)
    FONT_HEI_BOLD_POOL = list(_LINUX_FONT_HEI_BOLD) + list(_LINUX_FONT_HEI)
    FONT_SONG_POOL = list(_LINUX_FONT_SONG) + list(_LINUX_FONT_HEI)

# 最后统一追加仓库自带楷体作为任何平台、任何风格的最终兜底（保证至少能渲染中文）
FONT_HEI_POOL.append(FONT_KAI)
FONT_HEI_BOLD_POOL.append(FONT_KAI)
FONT_SONG_POOL.append(FONT_KAI)
FONT_KAI_POOL = [FONT_KAI] + FONT_SONG_POOL


class FontLoadError(RuntimeError):
    """字体加载失败。"""


@functools.lru_cache(maxsize=128)
def font(size: int, style: str = "kai") -> ImageFont.FreeTypeFont:
    """按风格加载字体，失败时兜底到系统默认。LRU 缓存避免每次循环重新 open 文件句柄。

    v5.38.15+：每个风格使用跨平台有序字体池，Windows / Linux / 仓库自带三层兜底，
    任何风格最终都会落到 LXGWWenKai（仓库内），避免 VPS 上"hei/bold"汉字变方块。
    v5.38.16+：functools.lru_cache(128)，单张卡片循环内相同 (size,style) 命中缓存。
    """
    pool_map = {
        "kai": FONT_KAI_POOL,
        "hei": FONT_HEI_POOL,
        "bold": FONT_HEI_BOLD_POOL,
        "song": FONT_SONG_POOL,
    }
    pool = pool_map.get(style, FONT_HEI_POOL)
    for name in pool:
        if not name:
            continue
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    # 最后兜底：仓库楷体（再失败才是 PIL 默认英文字体，此时大概率系统连仓库字体都没传）
    try:
        return ImageFont.truetype(FONT_KAI, size)
    except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
        logging.getLogger(__name__).debug(f'非致命忽略: {_e}')
    try:
        return ImageFont.load_default()
    except Exception as exc:
        raise FontLoadError(f"无法加载任何字体（最后兜底 LXGWWenKai 也失败，请检查 assets/fonts 是否已部署）: {exc}") from exc


def ts(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """测量文字宽高。"""
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont,
              max_w: int) -> List[str]:
    """按最大宽度自动换行。"""
    lines: List[str] = []
    line = ""
    for ch in text or "":
        if ch == "\n":
            if line:
                lines.append(line)
            line = ""
            continue
        if ts(draw, line + ch, fnt)[0] > max_w and line:
            lines.append(line)
            line = ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


def interpolate_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
    """两色线性插值。"""
    r = max(0.0, min(1.0, ratio))
    return (
        int(c1[0] + (c2[0] - c1[0]) * r),
        int(c1[1] + (c2[1] - c1[1]) * r),
        int(c1[2] + (c2[2] - c1[2]) * r),
    )


def draw_gradient_background(
    img: Image.Image,
    top: Tuple[int, int, int] = BG_TOP,
    bottom: Tuple[int, int, int] = BG_BOTTOM,
) -> None:
    """绘制顶部到底部的微渐变背景（深色主题传入夜色系底色）。"""
    width, height = img.size
    pixels = img.load()
    for y in range(height):
        ratio = y / height
        color = interpolate_color(top, bottom, ratio)
        for x in range(width):
            pixels[x, y] = color


def draw_rounded_rect_with_shadow(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    radius: int,
    fill: Tuple[int, int, int],
    shadow_color: Tuple[int, int, int, int] = (0, 0, 0, 30),
    shadow_offset: int = 4,
    shadow_blur: int = 8,
) -> None:
    """画带投影的圆角矩形。用完临时 shadow Image 立即 close 释放内存。"""
    x1, y1, x2, y2 = box
    shadow: Optional[Image.Image] = None
    blurred: Optional[Image.Image] = None
    try:
        shadow = Image.new(
            "RGBA",
            (x2 - x1 + shadow_blur * 2, y2 - y1 + shadow_blur * 2),
            (0, 0, 0, 0),
        )
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            [(shadow_blur, shadow_blur),
             (shadow.width - shadow_blur, shadow.height - shadow_blur)],
            radius=radius,
            fill=shadow_color,
        )
        blurred = shadow.filter(ImageFilter.GaussianBlur(shadow_blur // 2))
        img.paste(
            blurred,
            (x1 - shadow_blur + shadow_offset, y1 - shadow_blur + shadow_offset),
            blurred,
        )
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    finally:
        if blurred is not None:
            blurred.close()
        if shadow is not None:
            shadow.close()
