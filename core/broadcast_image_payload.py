# -*- coding: utf-8 -*-
"""播报图片卡 payload 适配器。

把各业务模块产生的原始数据（黄历、塔罗、易经、新闻、问候、定点播报）
转成 core.broadcast_image_card.draw_card 可消费的标准化 payload。
"""

from __future__ import annotations

import random
import re
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def _append_disclaimer_footer(payload: dict, mystic_payload: dict) -> None:
    """免责尾注并入图片卡 footer_lines（不新增 block，不影响区块结构）。"""
    note = str(mystic_payload.get("note", "") or "")
    if not note:
        return
    footer = list(payload.get("footer_lines") or [])
    footer.append(("说明", note))
    payload["footer_lines"] = footer


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
    _append_disclaimer_footer(payload, mystic_payload)

    return payload


_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)


def _parse_tarot_card_line(value: str) -> Tuple[str, str, str]:
    """解析塔罗牌行值 "XIII · 死神 · 正位｜启程 / 自由" → (牌名, 正逆位, 关键词)。

    阿拉伯序号与罗马数字都是装饰性编号，不参与牌名；
    容错纯牌名行（如 ("过去", "愚者")）：只取牌名，正逆位/关键词留空。
    """
    value = str(value or "")
    head, _, tail = value.partition("｜")
    parts = [p.strip() for p in head.split("·") if p.strip()]
    name, position = "", ""
    for p in parts:
        if p.isdigit() or _ROMAN_RE.match(p):
            continue
        if p in ("正位", "逆位"):
            position = p
        elif not name:
            name = p
        elif not position:
            position = p
    keywords = tail.strip().replace("/", " / ")
    return name, position, keywords


def build_tarot_image_payload(mystic_payload: dict) -> dict:
    """把塔罗 mystic payload 转成图片卡 payload。"""
    # 先归一化（去 heading emoji 前缀），牌面卡解析也基于归一后的 blocks，
    # 避免 "🎴 主牌" 里的 emoji 混进牌名，导致牌面印出 "XIII" 这类半截名字
    raw_blocks = _normalize_mystic_blocks(
        mystic_payload.get("blocks", []) or [],
        lambda heading, _lines: "key_value" if "能量" in heading else "list",
    )
    blocks = raw_blocks
    extra: Dict[str, Any] = {}
    # 从第一个区块的牌阵行解析牌面卡 (role, 牌名, 正逆位, 关键词)，最多 4 张
    first_lines = (raw_blocks[0].get("lines") or []) if raw_blocks else []
    tarot_cards: List[Tuple[str, str, str, str]] = []
    for role, value in first_lines[:4]:
        name, position, keywords = _parse_tarot_card_line(str(value))
        if name:
            tarot_cards.append((str(role), name, position, keywords))
    if tarot_cards:
        extra["tarot_cards"] = tarot_cards
    payload = _build_base_mystic_payload(mystic_payload, "午间 · 三张塔罗", blocks, extra)
    _append_disclaimer_footer(payload, mystic_payload)
    return payload


def _extract_moving_line(raw_blocks: List[dict]) -> Optional[int]:
    """从易经 blocks 中解析动爻序号（"九三 · 第3爻变" → 3），无动爻返回 None。"""
    for block in raw_blocks or []:
        for label, value in block.get("lines", []) or []:
            m = re.search(r"第\s*([1-6])\s*爻", f"{label}{value}")
            if m:
                return int(m.group(1))
    return None


def build_iching_image_payload(mystic_payload: dict) -> dict:
    """把易经 mystic payload 转成图片卡 payload。"""
    raw_blocks = mystic_payload.get("blocks", []) or []
    blocks = _normalize_mystic_blocks(
        raw_blocks,
        lambda heading, _lines: "key_value" if "卦意" in heading else "list",
    )
    extra: Dict[str, Any] = {}
    # 六爻装饰图：mystic 层没有原始爻线，用稳定 seed（标题+meta）生成装饰性爻线，
    # 保证同日内多次生成一致；不要求与真实卦象一致，由 draw 层按 moving_line 标注动爻。
    moving_line = _extract_moving_line(raw_blocks)
    if moving_line is not None:
        seed_src = f"{mystic_payload.get('title', '')}|{mystic_payload.get('meta', '')}"
        rng = random.Random(zlib.crc32(seed_src.encode("utf-8")))
        extra["hexagram_lines"] = [rng.randint(0, 1) for _ in range(6)]
        extra["moving_line"] = moving_line
    payload = _build_base_mystic_payload(mystic_payload, "晚间 · 易经一卦", blocks, extra)
    _append_disclaimer_footer(payload, mystic_payload)
    return payload


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


_CST = timezone(timedelta(hours=8))


def _beijing_now() -> datetime:
    """北京时间当前时刻。"""
    return datetime.now(_CST)


def build_greeting_image_payload(period: str, body: str, badge: str = "", seed: str = "") -> dict:
    """把问候语转成图片卡 payload。

    问候卡只展示本轮通过质量门禁的唯一正文，不再把独立随机的“今日一句”与
    “一言”硬拼进同一张卡。seed 参数仅为兼容既有调用方保留。
    """
    # 傍晚档不叫晚安（那会提前透支深夜的问候）：用"暮安"与早安/午安同一造词法，
    # 晚安留给 night 档；徽标也随语境改成傍晚收工的调子
    period_labels = {
        "morning": ("早安", "新的一天"),
        "afternoon": ("午安", "歇一分钟"),
        "evening": ("暮安", "今天慢慢收尾"),
        "night": ("晚安", "留一句话"),
    }
    title, default_badge = period_labels.get(period, ("问候", ""))

    # 北京时间当日 "X月X日 周X"，真实日期不虚构
    now = _beijing_now()
    weekday = "一二三四五六日"[now.weekday()]
    date_text = f"{now.month}月{now.day}日 周{weekday}"

    return {
        "title": title,
        "kicker": badge or default_badge,
        "meta": "",
        "date_text": date_text,
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
