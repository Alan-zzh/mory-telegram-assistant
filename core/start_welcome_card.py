# -*- coding: utf-8 -*-
"""私聊 ``/start`` 与群聊首次 ``@小助理`` 共用的欢迎图片卡。

这条入口不调用大模型，避免把明确的业务接待开场随机生成成“陪聊机器人”。
随机性只用于轮换已审核的横版底图和等义文案；姓名与日期在发送前本地绘制。
"""

from __future__ import annotations

import io
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from core.broadcast_cta import build_cta_markup_combo
from core.broadcast_image_card import font


_CST = timezone(timedelta(hours=8))
_ROOT = Path(__file__).resolve().parents[1]
_ASSET_DIR = _ROOT / "assets" / "start_welcome"
_ASSET_PATTERN = "mory_start_v3_*.jpg"
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")

_WELCOME_COPY = (
    "你好，{name}。我是 Mory 的小助理。\n"
    "要处理的事情、问题或咨询，直接发给我就行，不用先寒暄。\n"
    "能处理的我马上处理；需要 Mory 确认的，我会尝试转达，并明确告诉你是否送达。",
    "欢迎你，{name}。这里是 Mory 的小助理。\n"
    "有什么事情要处理、有什么想咨询的，直接发来就好。\n"
    "我会先帮你解决；超出范围的会尝试转达给 Mory，并把送达结果告诉你。",
    "{name}，你好。我是 Mory 的小助理。\n"
    "不用想开场白，把需要处理的事或问题直接发给我。\n"
    "我能解决的马上处理；必须由 Mory 确认的，我会尝试转达，并如实说明是否送达。",
    "你好，{name}，欢迎来到 Mory 小助理。\n"
    "办事、咨询、遇到问题，都可以直接把情况发给我。\n"
    "我会先处理；确实需要 Mory 的，会尝试转达，并当场告诉你有没有送达。",
)

_BUTTON_LABEL_PAIRS = (
    ("👀 免费预览", "🛒 自助订阅"),
    ("👀 先看预览", "🛒 查看订阅"),
    ("🎁 看免费内容", "💎 订阅选项"),
    ("✨ 免费看看", "🔓 自助开通"),
)


@dataclass(frozen=True)
class StartWelcomeCard:
    """已渲染的欢迎卡及可测试元数据。"""

    stream: io.BytesIO
    asset_name: str
    display_name: str
    date_text: str


@dataclass(frozen=True)
class StartWelcomeDelivery:
    """同源欢迎卡发送结果，用于私聊与群首次 @ 的统一验收。"""

    delivered: bool
    asset_name: str
    display_name: str
    caption: str
    degraded_to_text: bool = False


def normalize_display_name(value: object) -> str:
    """清理 Telegram 显示名，避免控制字符破坏图片与消息布局。"""
    cleaned = _CONTROL_RE.sub(" ", str(value or "")).strip()
    cleaned = " ".join(cleaned.split())
    return (cleaned or "朋友")[:18]


def build_start_welcome_caption(display_name: object, *, rng=None) -> str:
    """从等义业务接待文案池中随机选择一条，绝不生成陪聊式问题。"""
    chooser = rng or random.SystemRandom()
    name = normalize_display_name(display_name)
    return chooser.choice(_WELCOME_COPY).format(name=name)


def build_start_welcome_markup(config: Optional[dict] = None, *, rng=None):
    """随机轮换双入口显示文案；预览/订阅语义与链接始终固定。"""
    chooser = rng or random.SystemRandom()
    preview_label, subscribe_label = chooser.choice(_BUTTON_LABEL_PAIRS)
    combo = {
        "buttons": [
            {
                "target": "preview",
                "label": preview_label,
                "url": "https://t.me/moryselect",
                "style": "primary",
            },
            {
                "target": "subscribe",
                "label": subscribe_label,
                "url": "https://t.me/MorychannelBot",
                "style": "success",
            },
        ]
    }
    return build_cta_markup_combo(combo, config=config or {})


def _fit_font(draw: ImageDraw.ImageDraw, text: str, *, max_width: int, start: int, minimum: int):
    """把长昵称压到左侧姓名区内，不截断卡片布局。"""
    for size in range(start, minimum - 1, -2):
        candidate = font(size, "bold")
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if bbox[2] - bbox[0] <= max_width:
            return candidate
    return font(minimum, "bold")


def build_start_welcome_card(
    display_name: object,
    *,
    now: Optional[datetime] = None,
    rng=None,
) -> StartWelcomeCard:
    """随机选择一张底图，并绘制姓名、当天日期与 Mory 品牌信息。"""
    chooser = rng or random.SystemRandom()
    assets = sorted(_ASSET_DIR.glob(_ASSET_PATTERN))
    if not assets:
        raise FileNotFoundError(f"欢迎卡底图不存在: {_ASSET_DIR / _ASSET_PATTERN}")

    selected = chooser.choice(assets)
    name = normalize_display_name(display_name)
    local_now = (now or datetime.now(_CST)).astimezone(_CST)
    date_text = f"{local_now.year}年{local_now.month}月{local_now.day}日"

    with Image.open(selected) as source:
        canvas = source.convert("RGBA").resize((960, 480), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer = ImageDraw.Draw(overlay)
    # 只铺柔和的左侧阅读光，不再画独立白卡或人物相框；让背景、人物和文字
    # 保持在同一张画面的景深与光影里。
    for x in range(0, 590):
        ratio = x / 590
        alpha = int(118 * (1 - ratio) ** 1.7)
        layer.line((x, 0, x, 480), fill=(255, 250, 247, alpha))
    layer.rounded_rectangle((54, 54, 61, 423), radius=4, fill=(193, 106, 121, 210))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    rose = (162, 76, 94, 255)
    ink = (58, 48, 51, 255)
    soft = (111, 86, 91, 255)
    pale = (238, 220, 219, 255)

    draw.text((88, 54), "Mory", font=font(66, "kai"), fill=rose)
    draw.text((91, 126), "PERSONAL ASSISTANT", font=font(16, "hei"), fill=soft)
    draw.line((90, 167, 440, 167), fill=pale, width=2)

    draw.text((90, 194), "你好，今天由我协助你", font=font(24, "hei"), fill=soft)
    name_font = _fit_font(draw, name, max_width=360, start=50, minimum=30)
    draw.text((88, 233), name, font=name_font, fill=ink)

    date_font = font(20, "hei")
    date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
    date_width = date_bbox[2] - date_bbox[0]
    draw.rounded_rectangle((89, 318, 119 + date_width, 359), radius=20, fill=(244, 226, 226, 224))
    draw.text((104, 327), date_text, font=date_font, fill=rose)
    draw.text((90, 387), "处理事情   /   解答咨询   /   转达 Mory", font=font(18, "hei"), fill=soft)

    stream = io.BytesIO()
    canvas.convert("RGB").save(stream, format="JPEG", quality=89, optimize=True, progressive=True)
    stream.seek(0)
    stream.name = "mory-start-welcome.jpg"
    return StartWelcomeCard(
        stream=stream,
        asset_name=selected.name,
        display_name=name,
        date_text=date_text,
    )


def send_start_welcome(
    bot,
    message,
    config: Optional[dict] = None,
    *,
    mory_bot=None,
    rng=None,
) -> StartWelcomeDelivery:
    """发送私聊/群聊完全同款欢迎卡，运行时只读本地模板并用 Pillow 合成。

    ``mory_bot`` 仅在群聊传入，用于把图片或降级文本写入既有清理追踪链。
    本函数不接收 AI 实例，也没有任何模型调用路径。
    """
    user = getattr(message, "from_user", None)
    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    display_name = normalize_display_name(f"{first_name} {last_name}")
    caption = build_start_welcome_caption(display_name, rng=rng)
    markup = build_start_welcome_markup(config or {}, rng=rng)
    is_group = getattr(getattr(message, "chat", None), "type", "") in {
        "group",
        "supergroup",
    }
    card = None
    try:
        card = build_start_welcome_card(display_name, rng=rng)
        if is_group:
            if mory_bot is None:
                raise RuntimeError("群聊欢迎卡缺少 MoryBot 追踪器")
            sent = mory_bot.reply_photo_and_track(
                message,
                card.stream,
                caption=caption,
                reply_markup=markup,
            )
        else:
            from core.telebot_compat import send_photo_compat

            sent = send_photo_compat(
                bot,
                message.chat.id,
                card.stream,
                caption=caption,
                reply_markup=markup,
            )
        if is_group and not sent:
            raise RuntimeError("Telegram 未返回群聊图片消息回执")
        return StartWelcomeDelivery(
            delivered=True,
            asset_name=card.asset_name,
            display_name=display_name,
            caption=caption,
        )
    except Exception:
        if is_group:
            sent = mory_bot.reply_and_track(message, caption, reply_markup=markup)
            if not sent:
                raise RuntimeError("群聊欢迎卡图片和文本降级均未送达")
        else:
            sent = bot.send_message(message.chat.id, caption, reply_markup=markup)
        return StartWelcomeDelivery(
            delivered=True,
            asset_name=card.asset_name if card else "",
            display_name=display_name,
            caption=caption,
            degraded_to_text=True,
        )
    finally:
        if card is not None:
            card.stream.close()


__all__ = [
    "StartWelcomeCard",
    "StartWelcomeDelivery",
    "build_start_welcome_caption",
    "build_start_welcome_card",
    "build_start_welcome_markup",
    "normalize_display_name",
    "send_start_welcome",
]
