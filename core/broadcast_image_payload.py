# -*- coding: utf-8 -*-
"""播报图片卡 payload 适配器。

把各业务模块产生的原始数据（黄历、塔罗、易经、新闻、问候、定点播报）
转成 core.broadcast_image_card.draw_card 可消费的标准化 payload。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

from core.broadcast_image_card import GOLD_BG, GREEN, GREEN_BG, RED, RED_BG


def _extract_lunar_date(meta: str) -> str:
    """从 meta 字符串中提取农历日期作为右上角展示。"""
    if not meta:
        return ""
    parts = [p.strip() for p in meta.split("｜")]
    for part in parts:
        if "农历" in part:
            return part.replace("农历", "").strip()
    return ""


def _strip_emoji_prefix(text: str) -> str:
    """去掉 heading 前面的 emoji，避免标题区重复。"""
    return re.sub(r"^[📌🧭🌿🎴✨☯️🪶]+\s*", "", str(text or "")).strip()


def _normalize_mystic_blocks(
    raw_blocks: List[dict],
    style_detector: Callable[[str, List[Tuple[str, str]]], str],
) -> List[dict]:
    """统一处理 mystic blocks：去 emoji 前缀 + 调用方自定义 style 判断。

    黄历 / 塔罗 / 易经三个 build_* 函数结构高度一致，统一走这个 helper 避免三处重复。
    """
    result: List[dict] = []
    for block in raw_blocks or []:
        heading = _strip_emoji_prefix(block.get("heading", ""))
        lines = block.get("lines", []) or []
        style = style_detector(heading, lines)
        result.append({"heading": heading, "lines": lines, "style": style})
    return result


def _build_base_mystic_payload(
    mystic_payload: dict,
    default_title: str,
    blocks: List[dict],
    extra: dict = None,
) -> dict:
    """构造 mystic 基础 payload（title/kicker/meta/insight/blocks），再叠加 extra。"""
    payload: dict = {
        "title": mystic_payload.get("title", default_title),
        "kicker": mystic_payload.get("kicker", ""),
        "meta": mystic_payload.get("meta", ""),
        "blocks": blocks,
        "insight": mystic_payload.get("insight", ""),
    }
    if extra:
        payload.update(extra)
    return payload


def _almanac_style_detector(heading: str, lines: List[Tuple[str, str]]) -> str:
    """黄历 block 的 style 判断：宜忌用双栏，冲煞/值日等用 key_value，其余列表。"""
    if "宜" in heading or "忌" in heading:
        return "two_column"
    if any(str(label) in ("冲煞", "值日", "星宿", "吉神方位",
                          "节气", "彭祖百忌") for label, _ in lines):
        return "key_value"
    return "list"


def build_almanac_image_payload(mystic_payload: dict) -> dict:
    """把黄历 mystic payload 转成图片卡 payload。"""
    raw_blocks = mystic_payload.get("blocks", []) or []
    blocks = _normalize_mystic_blocks(raw_blocks, _almanac_style_detector)

    extra = {
        "date_text": _extract_lunar_date(mystic_payload.get("meta", "")),
    }
    payload = _build_base_mystic_payload(
        mystic_payload, "早间 · 今日黄历", blocks, extra
    )

    # 时辰吉凶标签
    hours = mystic_payload.get("hours")
    if hours:
        tags = []
        for name, _hour, luck in hours:
            color = GREEN if luck == "吉" else RED
            bg = GREEN_BG if luck == "吉" else RED_BG
            tags.append((name, luck, color, bg))
        payload["tags"] = tags
        payload["tags_title"] = "今日时辰吉凶"

    # 财神 / 喜神方位
    wealth = mystic_payload.get("wealth_direction", "")
    joy = mystic_payload.get("joy_direction", "")
    if wealth or joy:
        payload["footer_lines"] = []
        if wealth:
            payload["footer_lines"].append(("财神方位", wealth))
        if joy:
            payload["footer_lines"].append(("喜神方位", joy))

    return payload


def build_tarot_image_payload(mystic_payload: dict) -> dict:
    """把塔罗 mystic payload 转成图片卡 payload。"""
    raw_blocks = mystic_payload.get("blocks", []) or []
    blocks = _normalize_mystic_blocks(
        raw_blocks,
        lambda heading, _lines: "key_value" if "能量" in heading else "list",
    )
    return _build_base_mystic_payload(mystic_payload, "午间 · 三张塔罗", blocks)


def build_iching_image_payload(mystic_payload: dict) -> dict:
    """把易经 mystic payload 转成图片卡 payload。"""
    raw_blocks = mystic_payload.get("blocks", []) or []
    blocks = _normalize_mystic_blocks(
        raw_blocks,
        lambda heading, _lines: "key_value" if "卦意" in heading else "list",
    )
    return _build_base_mystic_payload(mystic_payload, "晚间 · 易经一卦", blocks)


def build_mystic_image_payload(mystic_payload: dict) -> dict:
    """根据 mode 自动分发到对应适配器。"""
    mode = mystic_payload.get("mode", "almanac")
    if mode == "almanac":
        return build_almanac_image_payload(mystic_payload)
    if mode == "tarot":
        return build_tarot_image_payload(mystic_payload)
    if mode == "iching":
        return build_iching_image_payload(mystic_payload)
    return build_almanac_image_payload(mystic_payload)


def build_news_image_payload(news_content: str, time_desc: str = "午间") -> dict:
    """把新闻文本转成图片卡 payload。

    news_content 预期是编号列表或标题列表。
    """
    from core.broadcast_formatter import _parse_news_copy

    news_items, observations = _parse_news_copy(news_content, max_items=5)

    lines = []
    for i, item in enumerate(news_items, 1):
        lines.append((f"{i}.", item))

    blocks = []
    if lines:
        blocks.append({
            "heading": f"{time_desc}速览",
            "lines": lines,
            "style": "list",
        })

    insight = ""
    if observations:
        # 去掉 insight 前的 emoji，避免 PIL 渲染为 tofu
        insight = re.sub(r"^[💡✨🌟⭐🔥\s]+", "", " ".join(observations)).strip()

    return {
        "title": f"{time_desc}新闻",
        "kicker": "热点速览",
        "meta": "",
        "blocks": blocks,
        "insight": insight,
    }


def build_greeting_image_payload(period: str, body: str, badge: str = "") -> dict:
    """把问候语转成图片卡 payload。"""
    period_labels = {
        "morning": ("早安", "新的一天"),
        "afternoon": ("午安", "歇一分钟"),
        "evening": ("晚安", "今天先到这"),
        "night": ("晚安", "留一句话"),
    }
    title, default_badge = period_labels.get(period, ("问候", ""))

    return {
        "title": title,
        "kicker": badge or default_badge,
        "meta": "",
        "blocks": [],
        "insight": body,
    }


def build_scheduled_image_payload(item: dict, user_profile: dict = None) -> dict:
    """把定点播报配置项转成图片卡 payload。"""
    title = str(item.get("title", "") or "").strip() or "群播报"
    body = str(item.get("content", "") or "").strip()
    badge = str(item.get("badge", "") or "").strip()
    footer = str(item.get("footer", "") or "").strip()
    period = str(item.get("period", "") or "").strip()

    # 图片卡标题去掉 emoji，避免 PIL 渲染为 tofu
    display_title = title.lstrip("☀️🍵🌆🌙📢 ").strip()

    # 正文与 footer 统一放进 insight 语录卡片，避免“补充”小标题喧宾夺主
    insight_parts = [body]
    if footer:
        insight_parts.append(footer)
    insight = "\n\n".join(p for p in insight_parts if p)

    payload = {
        "title": display_title,
        "kicker": badge,
        "meta": "",
        "blocks": [],
        "insight": insight,
    }

    # 用户画像微调节点
    if user_profile:
        tags = user_profile.get("tags", [])
        level = user_profile.get("level", 0)
        if "vip" in tags or level >= 5:
            payload["title"] = f"精选 · {display_title}"

    return payload
