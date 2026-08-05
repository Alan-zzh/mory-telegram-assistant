# -*- coding: utf-8 -*-
"""主题渲染 smoke 测试（theme / background_path / tarot 牌面 / 品牌印章）。

覆盖 v5.38.26 视觉升级：
- draw_card(options={"theme": "night"}) 出图成功（PNG 存在、高度 >1000）
- options 含指向不存在文件的 background_path → 静默跳过、仍出图成功（异常隔离）
- tarot payload 含 tarot_cards 牌面时出图成功
- 品牌印章保留：出图右下角区域存在红色系像素（参照 runtime/process_theme_assets.py _is_stamp_red）
- 不依赖 assets/broadcast 素材（背景统一用不存在的路径验证容错）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.broadcast_image_card import draw_card
from core.broadcast_image_payload import build_greeting_image_payload, build_tarot_image_payload


# 品牌印章红色判定（与 runtime/process_theme_assets.py 保持一致）
def _is_stamp_red(pixel) -> bool:
    r, g, b = pixel[:3]
    return r > 120 and 30 < g < 110 and 30 < b < 110


def _assert_render_ok(path: Path, info: dict) -> None:
    """公共断言：PNG 存在、体积 >1000、宽 800、高 >=1000。"""
    assert Path(path).exists(), f"未生成 PNG: {path}"
    assert os.path.getsize(path) > 1000, f"PNG 过小（疑似渲染失败）: {path}"
    assert info["width"] == 800
    assert info["height"] >= 1000


def test_night_theme_render_smoke(tmp_path: Path):
    """night 主题出图成功：PNG 存在且高度 >1000。"""
    payload = build_greeting_image_payload("night", "夜深了，还没睡的话不用硬睡，群里陪你待会儿。")
    out = tmp_path / "night_theme.png"
    path, info = draw_card(payload, str(out), cta="看看预览", min_height=1000, options={"theme": "night"})
    _assert_render_ok(Path(path), info)


def test_missing_background_path_skips_silently(tmp_path: Path):
    """background_path 指向不存在的文件 → 静默跳过、仍出图成功（异常隔离）。"""
    payload = build_greeting_image_payload("afternoon", "下午好，忙里偷闲记得歇口气。")
    missing = tmp_path / "no_such_bg.png"
    assert not missing.exists()
    out = tmp_path / "missing_bg.png"
    path, info = draw_card(
        payload, str(out), min_height=1000,
        options={"theme": "afternoon", "background_path": str(missing)},
    )
    _assert_render_ok(Path(path), info)


def test_tarot_cards_render_smoke(tmp_path: Path):
    """tarot payload 含 tarot_cards 牌面 → 出图成功。"""
    payload = build_tarot_image_payload({
        "blocks": [
            {"heading": "🎴 三张牌阵", "lines": [
                ("过去", "0 · 愚者 · 正位｜启程 / 自由"),
                ("现在", "1 · 魔术师 · 正位｜创造 / 行动"),
                ("未来", "2 · 女祭司 · 逆位｜直觉 / 迟疑"),
            ]},
        ],
        "insight": "现在是行动的好时机。",
    })
    assert payload.get("tarot_cards"), "塔罗 payload 应含 tarot_cards 牌面"
    out = tmp_path / "tarot_cards.png"
    path, info = draw_card(payload, str(out), min_height=1000, options={"theme": "afternoon"})
    _assert_render_ok(Path(path), info)


def test_brand_stamp_red_pixels_present(tmp_path: Path):
    """品牌印章保留：出图右下角区域存在红色系像素（印章未丢失）。"""
    payload = build_greeting_image_payload("night", "夜深了，想安静就安静，想聊就聊。")
    out = tmp_path / "stamp.png"
    path, info = draw_card(payload, str(out), cta="看看预览", min_height=1000, options={"theme": "night"})

    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    # 右下角区域覆盖品牌印章（x≈width-margin-130, y≈height-115）
    stamp_zone = im.crop((w - 260, h - 170, w, h))
    red_count = sum(1 for p in stamp_zone.getdata() if _is_stamp_red(p))
    im.close()
    assert red_count >= 200, f"右下角红色系像素过少（印章可能丢失）: {red_count}"
