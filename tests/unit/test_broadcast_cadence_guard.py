# -*- coding: utf-8 -*-
"""生产主动播报节奏与实时模型门禁。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_config(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_production_config_keeps_only_three_distinct_mystic_broadcasts():
    config = _load_config("config.json")
    greetings = config["GREETING_CONFIG"]

    assert config["AUTO_GREETING"] is False
    assert config["AUTO_GOODNIGHT"] is False
    assert greetings["image_card_enabled"] is False
    assert all(
        greetings[f"{period}_enabled"] is False
        for period in ("morning", "afternoon", "evening", "night")
    )
    assert all(item["enabled"] is False for item in config["SCHEDULED_BROADCASTS"])
    assert all(item["image_card_enabled"] is False for item in config["SCHEDULED_BROADCASTS"])

    mystic = config["MYSTIC_BROADCAST_CONFIG"]
    assert mystic["enabled"] is True
    assert mystic["image_card_enabled"] is True
    assert [
        (mystic[f"{period}_time"], mystic[f"{period}_mode"])
        for period in ("morning", "afternoon", "evening")
    ] == [("09:05", "almanac"), ("13:05", "tarot"), ("20:35", "iching")]


def test_model_pool_matches_current_expiry_first_truth():
    expected_names = [
        "qwen3.7-max-preview",
        "qwen3.7-plus-2026-05-26",
        "qwen3.7-max-2026-06-08",
        "qwen3.7-flash-2026-07-15",
        "qwen3.7-flash",
        "deepseek-v4-flash-0731",
        "qwen3.8-max",
        "qwen3.8-2.4t-a95b",
        "deepseek-v4-pro-0813",
    ]
    for config_name in ("config.json", "config.json.example"):
        config = _load_config(config_name)
        models = config["MODEL_POOLS"]["llm"]
        names = [item["name"] for item in models]

        assert names == expected_names
        assert [item["expire"] for item in models] == sorted(item["expire"] for item in models)
        assert all(isinstance(item.get("enable_thinking"), bool) for item in models)
        assert config["MODEL_POOLS"]["vision"] == [
            {
                "name": "qwen3.5-ocr",
                "expire": "2026-09-14",
                "desc": "通义千问3.5 OCR",
            }
        ]
        assert config["CURRENT_MODEL_INDEX"] == 0
        assert config["BLACKLISTED_MODELS"] == []
        assert config["BLACKLISTED_MODELS_TS"] == {}
        assert config["AB_TEST_GROUP_A_MODEL"] == ""
        assert config["AB_TEST_GROUP_B_MODEL"] == ""


def test_secondary_routers_cannot_reintroduce_removed_models():
    from core.ab_test_router import GROUP_A, GROUP_B, get_model_for_group
    from core.model_router import _primary_model_from_pool

    config = _load_config("config.json.example")

    assert _primary_model_from_pool(config) == "qwen3.7-max-preview"
    assert get_model_for_group(GROUP_A, config) is None
    assert get_model_for_group(GROUP_B, config) is None
