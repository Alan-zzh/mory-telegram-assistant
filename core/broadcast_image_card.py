# -*- coding: utf-8 -*-
"""播报图片卡绘制模块 v4.6。

把 runtime/demo_broadcast_card_v4.py 中的绘制逻辑抽象为可复用生产模块，
支持黄历、塔罗、易经、新闻、问候、定点播报等多种卡片的统一视觉输出。

设计约束：
- 仅依赖 PIL，不调用模型池
- 输出 PNG，适配移动端竖屏
- 右下角保留 "Mory / 沫沫的沫" 品牌印章
- 底部 CTA 按钮视觉（真实可点击入口由调用方以 InlineKeyboard 方式附加）
- v4.6：font() LRU 缓存 + 临时 Image 显式 close + 单区块异常隔离
"""

from __future__ import annotations

import functools
import logging
import os
import random
import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_logger = logging.getLogger(__name__)


# ── Mory 视觉系统配色 ──
BG_TOP = (252, 250, 246)        # 顶部暖奶油
BG_BOTTOM = (247, 244, 238)     # 底部浅米
INK = (26, 26, 26)              # 深字（接近黑但不纯黑）
INK_SOFT = (80, 80, 80)         # 次深字
GREEN = (45, 95, 79)            # 墨绿主色
GREEN_BG = (232, 240, 234)      # 浅墨绿底块
GREEN_DARK = (35, 75, 62)       # 深墨绿（标题可用）
GREEN_LIGHT = (75, 135, 115)    # 亮墨绿（渐变用）
GREEN_LINE = (180, 200, 188)    # 浅墨绿线
RED = (170, 65, 58)             # 朱砂
RED_BG = (245, 236, 234)        # 浅朱砂底
RED_LIGHT = (200, 95, 85)       # 亮朱砂（渐变用）
GRAY = (140, 140, 140)          # 次要灰
GOLD = (201, 169, 110)          # 暖金
GOLD_BG = (250, 245, 235)       # 浅金底
GOLD_DARK = (175, 145, 90)      # 深暖金
WHITE = (255, 255, 255)

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

# ── 默认布局常量 ──
DEFAULT_WIDTH = 800
DEFAULT_MARGIN = 56
DEFAULT_RADIUS = 16
DEFAULT_CTA_RADIUS = 24
DEFAULT_TAG_RADIUS = 16


class FontLoadError(RuntimeError):
    """字体加载失败。"""


_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs（含 👀）
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
    "\U0001FA00-\U0001FA6F"  # Chess Symbols
    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "]+",
    flags=re.UNICODE,
)


def strip_visual_emoji(text: str) -> str:
    """图片卡视觉文字去掉 emoji，避免 PIL 渲染为 tofu/方框。

    真实可点击按钮仍由调用方传入含 emoji 的文案；这里只影响图片上印的字。
    """
    if not isinstance(text, str):
        return ""
    cleaned = _EMOJI_RE.sub("", text).strip()
    # 顺手清理常见零宽连接符残留
    cleaned = cleaned.replace("\u200d", "").replace("\ufe0f", "").strip()
    return cleaned


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
    except Exception:
        pass
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


def _interpolate_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
    """两色线性插值。"""
    r = max(0.0, min(1.0, ratio))
    return (
        int(c1[0] + (c2[0] - c1[0]) * r),
        int(c1[1] + (c2[1] - c1[1]) * r),
        int(c1[2] + (c2[2] - c1[2]) * r),
    )


def _draw_gradient_background(img: Image.Image) -> None:
    """绘制顶部到底部的微渐变背景。"""
    width, height = img.size
    pixels = img.load()
    for y in range(height):
        ratio = y / height
        color = _interpolate_color(BG_TOP, BG_BOTTOM, ratio)
        for x in range(width):
            pixels[x, y] = color


def _draw_top_bar(draw: ImageDraw.ImageDraw, width: int) -> None:
    """绘制顶部墨绿装饰条。"""
    # 顶部一条细墨绿条 + 底部金色细线
    draw.rectangle([(0, 0), (width, 10)], fill=GREEN)
    draw.rectangle([(0, 10), (width, 13)], fill=GOLD)


def _draw_cloud_pattern(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """绘制极浅云纹纹理背景。"""
    color = (242, 236, 226)
    for i in range(8):
        x = 40 + i * 95
        y = 40 + (i % 3) * 210
        draw.arc([(x, y), (x + 90, y + 44)], start=0, end=180, fill=color, width=2)
    for i in range(6):
        x = 580 + i * 55
        y = 160 + (i % 4) * 230
        draw.arc([(x, y), (x + 70, y + 34)], start=180, end=360, fill=color, width=2)


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


def draw_brand_stamp(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    brand_top: str = "Mory",
    brand_bot: str = "沫沫的沫",
    f_top_size: int = 26,
    f_bot_size: int = 18,
) -> Tuple[int, int]:
    """绘制右下角品牌印章，返回实际占用宽高（不依赖外部 img）。"""
    f_top = font(f_top_size, "kai")
    f_bot = font(f_bot_size, "kai")
    tw, th = ts(draw, brand_top, f_top)
    bw, bh = ts(draw, brand_bot, f_bot)
    stamp_w = max(tw, bw) + 28
    stamp_h = th + bh + 22
    return stamp_w, stamp_h


def _render_brand_stamp(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
) -> Tuple[int, int]:
    """实际渲染品牌印章。用完 shadow 临时 Image 立即 close。"""
    f_top = font(26, "kai")
    f_bot = font(18, "kai")
    tw, th = ts(draw, "Mory", f_top)
    bw, bh = ts(draw, "沫沫的沫", f_bot)
    stamp_w = max(tw, bw) + 28
    stamp_h = th + bh + 22
    shadow: Optional[Image.Image] = None
    blurred: Optional[Image.Image] = None
    try:
        # 印章投影
        shadow = Image.new(
            "RGBA",
            (stamp_w + 12, stamp_h + 12),
            (0, 0, 0, 0),
        )
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            [(6, 6), (stamp_w + 6, stamp_h + 6)],
            radius=10,
            fill=(0, 0, 0, 35),
        )
        blurred = shadow.filter(ImageFilter.GaussianBlur(4))
        img.paste(blurred, (x - 6 + 2, y - 6 + 2), blurred)
    finally:
        if blurred is not None:
            blurred.close()
        if shadow is not None:
            shadow.close()

    # 印章底色 + 边框
    draw.rounded_rectangle([(x, y), (x + stamp_w, y + stamp_h)], radius=10, fill=RED)
    draw.rounded_rectangle(
        [(x + 2, y + 2), (x + stamp_w - 2, y + stamp_h - 2)],
        radius=8,
        outline=(255, 255, 255, 60),
        width=1,
    )
    draw.text((x + (stamp_w - tw) // 2, y + 10), "Mory", font=f_top, fill=WHITE)
    draw.text((x + (stamp_w - bw) // 2, y + th + 14), "沫沫的沫", font=f_bot, fill=WHITE)
    return stamp_w, stamp_h


def _draw_cta_button(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    width: int,
    margin: int = DEFAULT_MARGIN,
    f_size: int = 15,
) -> Tuple[int, int, int, int]:
    """绘制底部渐变 CTA 按钮视觉，返回按钮包围盒。用完 shadow 立即 close。"""
    text = strip_visual_emoji(text)
    f_footer = font(f_size, "hei")
    cw, ch = ts(draw, text, f_footer)
    btn_w = min(cw + 56, width - 2 * margin)
    btn_h = ch + 26
    btn_x = (width - btn_w) // 2
    btn_y = y

    shadow: Optional[Image.Image] = None
    blurred: Optional[Image.Image] = None
    try:
        # 按钮投影
        shadow = Image.new(
            "RGBA",
            (btn_w + 16, btn_h + 16),
            (0, 0, 0, 0),
        )
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle(
            [(8, 8), (btn_w + 8, btn_h + 8)],
            radius=DEFAULT_CTA_RADIUS,
            fill=(0, 0, 0, 40),
        )
        blurred = shadow.filter(ImageFilter.GaussianBlur(6))
        img.paste(blurred, (btn_x - 8 + 3, btn_y - 8 + 4), blurred)
    finally:
        if blurred is not None:
            blurred.close()
        if shadow is not None:
            shadow.close()

    # 渐变按钮底色（上亮下深）：渐变层 + 圆角 mask，避免四角镂空
    gradient = Image.new("RGBA", (btn_w, btn_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for dy in range(btn_h):
        ratio = dy / btn_h
        color = _interpolate_color(GREEN_LIGHT, GREEN_DARK, ratio)
        gd.line([(0, dy), (btn_w, dy)], fill=color, width=1)
    mask = Image.new("L", (btn_w, btn_h), 0)
    try:
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle(
            [(0, 0), (btn_w, btn_h)],
            radius=DEFAULT_CTA_RADIUS,
            fill=255,
        )
        img.paste(gradient, (btn_x, btn_y), mask)
    finally:
        mask.close()
        gradient.close()
    draw.rounded_rectangle(
        [(btn_x, btn_y), (btn_x + btn_w, btn_y + btn_h)],
        radius=DEFAULT_CTA_RADIUS,
        fill=None,
        outline=(255, 255, 255, 40),
        width=1,
    )
    draw.text((btn_x + (btn_w - cw) // 2, btn_y + (btn_h - ch) // 2 + 1),
              text, font=f_footer, fill=WHITE)
    return btn_x, btn_y, btn_x + btn_w, btn_y + btn_h


def _draw_title_area(
    draw: ImageDraw.ImageDraw,
    payload: dict,
    width: int,
    margin: int,
    y: int,
) -> int:
    """绘制非对称标题区（标题 + kicker 标签 + 日期标签），返回新的 y。"""
    f_title = font(52, "kai")
    f_kicker = font(18, "hei")
    f_date = font(18, "hei")

    title = str(payload.get("title", "") or "")
    kicker = str(payload.get("kicker", "") or "")
    date_text = str(payload.get("date_text", "") or "")
    if not date_text:
        meta = str(payload.get("meta", "") or "")
        parts = [p.strip() for p in meta.split("｜")]
        for part in parts:
            if "农历" in part:
                date_text = part.replace("农历", "").strip()
                break
        if not date_text and parts:
            # 取最后一个较短的作为日期
            short_parts = [p for p in parts if len(p) <= 12]
            if short_parts:
                date_text = short_parts[-1]

    # 日期标签放右上角
    if date_text:
        dt_w, dt_h = ts(draw, date_text, f_date)
        tag_w = dt_w + 24
        tag_h = dt_h + 14
        tag_x = width - margin - tag_w
        tag_y = y + 4
        draw.rounded_rectangle(
            [(tag_x, tag_y), (tag_x + tag_w, tag_y + tag_h)],
            radius=12,
            fill=GOLD_BG,
        )
        draw.text((tag_x + 12, tag_y + 7), date_text, font=f_date, fill=GOLD_DARK)

    # 主标题
    draw.text((margin, y), title, font=f_title, fill=GREEN_DARK)
    title_w, title_h = ts(draw, title, f_title)

    y += title_h + 14

    # kicker 用色块标签
    if kicker:
        kw, kh = ts(draw, kicker, f_kicker)
        tag_h = kh + 12
        tag_w = kw + 22
        draw.rounded_rectangle(
            [(margin, y), (margin + tag_w, y + tag_h)],
            radius=10,
            fill=GREEN_BG,
        )
        draw.text((margin + 11, y + 6), kicker, font=f_kicker, fill=GREEN)
        y += tag_h + 22
    else:
        y += 10

    return y


def _draw_section_divider(
    draw: ImageDraw.ImageDraw,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制精致分隔线：金色短线 + 中心菱形。"""
    center = width // 2
    line_y = y + 8
    # 左右短线
    draw.line([(margin + 60, line_y), (center - 16, line_y)], fill=GOLD, width=2)
    draw.line([(center + 16, line_y), (width - margin - 60, line_y)], fill=GOLD, width=2)
    # 中心菱形
    diamond = [(center, line_y - 5), (center + 5, line_y), (center, line_y + 5), (center - 5, line_y)]
    draw.polygon(diamond, fill=GOLD)
    return y + 24


def draw_block_two_column(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    block: dict,
    x: int,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制宜忌类双栏卡片，返回新的 y。"""
    f_section = font(24, "kai")
    f_body = font(22, "hei")

    heading = str(block.get("heading", "") or "")
    if heading:
        draw.rounded_rectangle([(x + margin, y + 6), (x + margin + 5, y + 30)], radius=2, fill=GREEN)
        draw.text((x + margin + 14, y), heading, font=f_section, fill=GREEN_DARK)
        y += 40

    lines = block.get("lines", []) or []
    left_items, right_items = [], []
    left_label, right_label = "宜", "忌"
    for label, value in lines:
        items = [s.strip() for s in str(value).split("·") if s.strip()]
        if "宜" in label:
            left_items, left_label = items, str(label).replace("📌", "").strip()
        elif "忌" in label:
            right_items, right_label = items, str(label).replace("📌", "").strip()

    col_w = (width - 2 * margin - 36) // 2
    lx, rx = margin, margin + col_w + 36

    # 按实际内容计算行高，再取左右最大高度，保证完全对称
    line_h = 44
    header_h = 68
    min_h = 180
    left_h = header_h + max(len(left_items), 1) * line_h + 24
    right_h = header_h + max(len(right_items), 1) * line_h + 24
    box_h = max(left_h, right_h, min_h)

    # 宜栏
    draw_rounded_rect_with_shadow(img, draw, (lx, y, lx + col_w, y + box_h),
                                  DEFAULT_RADIUS, GREEN_BG)
    draw.text((lx + 22, y + 18), left_label, font=f_section, fill=GREEN)
    draw.line([(lx + 22, y + 50), (lx + col_w - 22, y + 50)], fill=GREEN, width=2)
    yy = y + 68
    for item in left_items:
        draw.ellipse([(lx + 24, yy + 10), (lx + 34, yy + 20)], fill=GREEN)
        draw.text((lx + 44, yy), item, font=f_body, fill=INK)
        yy += line_h

    # 忌栏
    draw_rounded_rect_with_shadow(img, draw, (rx, y, rx + col_w, y + box_h),
                                  DEFAULT_RADIUS, RED_BG)
    draw.text((rx + 22, y + 18), right_label, font=f_section, fill=RED)
    draw.line([(rx + 22, y + 50), (rx + col_w - 22, y + 50)], fill=RED, width=2)
    jy = y + 68
    for item in right_items:
        draw.ellipse([(rx + 24, jy + 10), (rx + 34, jy + 20)], fill=RED)
        draw.text((rx + 44, jy), item, font=f_body, fill=INK)
        jy += line_h

    return y + box_h + 30


def draw_block_key_value(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    block: dict,
    y: int,
    margin: int,
) -> int:
    """绘制键值对区块（日值参考 / 节气提醒），返回新的 y。"""
    f_small = font(16, "hei")
    f_label = font(16, "hei")
    heading = str(block.get("heading", "") or "")
    if heading:
        draw.rounded_rectangle([(margin, y + 6), (margin + 5, y + 30)], radius=2, fill=GREEN)
        draw.text((margin + 14, y), heading, font=font(24, "kai"), fill=GREEN_DARK)
        y += 40
    for label, value in block.get("lines", []) or []:
        # 左侧小色块标签
        lw, lh = ts(draw, str(label), f_label)
        tag_w = lw + 16
        tag_h = lh + 10
        draw.rounded_rectangle([(margin, y), (margin + tag_w, y + tag_h)],
                               radius=6, fill=GOLD_BG)
        draw.text((margin + 8, y + 5), str(label), font=f_label, fill=GOLD_DARK)
        draw.text((margin + tag_w + 14, y + 5), str(value), font=f_small, fill=INK_SOFT)
        y += 34
    return y + 20


def draw_block_list(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    block: dict,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制列表区块（塔罗牌阵 / 易经卦象 / 新闻列表），返回新的 y。"""
    f_section = font(24, "kai")
    f_body = font(20, "hei")

    heading = str(block.get("heading", "") or "")
    if heading:
        # 左侧小竖条装饰
        draw.rounded_rectangle([(margin, y + 6), (margin + 5, y + 30)], radius=2, fill=GREEN)
        draw.text((margin + 14, y), heading, font=f_section, fill=GREEN_DARK)
        y += 40

    for idx, (label, value) in enumerate(block.get("lines", []) or []):
        # 行号/序号小圆点
        dot_color = GOLD if idx % 2 == 0 else GREEN
        if str(label).isdigit() or str(label).endswith("."):
            # 新闻编号
            display_label = str(label).rstrip(".") + "."
            draw.rounded_rectangle([(margin, y), (margin + 28, y + 26)], radius=6, fill=GOLD_BG)
            lw, _ = ts(draw, display_label, font(14, "hei"))
            draw.text((margin + (28 - lw) // 2, y + 3), display_label, font=font(14, "hei"), fill=GOLD_DARK)
            line_text = str(value)
            text_x = margin + 40
        else:
            draw.ellipse([(margin + 6, y + 9), (margin + 14, y + 17)], fill=dot_color)
            line_text = f"{label}　{value}"
            text_x = margin + 26

        # 内容换行支持
        max_text_w = width - margin - text_x
        wrapped = wrap_text(draw, line_text, f_body, max_text_w)
        for ln in wrapped:
            draw.text((text_x, y), ln, font=f_body, fill=INK)
            y += 30
        y += 6
    return y + 20


def draw_insight_card(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    insight: str,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制 insight 语录卡片，返回新的 y。"""
    f_insight = font(20, "hei")
    lines = wrap_text(draw, insight, f_insight, width - 2 * margin - 72)
    if not lines:
        return y
    i_h = len(lines) * 32 + 52

    # 渐变边框效果：先画大一点的金色底，再画浅绿内底
    draw.rounded_rectangle(
        [(margin + 2, y + 2), (width - margin + 2, y + i_h + 2)],
        radius=14,
        fill=GOLD_BG,
    )
    draw_rounded_rect_with_shadow(
        img, draw,
        (margin, y, width - margin, y + i_h),
        radius=14,
        fill=GREEN_BG,
        shadow_color=(0, 0, 0, 18),
        shadow_offset=2,
        shadow_blur=6,
    )
    # 左侧渐变条
    for dy in range(i_h - 8):
        ratio = dy / (i_h - 8)
        color = _interpolate_color(GOLD, GREEN_LIGHT, ratio)
        draw.line([(margin + 4, y + 4 + dy), (margin + 8, y + 4 + dy)], fill=color, width=1)
    # 引号装饰
    draw.text((margin + 18, y + 6), "\u201c", font=font(32, "kai"), fill=(200, 215, 205))
    iy = y + 24
    for ln in lines:
        draw.text((margin + 30, iy), ln, font=f_insight, fill=INK)
        iy += 32
    return y + i_h + 28


def draw_tags(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    title: str,
    tags: List[Tuple[str, str, Tuple[int, int, int], Tuple[int, int, int]]],
    y: int,
    width: int,
    margin: int,
    cols: int = 6,
) -> int:
    """绘制药丸形标签网格（如时辰吉凶），返回新的 y。"""
    f_section = font(24, "kai")
    f_tag = font(14, "hei")

    if not tags:
        return y

    draw.text((margin, y), title, font=f_section, fill=GREEN_DARK)
    y += 40

    tag_w = (width - 2 * margin - (cols - 1) * 12) // cols
    tag_h = 36
    for i, (name, value, fg, bg) in enumerate(tags):
        row = i // cols
        col = i % cols
        x = margin + col * (tag_w + 12)
        yy = y + row * (tag_h + 10)
        draw_rounded_rect_with_shadow(
            img, draw,
            (x, yy, x + tag_w, yy + tag_h),
            radius=DEFAULT_TAG_RADIUS,
            fill=bg,
            shadow_color=(0, 0, 0, 12),
            shadow_offset=1,
            shadow_blur=4,
        )
        label = f"{name}"
        value_text = str(value)
        lw, _ = ts(draw, label, f_tag)
        vw, _ = ts(draw, value_text, f_tag)
        draw.text((x + 10, yy + 8), label, font=f_tag, fill=GRAY)
        draw.text((x + tag_w - vw - 10, yy + 8), value_text, font=f_tag, fill=fg)
        # 中间小分隔
        draw.line([(x + tag_w // 2, yy + 8), (x + tag_w // 2, yy + tag_h - 8)], fill=(220, 220, 220), width=1)
    rows = (len(tags) + cols - 1) // cols
    return y + rows * (tag_h + 10) + 22


def draw_footer_lines(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    lines: List[Tuple[str, str]],
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制底部信息条（财神方位等），返回新的 y。"""
    f_small = font(16, "hei")
    if not lines:
        return y
    # 计算总宽度
    total_w = 0
    widths = []
    for label, value in lines:
        text = f"{label}：{value}"
        w, _ = ts(draw, text, f_small)
        widths.append(w)
        total_w += w + 50
    total_w -= 50

    box_h = 46
    box_x = max(margin, (width - total_w) // 2 - 20)
    box_w = min(width - 2 * margin, total_w + 40)
    draw_rounded_rect_with_shadow(
        img, draw,
        (box_x, y, box_x + box_w, y + box_h),
        radius=12,
        fill=GOLD_BG,
        shadow_color=(0, 0, 0, 12),
        shadow_offset=1,
        shadow_blur=4,
    )
    x = box_x + 20
    for (label, value), w in zip(lines, widths):
        text = f"{label}：{value}"
        draw.text((x, y + 12), text, font=f_small, fill=INK_SOFT)
        x += w + 50
    return y + box_h + 24


def _render_block_safe(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    block: dict,
    y: int,
    width: int,
    margin: int,
) -> int:
    """单个区块绘制：出错记日志跳过，y 前进占位避免塌陷。"""
    style = block.get("style", "list")
    heading = str(block.get("heading", "") or "")
    try:
        if style == "two_column":
            return draw_block_two_column(img, draw, block, 0, y, width, margin)
        if style == "key_value":
            return draw_block_key_value(img, draw, block, y, margin)
        return draw_block_list(img, draw, block, y, width, margin)
    except Exception as exc:
        _logger.warning("skip block style=%s heading=%r: %s", style, heading[:30], exc)
        # 占位高度：按 list 默认一行估算，避免后续内容上移错位
        return y + 80


def draw_card(
    payload: dict,
    out: str,
    cta: str = None,
    width: int = DEFAULT_WIDTH,
    min_height: int = 1000,
    options: dict = None,
) -> Tuple[str, dict]:
    """通用图片卡绘制入口。

    参数：
        payload: 标准化播报数据，字段见下
        out: 输出 PNG 路径
        cta: 底部按钮文案（纯视觉，真实按钮由调用方附加）
        width: 图片宽度
        min_height: 最小高度（内容少时占位）
        options: 扩展选项（当前保留兼容，未启用新字段）

    payload 字段：
        title: 标题
        kicker: 副标题（可选）
        meta: 元信息（可选）
        date_text: 右上角日期文字（可选，默认从 meta 提取）
        blocks: 内容区块列表，每个 block 支持 style 字段：
            - "two_column": 宜忌双栏
            - "key_value": 键值对
            - "list": 普通列表（默认）
        insight: 语录/提示卡片（可选）
        tags: [(name, value, fg_color, bg_color), ...]（可选）
        tags_title: tags 的标题（可选）
        footer_lines: [(label, value), ...]（可选）
        time_text: 播报时间（可选）

    返回：
        (out, info_dict)
    """
    opts = options or {}
    margin = opts.get("margin", DEFAULT_MARGIN)

    tmp: Optional[Image.Image] = None
    img: Optional[Image.Image] = None
    try:
        # 先创建临时画布估算高度
        tmp = Image.new("RGB", (width, 4000), WHITE)
        tmp_draw = ImageDraw.Draw(tmp)
        y = 70
        y = _draw_title_area(tmp_draw, payload, width, margin, y)
        y = _draw_section_divider(tmp_draw, y, width, margin)

        blocks = payload.get("blocks", []) or []
        for block in blocks:
            y = _render_block_safe(tmp, tmp_draw, block, y, width, margin)

        insight = str(payload.get("insight", "") or "")
        if insight:
            try:
                y = draw_insight_card(tmp, tmp_draw, insight, y, width, margin)
            except Exception as exc:
                _logger.warning("skip insight(tmp): %s", exc)
                y += 120

        tags = payload.get("tags")
        if tags:
            try:
                y = draw_tags(tmp, tmp_draw, payload.get("tags_title", ""), tags,
                              y, width, margin)
            except Exception as exc:
                _logger.warning("skip tags(tmp): %s", exc)
                y += 120

        footer_lines = payload.get("footer_lines")
        if footer_lines:
            try:
                y = draw_footer_lines(tmp, tmp_draw, footer_lines, y, width, margin)
            except Exception as exc:
                _logger.warning("skip footer_lines(tmp): %s", exc)
                y += 60

        time_text = str(payload.get("time_text", "") or "")
        if time_text:
            try:
                f_time = font(18, "hei")
                tw, _ = ts(tmp_draw, time_text, f_time)
                tmp_draw.text(((width - tw) / 2, y), time_text, font=f_time, fill=GRAY)
                y += 32
            except Exception as exc:
                _logger.warning("skip time_text(tmp): %s", exc)

        # 底部留白 + CTA + 印章
        cta_text = strip_visual_emoji(cta or "")
        footer_reserve = 170 if cta_text else 120
        content_bottom = y + footer_reserve
        height = max(min_height, content_bottom)

        # 正式绘制
        img = Image.new("RGB", (width, height), BG_TOP)
        draw = ImageDraw.Draw(img)
        _draw_gradient_background(img)
        _draw_cloud_pattern(draw, width, height)
        _draw_top_bar(draw, width)

        # 外框
        draw.rounded_rectangle([(22, 22), (width - 22, height - 22)],
                               radius=DEFAULT_RADIUS, outline=GREEN_LINE, width=2)
        draw.rounded_rectangle([(30, 30), (width - 30, height - 30)],
                               radius=12, outline=(215, 228, 220), width=1)

        y = 70
        y = _draw_title_area(draw, payload, width, margin, y)
        y = _draw_section_divider(draw, y, width, margin)

        for block in blocks:
            y = _render_block_safe(img, draw, block, y, width, margin)

        if insight:
            try:
                y = draw_insight_card(img, draw, insight, y, width, margin)
            except Exception as exc:
                _logger.warning("skip insight: %s", exc)
                y += 120

        if tags:
            try:
                y = draw_tags(img, draw, payload.get("tags_title", ""), tags,
                              y, width, margin)
            except Exception as exc:
                _logger.warning("skip tags: %s", exc)
                y += 120

        if footer_lines:
            try:
                y = draw_footer_lines(img, draw, footer_lines, y, width, margin)
            except Exception as exc:
                _logger.warning("skip footer_lines: %s", exc)
                y += 60

        if time_text:
            try:
                f_time = font(18, "hei")
                tw, _ = ts(draw, time_text, f_time)
                draw.text(((width - tw) / 2, y), time_text, font=f_time, fill=GRAY)
                y += 32
            except Exception as exc:
                _logger.warning("skip time_text: %s", exc)

        # 底部分隔线
        draw.line([(margin, height - 130), (width - margin, height - 130)],
                  fill=GREEN_LINE, width=1)

        # CTA 按钮视觉
        if cta_text:
            try:
                _draw_cta_button(img, draw, cta_text, height - 115, width, margin)
            except Exception as exc:
                _logger.warning("skip cta_button: %s", exc)

        # 品牌印章（使用临时画布已测量的尺寸精确定位）
        stamp_w, stamp_h = draw_brand_stamp(tmp_draw, x=0, y=0)
        try:
            _render_brand_stamp(
                img, draw,
                x=width - margin - stamp_w,
                y=height - 115,
            )
        except Exception as exc:
            _logger.warning("skip brand_stamp: %s", exc)

        # 保存
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        img.save(out, "PNG")
        info = {
            "path": out,
            "width": width,
            "height": height,
            "size_kb": os.path.getsize(out) // 1024,
            "cta": cta_text,
        }
        return out, info
    finally:
        if tmp is not None:
            tmp.close()
        if img is not None:
            img.close()


# ── CTA 文案池 ──
MYSTIC_CTA_VARIANTS = [
    "问 Mory 专属风水 · 点击头像",
    "找 Mory 单独抽牌 · 点击头像",
    "找 Mory 问一卦 · 点击头像",
    "想看个人专属运势 · 点击头像",
    "每日推送已更新 · 点击头像订阅",
    "会员群今日已更新 · 点击头像加入",
    "需要专属服务 · 点击头像开始自助",
    "点击头像 · 了解更多",
]

NEWS_CTA_VARIANTS = [
    "Mory 每日播报",
    "每日资讯 · 与你有关",
]

GREETING_CTA_VARIANTS = [
    "看看预览",
]

SCHEDULED_CTA_VARIANTS = [
    "看看预览",
    "点击头像 · 了解更多",
    "需要专属服务 · 点击头像",
]


def get_random_cta(pool_name: str = "mystic", rng: random.Random = None) -> str:
    """从指定 CTA 池中随机抽取文案。"""
    pools = {
        "mystic": MYSTIC_CTA_VARIANTS,
        "news": NEWS_CTA_VARIANTS,
        "greeting": GREETING_CTA_VARIANTS,
        "scheduled": SCHEDULED_CTA_VARIANTS,
    }
    pool = pools.get(pool_name, MYSTIC_CTA_VARIANTS)
    if rng is None:
        rng = random.Random()
    return rng.choice(pool)


def build_broadcast_image_card(
    payload: dict,
    cache_key: str,
    cta_pool: str = "mystic",
    config: dict = None,
    min_height: int = 1000,
    cta_text: str = "",
) -> str | None:
    """通用图片卡生成入口，返回本地 PNG 路径；失败返回 None。

    cache_key 用于构造文件名，建议包含类型与日期，避免冲突。
    cta_text 由调用方传入（与真实按钮一致）；为空时图片卡不绘制按钮，避免无入口场景出现假按钮。
    """
    try:
        safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(cache_key))[:80]
        final_cta = cta_text or ""

        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "runtime", "cache", "broadcast"
        )
        os.makedirs(cache_dir, exist_ok=True)
        out_path = os.path.join(cache_dir, f"{safe_key}.png")
        _, info = draw_card(payload, out=out_path, cta=final_cta, min_height=min_height)
        logger = None
        try:
            from core.logging_util import get_logger
            logger = get_logger("broadcast_image_card")
        except Exception:
            pass
        if logger:
            logger.info(f"[image_card] 已生成: {out_path} ({info['size_kb']} KB)")
        return out_path
    except Exception as e:
        try:
            from core.logging_util import get_logger
            get_logger("broadcast_image_card").warning(f"[image_card] 生成失败: {e}")
        except Exception:
            pass
        return None
