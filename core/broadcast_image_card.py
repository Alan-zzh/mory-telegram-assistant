# -*- coding: utf-8 -*-
"""播报图片卡绘制模块 v4.6。

把 runtime/demo_broadcast_card_v4.py 中的绘制逻辑抽象为可复用生产模块，
支持黄历、塔罗、易经、新闻、问候、定点播报等多种卡片的统一视觉输出。

设计约束：
- 仅依赖 PIL，不调用模型池
- 输出 PNG，适配移动端竖屏
- 右下角保留 "Mory / 沫沫的沫" 品牌印章
- 图片内不再绘制 CTA 按钮视觉（真实可点击按钮由调用方以 Telegram InlineKeyboard 附加，图片只管画面）
- v4.6：font() LRU 缓存 + 临时 Image 显式 close + 单区块异常隔离
"""

from __future__ import annotations

import contextvars
import functools
import logging
import os
import re
import time
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
DEFAULT_CTA_RADIUS = 18
DEFAULT_TAG_RADIUS = 8


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


def _draw_gradient_background(
    img: Image.Image,
    top: Tuple[int, int, int] = BG_TOP,
    bottom: Tuple[int, int, int] = BG_BOTTOM,
) -> None:
    """绘制顶部到底部的微渐变背景（深色主题传入夜色系底色）。"""
    width, height = img.size
    pixels = img.load()
    for y in range(height):
        ratio = y / height
        color = _interpolate_color(top, bottom, ratio)
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

    # 渐变按钮底色（上亮下深，可被主题覆盖）：渐变层 + 圆角 mask，避免四角镂空
    cta_top = _theme_color("cta_top", GREEN_LIGHT)
    cta_bottom = _theme_color("cta_bottom", GREEN_DARK)
    gradient = Image.new("RGBA", (btn_w, btn_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for dy in range(btn_h):
        ratio = dy / btn_h
        color = _interpolate_color(cta_top, cta_bottom, ratio)
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

    # 主标题（主题可选覆盖标题色，缺省墨绿）
    draw.text((margin, y), title, font=f_title, fill=_theme_color("title", GREEN_DARK))
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
    """绘制精致分隔线：金色短线 + 中心菱形（深色主题随主题提亮）。"""
    center = width // 2
    line_y = y + 8
    divider_color = _theme_color("divider", GOLD)
    diamond_color = _theme_color("gold_accent", GOLD)
    # 左右短线
    draw.line([(margin + 60, line_y), (center - 16, line_y)], fill=divider_color, width=2)
    draw.line([(center + 16, line_y), (width - margin - 60, line_y)], fill=divider_color, width=2)
    # 中心菱形
    diamond = [(center, line_y - 5), (center + 5, line_y), (center, line_y + 5), (center - 5, line_y)]
    draw.polygon(diamond, fill=diamond_color)
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
    """绘制宜忌类双栏卡片，返回新的 y。忌栏底色与强调色随主题切换，
    深色主题下两栏同族深底、近白文字，不允许局部停留在浅色材质。"""
    f_section = font(24, "kai")
    f_body = font(22, "hei")

    heading = str(block.get("heading", "") or "")
    if heading:
        draw.rounded_rectangle([(x + margin, y + 6), (x + margin + 5, y + 30)], radius=2,
                               fill=_theme_color("green_accent", GREEN))
        draw.text((x + margin + 14, y), heading, font=f_section, fill=_theme_color("heading", GREEN_DARK))
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

    # 宜忌栏强调色：浅色主题墨绿/朱砂，深色主题提亮变体（色相不变、明度上抬）
    yi_color = _theme_color("green_accent", GREEN)
    ji_color = _theme_color("red_accent", RED)

    # 宜栏（区块底色可被主题覆盖）
    draw_rounded_rect_with_shadow(img, draw, (lx, y, lx + col_w, y + box_h),
                                  DEFAULT_RADIUS, _theme_color("block_bg", GREEN_BG))
    draw.text((lx + 22, y + 18), left_label, font=f_section, fill=yi_color)
    draw.line([(lx + 22, y + 50), (lx + col_w - 22, y + 50)], fill=yi_color, width=2)
    yy = y + 68
    for item in left_items:
        draw.ellipse([(lx + 24, yy + 10), (lx + 34, yy + 20)], fill=yi_color)
        draw.text((lx + 44, yy), item, font=f_body, fill=_theme_color("text", INK))
        yy += line_h

    # 忌栏（深色主题随主题换成深朱底，避免浅色底配浅色字）
    draw_rounded_rect_with_shadow(img, draw, (rx, y, rx + col_w, y + box_h),
                                  DEFAULT_RADIUS, _theme_color("block_bg_danger", RED_BG))
    draw.text((rx + 22, y + 18), right_label, font=f_section, fill=ji_color)
    draw.line([(rx + 22, y + 50), (rx + col_w - 22, y + 50)], fill=ji_color, width=2)
    jy = y + 68
    for item in right_items:
        draw.ellipse([(rx + 24, jy + 10), (rx + 34, jy + 20)], fill=ji_color)
        draw.text((rx + 44, jy), item, font=f_body, fill=_theme_color("text", INK))
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
    f_small = font(17, "hei")
    f_label = font(17, "hei")
    heading = str(block.get("heading", "") or "")
    if heading:
        draw.rounded_rectangle([(margin, y + 6), (margin + 5, y + 30)], radius=2,
                               fill=_theme_color("green_accent", GREEN))
        draw.text((margin + 14, y), heading, font=font(24, "kai"), fill=_theme_color("heading", GREEN_DARK))
        y += 40
    for label, value in block.get("lines", []) or []:
        # 左侧小色块标签
        lw, lh = ts(draw, str(label), f_label)
        tag_w = lw + 16
        tag_h = lh + 10
        draw.rounded_rectangle([(margin, y), (margin + tag_w, y + tag_h)],
                               radius=6, fill=GOLD_BG)
        draw.text((margin + 8, y + 5), str(label), font=f_label, fill=GOLD_DARK)
        draw.text((margin + tag_w + 14, y + 4), str(value), font=f_small, fill=_theme_color("text_soft", INK_SOFT))
        y += 36
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
        draw.rounded_rectangle([(margin, y + 6), (margin + 5, y + 30)], radius=2,
                               fill=_theme_color("green_accent", GREEN))
        draw.text((margin + 14, y), heading, font=f_section, fill=_theme_color("heading", GREEN_DARK))
        y += 40

    for idx, (label, value) in enumerate(block.get("lines", []) or []):
        # 行号/序号小圆点（深色主题用提亮强调色，保证弱光底上可见）
        dot_color = _theme_color("gold_accent", GOLD) if idx % 2 == 0 else _theme_color("green_accent", GREEN)
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
            draw.text((text_x, y), ln, font=f_body, fill=_theme_color("text", INK))
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

    # 外圈跟随主题（深色主题用深金，避免浅金圈浮在深底上发飘）
    draw.rounded_rectangle(
        [(margin + 2, y + 2), (width - margin + 2, y + i_h + 2)],
        radius=14,
        fill=_theme_color("insight_halo", GOLD_BG),
    )
    draw_rounded_rect_with_shadow(
        img, draw,
        (margin, y, width - margin, y + i_h),
        radius=14,
        fill=_theme_color("block_bg", GREEN_BG),
        shadow_color=(0, 0, 0, 18),
        shadow_offset=2,
        shadow_blur=6,
    )
    # 左侧渐变条
    for dy in range(i_h - 8):
        ratio = dy / (i_h - 8)
        color = _interpolate_color(GOLD, GREEN_LIGHT, ratio)
        draw.line([(margin + 4, y + 4 + dy), (margin + 8, y + 4 + dy)], fill=color, width=1)
    # 引号装饰（跟随主题，深底上不再用几乎看不见的浅绿）
    draw.text((margin + 18, y + 6), "\u201c", font=font(32, "kai"),
              fill=_theme_color("quote_mark", (200, 215, 205)))
    iy = y + 24
    for ln in lines:
        draw.text((margin + 30, iy), ln, font=f_insight, fill=_theme_color("text", INK))
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
    """绘制药丸形标签网格（如时辰吉凶），返回新的 y。

    标签底色由调用方传入（固定浅绿/浅朱族），因此标签内文字一律用深色，
    不跟随主题——底是浅的，字就必须是深的，深色主题也不例外。
    """
    f_section = font(24, "kai")
    f_tag = font(16, "hei")

    if not tags:
        return y

    draw.text((margin, y), title, font=f_section, fill=_theme_color("heading", GREEN_DARK))
    y += 40

    tag_w = (width - 2 * margin - (cols - 1) * 12) // cols
    tag_h = 40
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
        draw.text((x + 10, yy + 9), label, font=f_tag, fill=GRAY)
        draw.text((x + tag_w - vw - 10, yy + 9), value_text, font=f_tag, fill=fg)
        # 中间小分隔
        draw.line([(x + tag_w // 2, yy + 9), (x + tag_w // 2, yy + tag_h - 9)], fill=(220, 220, 220), width=1)
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
    f_small = font(17, "hei")
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

    box_h = 48
    box_x = max(margin, (width - total_w) // 2 - 20)
    box_w = min(width - 2 * margin, total_w + 40)
    draw_rounded_rect_with_shadow(
        img, draw,
        (box_x, y, box_x + box_w, y + box_h),
        radius=12,
        fill=_theme_color("block_bg", GOLD_BG),
        shadow_color=(0, 0, 0, 12),
        shadow_offset=1,
        shadow_blur=4,
    )
    x = box_x + 20
    for (label, value), w in zip(lines, widths):
        text = f"{label}：{value}"
        draw.text((x, y + 13), text, font=f_small, fill=_theme_color("text_soft", INK_SOFT))
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
        cta: 底部按钮文案（仅透传记录，图片内不再绘制按钮视觉，
            真实按钮由调用方以 Telegram InlineKeyboard 附加）
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

    # 主题为可选覆盖：注入后本次绘制内的标题/区块/分隔线/CTA 配色随之变化，缺省保持墨绿米白
    theme_token = _THEME_CTX.set(THEMES.get(str(opts.get("theme", "") or "")))
    background_path = opts.get("background_path")
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

        tarot_cards = payload.get("tarot_cards")
        if tarot_cards:
            try:
                y = draw_tarot_cards(tmp, tmp_draw, tarot_cards, 0, y, width, margin)
            except Exception as exc:
                _logger.warning("skip tarot_cards(tmp): %s", exc)
                y += 160

        if payload.get("hexagram_lines"):
            try:
                y = draw_iching_hexagram(tmp, tmp_draw, payload, 0, y, width, margin)
            except Exception as exc:
                _logger.warning("skip hexagram(tmp): %s", exc)
                y += 160

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
                f_time = font(17, "hei")
                tw, _ = ts(tmp_draw, time_text, f_time)
                tmp_draw.text(((width - tw) / 2, y), time_text, font=f_time,
                              fill=_theme_color("text_soft", GRAY))
                y += 32
            except Exception as exc:
                _logger.warning("skip time_text(tmp): %s", exc)

        # 底部留白 + 印章
        cta_text = strip_visual_emoji(cta or "")
        footer_reserve = 120
        content_bottom = y + footer_reserve
        height = max(min_height, content_bottom)

        # 正式绘制（深色主题用夜色系底色，无背景素材时也能自成一体）
        bg_top = _theme_color("bg_top", BG_TOP)
        bg_bottom = _theme_color("bg_bottom", BG_BOTTOM)
        img = Image.new("RGB", (width, height), bg_top)
        draw = ImageDraw.Draw(img)
        _draw_gradient_background(img, bg_top, bg_bottom)
        # 可选外部背景图半透明叠加（缺失/损坏时静默跳过，不影响出图）
        if background_path:
            _compose_background(img, background_path, width, height)
            # 深色主题（night/evening）+ 启用背景：叠加半透明深色遮罩压暗背景，
            # 提升近白正文文字的对比度；浅色主题不叠加，保持原有明快视觉。
            if opts.get("theme") in ("night", "evening"):
                _apply_dark_overlay(img, width, height)
        else:
            # 云纹只属于素底卡：启用背景图时背景自身就是纹理，再叠纹样就是噪音
            _draw_cloud_pattern(draw, width, height)
        _draw_top_bar(draw, width)

        # 外框（深色主题随主题换成冷色细框，避免浅绿框压在夜底上突兀）
        draw.rounded_rectangle([(22, 22), (width - 22, height - 22)],
                               radius=DEFAULT_RADIUS,
                               outline=_theme_color("frame", GREEN_LINE), width=2)
        draw.rounded_rectangle([(30, 30), (width - 30, height - 30)],
                               radius=12,
                               outline=_theme_color("frame_inner", (215, 228, 220)), width=1)

        y = 70
        y = _draw_title_area(draw, payload, width, margin, y)
        y = _draw_section_divider(draw, y, width, margin)

        for block in blocks:
            y = _render_block_safe(img, draw, block, y, width, margin)

        if tarot_cards:
            try:
                y = draw_tarot_cards(img, draw, tarot_cards, 0, y, width, margin)
            except Exception as exc:
                _logger.warning("skip tarot_cards: %s", exc)
                y += 160

        if payload.get("hexagram_lines"):
            try:
                y = draw_iching_hexagram(img, draw, payload, 0, y, width, margin)
            except Exception as exc:
                _logger.warning("skip hexagram: %s", exc)
                y += 160

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
                f_time = font(17, "hei")
                tw, _ = ts(draw, time_text, f_time)
                draw.text(((width - tw) / 2, y), time_text, font=f_time,
                          fill=_theme_color("text_soft", GRAY))
                y += 32
            except Exception as exc:
                _logger.warning("skip time_text: %s", exc)

        # 底部分隔线（深色主题随主题提亮，避免隐入夜底）
        draw.line([(margin, height - 130), (width - margin, height - 130)],
                  fill=_theme_color("divider_soft", GREEN_LINE), width=1)

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
        _THEME_CTX.reset(theme_token)
        if tmp is not None:
            tmp.close()
        if img is not None:
            img.close()


def build_broadcast_image_card(
    payload: dict,
    cache_key: str,
    config: dict = None,
    min_height: int = 1000,
    cta_text: str = "",
    options: dict = None,
) -> str | None:
    """通用图片卡生成入口，返回本地 PNG 路径；失败返回 None。

    cache_key 用于构造文件名，建议包含类型与日期，避免冲突。
    cta_text 由调用方传入（与真实按钮一致）；为空时图片卡不绘制按钮，避免无入口场景出现假按钮。
    options 透传给 draw_card（如 resolve_theme_options 返回的 theme / background_path）。

    缓存策略：cache_key 含日期时同日幂等。文件已存在且 mtime 距今 <24h 时
    直接复用（省去重复绘制）；否则重新绘制，先写 .tmp 再 os.replace 原子替换，
    避免并发绘制时读到半张图。
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

        # 缓存命中短路：cache_key 含日期时同日幂等，文件存在且 mtime 距今 <24h 直接复用
        if os.path.isfile(out_path):
            try:
                if time.time() - os.path.getmtime(out_path) < 24 * 3600:
                    return out_path
            except OSError:
                pass  # 拿不到 mtime 时按未命中处理，走重新生成

        # 先写 .tmp 再原子替换，避免并发绘制时读到半张图（draw_card 内部逻辑不动）
        tmp_path = out_path + ".tmp"
        _, info = draw_card(
            payload, out=tmp_path, cta=final_cta, min_height=min_height, options=options or {},
        )
        os.replace(tmp_path, out_path)
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


# ── 时段主题系统（可选覆盖，缺省保持墨绿米白配色） ──
# draw_card(options={"theme": "morning"|"afternoon"|"evening"|"night"}) 时
# 覆盖标题色/区块底色/分隔线色/CTA 按钮渐变色；不传 theme 时全部回落到上方常量配色。
# 色板约定（见 docs/technical/broadcast-card-design-philosophy.md）：
# - 浅色主题：纸底 + 墨字，区块浅底；
# - 深色主题（evening/night）：夜色底 + 深色区块 + 近白字，
#   绝不允许浅底配浅字；强调色（green/red/gold accent）保持色相、明度上抬。
THEMES = {
    "morning": {
        "label": "暖金晨光",
        "title": (168, 116, 50),
        "block_bg": (250, 242, 226),
        "divider": (216, 178, 108),
        "cta_top": (222, 184, 120),
        "cta_bottom": (158, 116, 62),
        "text": INK,
        "text_soft": INK_SOFT,
        "tag_text": (110, 98, 78),
        "divider_soft": (232, 218, 192),
    },
    "afternoon": {
        "label": "青绿生息",
        "title": (38, 110, 92),
        "block_bg": (228, 242, 234),
        "divider": (150, 190, 165),
        "cta_top": (92, 160, 136),
        "cta_bottom": (38, 92, 74),
        "text": INK,
        "text_soft": INK_SOFT,
        "tag_text": (72, 110, 98),
        "divider_soft": (206, 224, 212),
    },
    "evening": {
        "label": "靛蓝暮色",
        # 夜色底 + 深色区块 + 近白字：标题与正文都亮起来，区块沉下去
        "bg_top": (44, 52, 88),
        "bg_bottom": (30, 36, 64),
        "title": (242, 238, 226),
        "heading": (226, 228, 240),
        "block_bg": (36, 44, 74),
        "block_bg_danger": (66, 40, 46),
        "divider": (150, 160, 205),
        "divider_soft": (96, 106, 148),
        "cta_top": (110, 122, 190),
        "cta_bottom": (48, 56, 108),
        "text": (240, 240, 234),
        "text_soft": (208, 210, 220),
        "tag_text": (186, 190, 216),
        "gold_accent": (224, 192, 132),
        "green_accent": (142, 192, 166),
        "red_accent": (226, 132, 120),
        "insight_halo": (108, 94, 60),
        "quote_mark": (108, 122, 162),
        "frame": (120, 132, 172),
        "frame_inner": (86, 96, 132),
    },
    "night": {
        "label": "深空蓝",
        "bg_top": (26, 32, 56),
        "bg_bottom": (14, 18, 36),
        "title": (240, 238, 228),
        "heading": (222, 226, 240),
        "block_bg": (26, 33, 56),
        "block_bg_danger": (58, 36, 42),
        "divider": (140, 160, 215),
        "divider_soft": (80, 92, 130),
        "cta_top": (80, 105, 175),
        "cta_bottom": (28, 44, 96),
        "text": (238, 238, 232),
        "text_soft": (202, 204, 214),
        "tag_text": (178, 186, 212),
        "gold_accent": (220, 188, 128),
        "green_accent": (134, 186, 160),
        "red_accent": (224, 128, 116),
        "insight_halo": (100, 88, 56),
        "quote_mark": (96, 112, 152),
        "frame": (104, 118, 158),
        "frame_inner": (72, 84, 120),
    },
}

# 当前绘制上下文内生效的主题（contextvar 隔离并发调用，避免互相串色）
_THEME_CTX: contextvars.ContextVar = contextvars.ContextVar("broadcast_theme", default=None)


def _theme_color(key: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """取当前主题配色键；未启用主题时返回默认色，保持现有墨绿米白视觉。"""
    theme = _THEME_CTX.get()
    if theme and key in theme:
        return theme[key]
    return default


def _compose_background(
    img: Image.Image,
    path: str,
    width: int,
    height: int,
    opacity: float = 0.65,
) -> None:
    """把外部背景图缩放到卡片尺寸、半透明叠加到渐变背景之上。

    背景图缺失/损坏/格式异常一律 logger.warning 后跳过，绝不影响出图。
    不做自动素材加载：只有 draw_card(options={"background_path": ...}) 显式传入才生效。
    """
    bg: Optional[Image.Image] = None
    try:
        if not path:
            return
        if not os.path.isfile(path):
            _logger.warning("背景图不存在，已跳过: %s", path)
            return
        bg = Image.open(path)
        bg = bg.convert("RGBA").resize((width, height), Image.LANCZOS)
        alpha = bg.getchannel("A").point(lambda a: int(a * opacity))
        bg.putalpha(alpha)
        img.paste(bg, (0, 0), bg)
    except Exception as exc:
        _logger.warning("背景图合成失败，已跳过: %s", exc)
    finally:
        if bg is not None:
            bg.close()


def _apply_dark_overlay(
    img: Image.Image,
    width: int,
    height: int,
    color: Tuple[int, int, int] = (10, 10, 15),
    alpha: int = 85,
) -> None:
    """深色主题下对整幅画面叠加一层半透明深色遮罩，压暗背景、提升浅色文字对比度。

    仅在 night/evening 且启用了背景图时由 draw_card 调用；浅色主题不叠加。
    """
    overlay = Image.new("RGBA", (width, height), color + (alpha,))
    try:
        img.paste(overlay, (0, 0), overlay)
    finally:
        overlay.close()


def draw_tarot_cards(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    cards: List[Tuple[str, str, str, str]],
    x: int,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制竖版塔罗牌面卡组，返回新的 y。

    cards 每项为 (role, 牌名, 正逆位, 关键词)，最多绘制 4 张；
    墨绿/金色系 + 投影，正逆位用红/金区分。
    """
    cards = [c for c in (cards or []) if c and c[1]][:4]
    if not cards:
        return y

    f_role = font(16, "hei")
    f_name = font(26, "kai")
    f_pos = font(16, "hei")
    f_key = font(16, "hei")

    n = len(cards)
    gap = 14
    card_w = (width - 2 * margin - (n - 1) * gap) // n
    card_h = 248
    box_y = y + 4

    for i, (role, name, position, keywords) in enumerate(cards):
        cx = margin + i * (card_w + gap)
        # 牌面：投影 + 圆角矩形 + 金色描边
        draw_rounded_rect_with_shadow(
            img, draw,
            (cx, box_y, cx + card_w, box_y + card_h),
            radius=DEFAULT_RADIUS,
            fill=_theme_color("block_bg", GREEN_BG),
            shadow_color=(0, 0, 0, 30),
            shadow_offset=3,
            shadow_blur=7,
        )
        draw.rounded_rectangle(
            [(cx + 6, box_y + 6), (cx + card_w - 6, box_y + card_h - 6)],
            radius=DEFAULT_RADIUS - 4,
            fill=None,
            outline=_theme_color("gold_accent", GOLD),
            width=1,
        )
        # 顶部 role 标签
        if role:
            rw, rh = ts(draw, str(role), f_role)
            tag_w = rw + 20
            tag_h = rh + 10
            tag_x = cx + (card_w - tag_w) // 2
            draw.rounded_rectangle(
                [(tag_x, box_y + 16), (tag_x + tag_w, box_y + 16 + tag_h)],
                radius=9,
                fill=GOLD_BG,
            )
            draw.text((tag_x + 10, box_y + 21), str(role), font=f_role, fill=GOLD_DARK)
        # 牌名
        name = str(name)
        nw, nh = ts(draw, name, f_name)
        draw.text(
            (cx + (card_w - nw) // 2, box_y + 54),
            name, font=f_name,
            fill=_theme_color("title", GREEN_DARK),
        )
        # 正逆位（逆位用提亮朱砂，深色牌面上依旧醒目）
        pos_text = str(position or "")
        if pos_text:
            pw, _ = ts(draw, pos_text, f_pos)
            pos_color = _theme_color("red_accent", RED) if "逆" in pos_text else _theme_color("gold_accent", GOLD_DARK)
            draw.text((cx + (card_w - pw) // 2, box_y + 96), pos_text, font=f_pos, fill=pos_color)
        # 分隔细线
        line_y = box_y + 128
        draw.line([(cx + 14, line_y), (cx + card_w - 14, line_y)],
                  fill=_theme_color("divider_soft", GREEN_LINE), width=1)
        # 关键词（换行居中）
        kw_text = str(keywords or "")
        max_w = card_w - 24
        key_lines = wrap_text(draw, kw_text, f_key, max_w)
        ky = line_y + 12
        for ln in key_lines[:4]:
            lw, _ = ts(draw, ln, f_key)
            draw.text((cx + (card_w - lw) // 2, ky), ln, font=f_key,
                      fill=_theme_color("text_soft", INK_SOFT))
            ky += 24

    return box_y + card_h + 26


def draw_iching_hexagram(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    payload: dict,
    x: int,
    y: int,
    width: int,
    margin: int,
) -> int:
    """绘制易经六爻示意装饰图，返回新的 y。

    payload.hexagram_lines：6 个 1/0，自下而上（1=初爻）；阳爻实线、阴爻两段虚线。
    payload.moving_line：1-6 动爻序号，动爻金色加粗并标注。
    爻线为稳定 seed 生成的装饰性视觉，不要求与真实卦象一致。
    """
    lines = payload.get("hexagram_lines") or []
    if not lines:
        return y
    moving = int(payload.get("moving_line") or 0)

    f_head = font(24, "kai")
    f_mark = font(18, "kai")

    box_x, box_y = margin, y + 4
    box_w = width - 2 * margin
    line_len = min(box_w - 210, 320)
    row_h = 34
    pad_top = 48
    box_h = pad_top + 6 * row_h + 26

    draw_rounded_rect_with_shadow(
        img, draw,
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=DEFAULT_RADIUS,
        fill=_theme_color("block_bg", GREEN_BG),
        shadow_color=(0, 0, 0, 20),
        shadow_offset=2,
        shadow_blur=6,
    )
    draw.text((box_x + 16, box_y + 8), "六爻示意", font=f_head,
              fill=_theme_color("title", GREEN_DARK))

    center_x = width // 2
    for i in range(6):
        if i >= len(lines):
            break
        row = 5 - i
        yy = box_y + pad_top + row * row_h + row_h // 2
        is_moving = moving == i + 1
        color = _theme_color("gold_accent", GOLD_DARK) if is_moving else _theme_color("green_accent", GREEN)
        thick = 16 if is_moving else 12
        half = line_len // 2
        if int(lines[i]) == 1:
            draw.rounded_rectangle(
                [(center_x - half, yy - thick // 2), (center_x + half, yy + thick // 2)],
                radius=thick // 2,
                fill=color,
            )
        else:
            seg = int(half * 0.4)
            draw.rounded_rectangle(
                [(center_x - half, yy - thick // 2), (center_x - half + seg, yy + thick // 2)],
                radius=thick // 2,
                fill=color,
            )
            draw.rounded_rectangle(
                [(center_x + half - seg, yy - thick // 2), (center_x + half, yy + thick // 2)],
                radius=thick // 2,
                fill=color,
            )
        if is_moving:
            draw.text((center_x + half + 14, yy - 15), "动", font=f_mark,
                      fill=_theme_color("gold_accent", GOLD_DARK))

    return box_y + box_h + 26


# ── 视觉主题接线（v5.38.26）──────────────────────────────────────────────────
# 生产调用方（问候/玄学/定点播报）通过 resolve_theme_options 拿到主题 options：
# - BROADCAST_THEME_ENABLED=true 时启用时段主题色；
# - assets/broadcast/bg_{period}.png 素材存在时附带背景合成路径（素材缺失静默跳过）。
_BROADCAST_ASSET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "broadcast",
)


def resolve_theme_options(config: dict = None, period: str = "") -> dict:
    """按配置与时段返回图片卡主题 options（theme 色 + 可选背景素材）。

    返回空 dict 时绘制层保持默认墨绿米白；素材文件不存在时只启用主题色、不挂背景。
    """
    cfg = config or {}
    if not bool(cfg.get("BROADCAST_THEME_ENABLED", True)):
        return {}
    period = str(period or "").lower()
    if period not in THEMES:
        return {}
    opts = {"theme": period}
    for ext in (".png", ".jpg", ".jpeg"):
        bg = os.path.join(_BROADCAST_ASSET_DIR, f"bg_{period}{ext}")
        if os.path.isfile(bg):
            opts["background_path"] = bg
            break
    return opts
