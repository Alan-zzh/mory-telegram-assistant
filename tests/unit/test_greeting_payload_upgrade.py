# -*- coding: utf-8 -*-
"""问候卡 payload 升级与人设一致性测试。

覆盖 v5.38.26 问候卡升级：
- build_greeting_image_payload 返回 date_text（X月X日 周X 格式）与"今日一句"区块
- _GREETING_TIPS 贴士池恰为 9 条，且全部不命中 MessageTemplates.GREETING_STYLE_BAN 禁区词
- 问候 fallback 池（含 night）全部长度 30-120 且不命中禁区词
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.broadcast_image_payload import _GREETING_TIPS, _MORY_QUOTES, build_greeting_image_payload
from tasks.support.message_templates import MessageTemplates

# date_text 格式：X月X日 周X（X 为 1-2 位数字，周后为一二三四五六日）
_DATE_TEXT_RE = re.compile(r"^\d{1,2}月\d{1,2}日 周[一二三四五六日]$")


def test_greeting_payload_has_date_text_and_today_line():
    """问候卡 payload 含 date_text（X月X日 周X）与"今日一句"区块。"""
    for period in ("morning", "afternoon", "evening", "night"):
        p = build_greeting_image_payload(period, "今天也要元气满满哦～", badge="新的一天")
        # 右上角日期：北京时间当日真实日期，只断言格式不虚构
        assert _DATE_TEXT_RE.fullmatch(p["date_text"]), (
            f"{period} date_text 格式异常: {p['date_text']!r}"
        )
        # 区块含"今日一句"，且内容非空
        headings = [b["heading"] for b in p["blocks"]]
        assert "今日一句" in headings, f"{period} 缺今日一句区块: {headings}"
        tip_block = next(b for b in p["blocks"] if b["heading"] == "今日一句")
        assert tip_block["lines"] and tip_block["lines"][0][1], "今日一句内容为空"
        # 正文走 insight 语录卡片，kicker 沿用传入徽标
        assert p["insight"] == "今天也要元气满满哦～"
        assert p["kicker"] == "新的一天"


def test_greeting_tips_pool_has_exactly_nine_and_no_ban_words():
    """_GREETING_TIPS 恰为 9 条，且全部不命中 GREETING_STYLE_BAN 禁区词（人设一致性）。"""
    assert len(_GREETING_TIPS) == 9, f"贴士池应恰好 9 条，实际 {len(_GREETING_TIPS)}"
    banned = MessageTemplates.GREETING_STYLE_BAN
    for tip in _GREETING_TIPS:
        hits = [marker for marker in banned if marker in tip]
        assert not hits, f"贴士命中禁区词 {hits}: {tip!r}"


def _extract_tip_quote(p: dict) -> tuple:
    tip = next(b["lines"][0][1] for b in p["blocks"] if b["heading"] == "今日一句")
    quote = next(b["lines"][0][1] for b in p["blocks"] if b["heading"] == "一言")
    return tip, quote


def test_greeting_seed_stable_and_default_varies():
    """文案随机化契约：传 seed 稳定复现；不传 seed 每次重新随机且值域合法。"""
    # 同 seed 两次调用：贴士与一言完全一致（测试/回放可复现）
    p1 = build_greeting_image_payload("morning", "正文", seed="2026-08-06|morning")
    p2 = build_greeting_image_payload("morning", "正文", seed="2026-08-06|morning")
    assert _extract_tip_quote(p1) == _extract_tip_quote(p2)

    # 不传 seed：多次调用值域合法（必在池内）；抽足够多次应出现多于 1 种组合
    combos = set()
    for _ in range(20):
        p = build_greeting_image_payload("morning", "正文")
        tip, quote = _extract_tip_quote(p)
        assert tip in _GREETING_TIPS, f"贴士不在池内: {tip!r}"
        assert quote in _MORY_QUOTES, f"一言不在池内: {quote!r}"
        combos.add((tip, quote))
    assert len(combos) > 1, "默认随机失效：20 次抽取组合完全相同"


@pytest.mark.parametrize("period", ["morning", "afternoon", "evening", "night"])
def test_greeting_fallback_pool_length_and_ban_words(period):
    """问候 fallback 池（含 night）全部长度 30-120 且不命中禁区词。"""
    pool = MessageTemplates.GREETING_FALLBACK_POOL.get(period, [])
    assert pool, f"{period} 无 fallback 池"
    banned = MessageTemplates.GREETING_STYLE_BAN
    for text in pool:
        assert 30 <= len(text) <= 120, f"{period} 文案长度 {len(text)} 越界: {text!r}"
        hits = [marker for marker in banned if marker in text]
        assert not hits, f"{period} 文案命中禁区词 {hits}: {text!r}"
