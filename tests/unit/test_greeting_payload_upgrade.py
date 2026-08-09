# -*- coding: utf-8 -*-
"""问候卡只允许一份经过质量门禁的正文。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.broadcast_image_payload import build_greeting_image_payload
from tasks.support.message_templates import MessageTemplates

_DATE_TEXT_RE = re.compile(r"^\d{1,2}月\d{1,2}日 周[一二三四五六日]$")


@pytest.mark.parametrize("period", ["morning", "afternoon", "evening", "night"])
def test_greeting_payload_has_one_coherent_body(period):
    body = "今天在群里跟大家问声好，照顾好自己就行。"
    payload = build_greeting_image_payload(period, body, badge="Mory 小助理")

    assert _DATE_TEXT_RE.fullmatch(payload["date_text"])
    assert payload["insight"] == body
    assert payload["kicker"] == "Mory 小助理"
    assert payload["blocks"] == []


def test_greeting_payload_seed_cannot_inject_unrelated_random_copy():
    first = build_greeting_image_payload("morning", "同一份正文", seed="first")
    second = build_greeting_image_payload("morning", "同一份正文", seed="second")

    assert first == second
    assert "今日一句" not in str(first)
    assert "一言" not in str(first)


def test_fixed_greeting_fallback_pool_is_removed():
    assert not hasattr(MessageTemplates, "GREETING_FALLBACK_POOL")
    assert not hasattr(MessageTemplates, "get_fallback_greeting")
