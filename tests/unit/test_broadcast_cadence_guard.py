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


def test_realtime_models_have_explicit_thinking_contract_and_no_expired_model():
    for config_name in ("config.json", "config.json.example"):
        config = _load_config(config_name)
        models = config["MODEL_POOLS"]["llm"]
        names = {item["name"] for item in models}

        assert "qwen3.6-27b" not in names
        assert all(isinstance(item.get("enable_thinking"), bool) for item in models)
        assert config["AB_TEST_GROUP_A_MODEL"] == "qwen3.7-plus-2026-05-26"
        assert config["AB_TEST_GROUP_B_MODEL"] == "qwen3.7-max-2026-06-08"
