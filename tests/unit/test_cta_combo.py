# -*- coding: utf-8 -*-
"""CTA 组合按钮测试（v5.38.27）。

覆盖 get_broadcast_cta_combo / build_cta_markup_combo：
- 同 date_key 组合稳定（同日全群一致）；跨连续 7 天出现 ≥2 种模式（跨日轮换）
- duo 组合按钮目标不重复、preview 在前
- mystic cta_enabled=false 空按钮；greeting morning/evening 空按钮；scheduled 仅 preview
- build_cta_markup_combo 按钮数与布局正确（单按钮一行 1 个、双按钮同一行 2 个）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.broadcast_cta import build_cta_markup_combo, get_broadcast_cta_combo

# 开启玄学 CTA，让 mystic 三档有入口
CFG = {"MYSTIC_BROADCAST_CONFIG": {"cta_enabled": True}}

# 固定连续 7 天，避免测试依赖系统时钟
DATES = [f"2026-08-{day:02d}" for day in range(1, 8)]

MYSTIC_SCENES = [
    ("mystic", "morning", "almanac"),
    ("mystic", "afternoon", "tarot"),
    ("mystic", "evening", "iching"),
]

_MODE_NAMES = {
    ("preview",): "single_preview",
    ("contact",): "single_contact",
    ("subscribe",): "single_subscribe",
    ("preview", "contact"): "duo_preview_contact",
    ("preview", "subscribe"): "duo_preview_subscribe",
}


def _mode_of(combo: dict) -> str:
    """从 combo 的 buttons target 序列推断模式名。"""
    targets = tuple(b["target"] for b in combo.get("buttons") or [])
    return _MODE_NAMES.get(targets, "_".join(targets))


def test_combo_stable_same_date_key():
    """同 scene/period/mode + 同 date_key → 两次调用返回完全一致的组合（同日全群一致）。"""
    for scene, period, mode in MYSTIC_SCENES:
        c_1 = get_broadcast_cta_combo(
            scene=scene, period=period, mode=mode, config=CFG, date_key="2026-08-03"
        )
        c_2 = get_broadcast_cta_combo(
            scene=scene, period=period, mode=mode, config=CFG, date_key="2026-08-03"
        )
        assert c_1 == c_2, f"{scene}/{period}/{mode or '-'} 同日两次调用结果不一致"


def test_combo_rotates_across_dates():
    """同 scene/period/mode 跨连续 7 天 → 组合模式至少出现 2 种（日期参与种子，跨日轮换）。"""
    for scene, period, mode in MYSTIC_SCENES:
        modes = set()
        for date_key in DATES:
            combo = get_broadcast_cta_combo(
                scene=scene, period=period, mode=mode, config=CFG, date_key=date_key
            )
            assert combo.get("buttons"), f"{scene}/{period}/{mode or '-'} @ {date_key} 应为空按钮"
            modes.add(_mode_of(combo))
        assert len(modes) >= 2, (
            f"{scene}/{period}/{mode or '-'} 跨 7 天组合无变化: {sorted(modes)}"
        )


def test_combo_duo_targets_unique_and_preview_first():
    """7 天滚动：duo 组合 preview 必须在前、目标不重复；单按钮 target 属于合法入口。"""
    for scene, period, mode in MYSTIC_SCENES:
        for date_key in DATES:
            combo = get_broadcast_cta_combo(
                scene=scene, period=period, mode=mode, config=CFG, date_key=date_key
            )
            targets = [b["target"] for b in combo.get("buttons") or []]
            if len(targets) == 2:
                assert targets[0] == "preview", (
                    f"{scene}/{period}/{mode} @ {date_key} duo 组合 preview 不在前: {targets}"
                )
                assert len(set(targets)) == 2, (
                    f"{scene}/{period}/{mode} @ {date_key} duo 组合目标重复: {targets}"
                )
            elif len(targets) == 1:
                assert targets[0] in {"preview", "contact", "subscribe"}, (
                    f"{scene}/{period}/{mode} @ {date_key} 非法入口: {targets}"
                )
            else:
                assert False, f"{scene}/{period}/{mode} @ {date_key} 不应空按钮"


def test_combo_empty_scenes():
    """mystic cta_enabled=false / greeting morning/evening / news → 空按钮。"""
    # mystic cta_enabled=false（或配置缺失）→ 空按钮
    for scene, period, mode in MYSTIC_SCENES:
        combo = get_broadcast_cta_combo(scene=scene, period=period, mode=mode, config={}, date_key="2026-08-03")
        assert combo["buttons"] == [], f"{scene}/{period}/{mode} cta_enabled=false 应无按钮"
        assert combo["closing"] == ""
    # greeting 非午后/夜间（morning/evening）→ 空按钮
    assert get_broadcast_cta_combo(scene="greeting", period="morning", config=CFG)["buttons"] == []
    assert get_broadcast_cta_combo(scene="greeting", period="evening", config=CFG)["buttons"] == []
    # news 纯资讯 → 空按钮
    assert get_broadcast_cta_combo(scene="news", config=CFG)["buttons"] == []


def test_scheduled_only_preview():
    """scheduled 恒为 preview 单按钮（定点播报历史规则只给预览，不组合）。"""
    for period in ("morning", "afternoon", "night", ""):
        for date_key in DATES:
            combo = get_broadcast_cta_combo(
                scene="scheduled", period=period, config=CFG, date_key=date_key
            )
            targets = [b["target"] for b in combo["buttons"]]
            assert targets == ["preview"], (
                f"scheduled/{period or '-'} @ {date_key} 出现非 preview: {targets}"
            )


def test_build_markup_combo_button_count_and_layout():
    """单按钮一行 1 个、双按钮同一行 2 个（row_width=2）；空按钮返回 None。"""
    duo = {
        "buttons": [
            {"target": "preview", "label": "看预览", "url": "https://t.me/moryselect", "style": "primary", "closing": ""},
            {"target": "contact", "label": "找 Mory", "url": "https://t.me/Moryfansbot", "style": "primary", "closing": ""},
        ],
        "closing": "",
    }
    markup_duo = build_cta_markup_combo(duo, config=CFG)
    assert markup_duo is not None
    assert len(markup_duo.keyboard) == 1, "双按钮应同一行"
    assert len(markup_duo.keyboard[0]) == 2, "双按钮应同一行 2 个"

    single = {
        "buttons": [
            {"target": "preview", "label": "看预览", "url": "https://t.me/moryselect", "style": "primary", "closing": ""},
        ],
        "closing": "",
    }
    markup_single = build_cta_markup_combo(single, config=CFG)
    assert markup_single is not None
    assert len(markup_single.keyboard[0]) == 1, "单按钮应一行 1 个"

    # 空按钮 / 非 dict / 无 buttons → None
    assert build_cta_markup_combo({"buttons": [], "closing": ""}) is None
    assert build_cta_markup_combo({}) is None
    assert build_cta_markup_combo(None) is None

    # 全 none target 也应返回 None（无有效按钮）
    all_none = {"buttons": [{"target": "none", "label": "", "url": ""}], "closing": ""}
    assert build_cta_markup_combo(all_none, config=CFG) is None


def test_combo_button_fields_complete():
    """buttons 内每个 cta 复用单按钮结构：target/label/image_label/url/style/closing 齐备。"""
    for scene, period, mode in MYSTIC_SCENES:
        combo = get_broadcast_cta_combo(
            scene=scene, period=period, mode=mode, config=CFG, date_key="2026-08-03"
        )
        for btn in combo["buttons"]:
            assert btn["target"] in {"preview", "contact", "subscribe"}
            assert btn["label"], f"target={btn['target']} 但 label 为空"
            assert btn["image_label"], "image_label 为空"
            assert btn["url"], f"target={btn['target']} 但 url 为空"
            assert btn["style"] in {"primary", "success"}
            assert isinstance(btn["closing"], str)
