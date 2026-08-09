# -*- coding: utf-8 -*-
"""特定词自动回复卡片组件。

把自动回复的 Rich/HTML 排版、随机入口按钮（联系 Mory @Moryfansbot /
自助下单 @MorychannelBot / 预览 @moryselect）与文案池收敛到一个模块，
供 modules/keyword_trigger.py 在 AUTO_REPLY_CARD_ENABLED=true 时使用。

红线对齐（AGENTS.md）：
- 群聊每轮至多一个与正文一致入口 → 单按钮，不组合
- 私聊不挂销售按钮 → chat_id>0 时 markup 恒为 None（正文保留润色文本）
- 规则显式声明 conversion_target 时目标绑定（了解→预览、明确购买→自助）；
  未声明时在「联系 / 自助下单」间二选一随机，命中即锁定
- 规则可配 "button_enabled": false 显式关闭按钮
"""

from __future__ import annotations

import random
from typing import Any, Dict, Optional

from core.broadcast_cta import (
    TARGET_CONTACT,
    TARGET_PREVIEW,
    TARGET_SUBSCRIBE,
    _DEFAULT_URLS,
    build_cta_markup,
)
from core.broadcast_formatter import (
    build_card_html,
    build_rich_card_message,
)


# ── 自动回复按钮文案池 ───────────────────────────────────────────────────────
# 元组格式：(label, closing)
# label: 真实按钮文案（含随机表情）；closing: 正文结尾自然引导语
_AUTO_REPLY_CTA_POOLS: Dict[str, list] = {
    TARGET_CONTACT: [
        ("💬 找 Mory 聊聊", "想单独聊的话，直接找 Mory 说一声就好。"),
        ("✨ 私聊 Mory", "有些话适合私下讲，想聊随时找 Mory。"),
        ("💌 悄悄找 Mory", "不方便在群里说的，可以悄悄找 Mory。"),
        ("👋 联系 Mory", "需要一对一沟通的话，Mory 随时在。"),
        ("🔑 我随时在", "想细聊的都可以找 Mory，我随时在。"),
    ],
    TARGET_SUBSCRIBE: [
        ("🛒 自助下单", "看完想继续的话，自助下单入口在下面。"),
        ("⚡ 一键下单", "已经了解过的话，可以直接自助下单。"),
        ("📦 查看订阅选项", "想持续收到这类内容，可以看看订阅选项。"),
        ("🛍️ 点这里下单", "合适的话点这里下单就行。"),
        ("🚀 想继续？点这", "想继续了解或订阅，点下面入口就行。"),
    ],
    TARGET_PREVIEW: [
        ("👀 看看预览", "想先看看内容，预览里都有，看完再决定不迟。"),
        ("🎁 先看一眼福利", "不确定的话，先去预览里看看实际内容。"),
        ("👀 预览入口在这", "想了解的都在预览里，点进去慢慢看。"),
    ],
}

# 未声明目标时随机二选一的候选
_AUTO_REPLY_RANDOM_TARGETS = (TARGET_CONTACT, TARGET_SUBSCRIBE)

# 卡片标题表情池（与按钮表情一样每次随机）
_AUTO_REPLY_TITLE_EMOJIS = ("💌", "✨", "🤍", "💬", "🌷")


def _resolve_cta_target(rule: Dict[str, Any]) -> Optional[str]:
    """按规则声明解析按钮目标。

    - contact/preview/subscribe：绑定对应池
    - none/空串/显式无入口：返回 \"none\"（禁止按钮）
    - 键缺失：返回 None（仅此时随机二选一）
    """
    if "conversion_target" not in rule:
        return None
    target = str(rule.get("conversion_target") or "").strip().lower()
    if target in _AUTO_REPLY_CTA_POOLS:
        return target
    # none / 空 / 未知目标一律视为无入口（普通聊天红线）
    return "none"


def pick_auto_reply_cta(
    rule: Dict[str, Any],
    rng: Optional[random.Random] = None,
) -> Optional[Dict[str, str]]:
    """选一个入口按钮（含文案与引导语），不选时返回 None。

    规则显式声明 conversion_target 时绑定对应目标；
    conversion_target=none/空串时无按钮；
    仅未声明 conversion_target 键时在「联系 / 自助下单」间随机二选一。
    """
    if not isinstance(rule, dict):
        return None
    if not bool(rule.get("button_enabled", True)):
        return None

    rng = rng or random.Random()
    target = _resolve_cta_target(rule)
    if target == "none":
        return None
    if target is None:
        target = rng.choice(_AUTO_REPLY_RANDOM_TARGETS)

    pool = _AUTO_REPLY_CTA_POOLS.get(target, [])
    if not pool:
        return None
    label, closing = rng.choice(pool)
    return {
        "target": target,
        "label": label,
        "closing": closing,
        "url": _DEFAULT_URLS.get(target, ""),
    }


def build_auto_reply_card(
    rule: Dict[str, Any],
    reply_text: str,
    chat_id: int,
    config: Optional[Dict[str, Any]] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """构建自动回复卡片（Rich + HTML 双版本 + 按钮）。

    返回：
        rich_html: Rich Message 块级标签卡片（RICH_MESSAGE_ENABLED 时使用）
        html_text: HTML parse_mode 卡片（所有客户端可用）
        markup:   单入口按钮（私聊恒为 None）
        closing:  正文结尾引导语（无按钮时为空串）
    """
    cfg = config or {}
    rng = rng or random.Random()
    safe_reply = (reply_text or "").strip()
    title = "Mory 小助理"
    badge = str(rule.get("name") or rule.get("topic") or "自动回复").strip()[:32]

    cta = pick_auto_reply_cta(rule, rng=rng)
    closing = ""
    markup = None
    if cta and int(chat_id or 0) < 0:
        closing = cta.get("closing", "")
        markup = build_cta_markup(cta, cfg)

    emoji = rng.choice(_AUTO_REPLY_TITLE_EMOJIS)
    rich_html = build_rich_card_message(
        title=title,
        body=safe_reply,
        footer="",
        badge=badge,
        emoji=emoji,
        closing=closing,
    )
    html_text = build_card_html(
        title=title,
        body=safe_reply,
        footer="",
        badge=badge,
        emoji=emoji,
        closing=closing,
    )
    # Rich 卡片与 HTML 卡片在旧客户端不可见时，保留纯文本兜底
    return {
        "rich_html": rich_html,
        "html_text": html_text,
        "markup": markup,
        "closing": closing,
    }


def is_auto_reply_card_enabled(config: Optional[Dict[str, Any]]) -> bool:
    """自动回复卡片总闸（默认关闭，铁律 #8 新功能默认关）。"""
    cfg = config or {}
    return bool(cfg.get("AUTO_REPLY_CARD_ENABLED", False))


def is_rich_message_enabled(config: Optional[Dict[str, Any]]) -> bool:
    """Rich Message 是否启用且格式版本兼容（与播报共用开关）。"""
    cfg = config or {}
    if not bool(cfg.get("RICH_MESSAGE_ENABLED", False)):
        return False
    fmt = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
    return fmt in ("rich", "auto")
