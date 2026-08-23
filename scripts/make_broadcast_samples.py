# -*- coding: utf-8 -*-
"""v5.38.27 样张生成：问候 4 档（一言区块+深色主题可读性）+ 玄学组合卡，无图上按钮。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.broadcast_image_card import build_broadcast_image_card, resolve_theme_options
from core.broadcast_image_payload import (
    build_greeting_image_payload,
    build_mystic_image_payload,
)
from tasks.support.mystic_content import build_mystic_broadcast

CFG = {
    "BROADCAST_THEME_ENABLED": True,
    "GREETING_CONFIG": {"image_card_enabled": True},
    "MYSTIC_BROADCAST_CONFIG": {"enabled": True, "image_card_enabled": True, "cta_enabled": True},
}

BODIES = {
    "morning": "早，今天按自己的节奏来就行，群里随时有人接话。",
    "afternoon": "下午好，忙里偷闲记得歇口气，聊两句再继续。",
    "evening": "晚上好，今天辛苦了，想说话就来群里冒个泡。",
    "night": "夜深了，还没睡的话不用硬睡，群里陪你待会儿。",
}

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "runtime", "cache", "broadcast", "demo")
os.makedirs(OUT, exist_ok=True)

for period, body in BODIES.items():
    payload = build_greeting_image_payload(period, body)
    out = build_broadcast_image_card(
        payload,
        cache_key=f"v53827_greeting_{period}",
        config=CFG,
        min_height=900,
        cta_text="",
        options=resolve_theme_options(CFG, period),
    )
    print(f"greeting_{period}: {out}")

for period in ("morning", "afternoon", "evening"):
    mp = build_mystic_image_payload(build_mystic_broadcast(CFG, period=period))
    out = build_broadcast_image_card(
        mp,
        cache_key=f"v53827_mystic_{period}",
        config=CFG,
        min_height=1100,
        cta_text="",
        options=resolve_theme_options(CFG, period),
    )
    print(f"mystic_{period}: {out}")
print("SAMPLES_DONE")
