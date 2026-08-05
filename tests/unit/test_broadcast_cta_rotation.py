# -*- coding: utf-8 -*-
"""CTA 日期轮换与玄学单入口测试。

覆盖 v5.38.26 的 _stable_seed(date_key) 升级（日期参与种子）：
- 同 scene/period/mode + 同 date_key → 两次调用结果完全一致（同日全群一致）
- 同 scene/period/mode 跨连续 7 天 → label 至少出现 2 种（跨日轮换）
- 玄学三入口单入口：cta_enabled=True 时 target ∈ {preview, contact, subscribe} 且每次只有一个
- cta_enabled=False（或缺失）→ 玄学场景无入口（回归保护）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.broadcast_cta import get_broadcast_cta

# 开启玄学 CTA，让 mystic 三档有入口
CFG = {"MYSTIC_BROADCAST_CONFIG": {"cta_enabled": True}}

# (scene, period, mode)：覆盖玄学三档 + 问候午后/夜间 + 定点三档（全部有入口）
SCENES = [
    ("mystic", "morning", "almanac"),
    ("mystic", "afternoon", "tarot"),
    ("mystic", "evening", "iching"),
    ("greeting", "afternoon", ""),
    ("greeting", "night", ""),
    ("scheduled", "morning", ""),
    ("scheduled", "afternoon", ""),
    ("scheduled", "night", ""),
]

# 玄学三档（单入口断言专用）
MYSTIC_SCENES = [
    ("mystic", "morning", "almanac"),
    ("mystic", "afternoon", "tarot"),
    ("mystic", "evening", "iching"),
]

# 固定连续 7 天（与 runtime/verify_cta_rotation.py 一致），避免测试依赖系统时钟
DATES = [f"2026-08-{day:02d}" for day in range(1, 8)]


def test_same_date_key_is_deterministic():
    """同 date_key 两次调用 → 返回完全一致的 CTA dict（确定性，同日全群一致）。"""
    for scene, period, mode in SCENES:
        cta_1 = get_broadcast_cta(
            scene=scene, period=period, mode=mode, config=CFG, date_key="2026-08-03"
        )
        cta_2 = get_broadcast_cta(
            scene=scene, period=period, mode=mode, config=CFG, date_key="2026-08-03"
        )
        assert cta_1 == cta_2, f"{scene}/{period}/{mode or '-'} 同日两次调用结果不一致"


def test_cta_labels_rotate_across_dates():
    """同 scene/period/mode 跨连续 7 天 → label 集合至少 2 种（日期参与种子，跨日轮换）。"""
    for scene, period, mode in SCENES:
        labels = set()
        for date_key in DATES:
            cta = get_broadcast_cta(
                scene=scene, period=period, mode=mode, config=CFG, date_key=date_key
            )
            assert cta["target"] != "none", f"{scene}/{period}/{mode or '-'} 应有入口"
            labels.add(cta["label"])
        assert len(labels) >= 2, (
            f"{scene}/{period}/{mode or '-'} 跨 7 天 label 无变化: {sorted(labels)}"
        )


def test_mystic_cta_single_entry_target_scope():
    """玄学三入口单入口断言：cta_enabled=True 时 target ∈ {preview, contact, subscribe}。

    每次调用只返回一个 target（target 为单值字符串），且该入口的
    label / image_label / url 齐备（图片卡印字与真实按钮强绑定）。
    """
    for scene, period, mode in MYSTIC_SCENES:
        for date_key in DATES:
            cta = get_broadcast_cta(
                scene=scene, period=period, mode=mode, config=CFG, date_key=date_key
            )
            assert cta["target"] in {"preview", "contact", "subscribe"}, (
                f"{scene}/{period}/{mode} @ {date_key} 出现非法入口 target={cta['target']!r}"
            )
            assert cta["label"], f"target={cta['target']} 但 label 为空"
            assert cta["image_label"], "image_label 为空（图片卡上无法印按钮文案）"
            assert cta["url"], f"target={cta['target']} 但 url 为空"


def test_mystic_cta_disabled_returns_none():
    """cta_enabled=False（或配置缺失）→ 玄学场景无入口（回归保护）。"""
    for scene, period, mode in MYSTIC_SCENES:
        cta = get_broadcast_cta(
            scene=scene, period=period, mode=mode, config={}, date_key="2026-08-03"
        )
        assert cta["target"] == "none"
        assert cta["label"] == ""
        assert cta["image_label"] == ""
