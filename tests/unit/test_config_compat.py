# -*- coding: utf-8 -*-
"""[Codex] 配置兼容层必须把 Dashboard/Bot 面板的历史键自动对齐。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def test_normalize_runtime_config_syncs_enable_enabled_pairs():
    from core.config_compat import normalize_runtime_config

    cfg = {
        "REPORT_CONFIG": {"enabled": True},
        "CHECKIN_CONFIG": {"enable": True, "base_points": 8},
        "LOTTERY_CONFIG": {"enabled": True},
        "SHOP_CONFIG": {"enabled": True},
    }

    normalized = normalize_runtime_config(cfg)

    assert normalized["REPORT_CONFIG"]["enable"] is True
    assert normalized["REPORT_CONFIG"]["enabled"] is True
    assert normalized["CHECKIN_CONFIG"]["enable"] is True
    assert normalized["CHECKIN_CONFIG"]["enabled"] is True
    assert normalized["LOTTERY_CONFIG"]["enable"] is True
    assert normalized["LOTTERY_CONFIG"]["enabled"] is True
    assert normalized["SHOP_CONFIG"]["enable"] is True
    assert normalized["SHOP_CONFIG"]["enabled"] is True


def test_normalize_runtime_config_syncs_greeting_and_news_legacy_keys():
    from core.config_compat import normalize_runtime_config

    cfg = {
        "GREETING_CONFIG": {
            "morning_enabled": True,
            "afternoon_enabled": True,
            "evening_enabled": False,
            "morning_time": "08:11",
            "afternoon_time": "12:44",
            "evening_time": "23:21",
        },
        "NEWS_BROADCAST_CONFIG": {
            "enabled": True,
            "preferred_source": "real_first",
            "morning_time": "09:09",
            "afternoon_time": "13:13",
            "evening_time": "20:29",
        },
    }

    normalized = normalize_runtime_config(cfg)

    assert normalized["AUTO_GREETING"] is True
    assert normalized["AUTO_GOODNIGHT"] is False
    assert normalized["GREETING_HOUR"] == "08:11"
    assert normalized["AFTERNOON_GREETING_HOUR"] == "12:44"
    assert normalized["GOODNIGHT_HOUR"] == "23:21"
    assert normalized["AUTO_NEWS"] is True
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["enabled"] is False
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["cta_enabled"] is False
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["morning_mode"] == "almanac"
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["afternoon_mode"] == "tarot"
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["evening_mode"] == "iching"
    assert normalized["NEWS_HOUR_MORNING"] == "09:09"
    assert normalized["NEWS_HOUR_AFTERNOON"] == "13:13"
    assert normalized["NEWS_HOUR_EVENING"] == "20:29"


def test_normalize_runtime_config_syncs_anti_raid_window_alias():
    from core.config_compat import normalize_runtime_config

    cfg = {"ANTI_RAID_CONFIG": {"enabled": True, "window_seconds": 90}}

    normalized = normalize_runtime_config(cfg)

    assert normalized["ANTI_RAID_CONFIG"]["window"] == 90
    assert normalized["ANTI_RAID_CONFIG"]["window_seconds"] == 90


def test_normalize_runtime_config_removes_fake_comment_key_and_syncs_cost_aliases():
    from core.config_compat import normalize_runtime_config

    cfg = {
        "⚙️ 设置面板完全体 新增配置项（v5.0.0）": "说明文字，不该当配置",
        "BLIND_BOX_CONFIG": {"cost": 66},
        "LUCKY_WHEEL_COST": 18,
    }

    normalized = normalize_runtime_config(cfg)

    assert "⚙️ 设置面板完全体 新增配置项（v5.0.0）" not in normalized
    assert normalized["BLIND_BOX_CONFIG"]["cost"] == 66
    assert normalized["BLIND_BOX_COST"] == 66
    assert normalized["LUCKY_WHEEL_CONFIG"]["cost"] == 18
    assert normalized["LUCKY_WHEEL_COST"] == 18


def test_compact_runtime_config_keeps_only_primary_disk_keys():
    from core.config_compat import compact_runtime_config

    cfg = {
        "REPORT_CONFIG": {"enabled": True, "enable": True},
        "ANTI_RAID_CONFIG": {"enabled": True, "enable": True, "window": 60, "window_seconds": 60},
        "CHECKIN_CONFIG": {"enable": False, "enabled": False},
    }

    compacted = compact_runtime_config(cfg)

    assert "enable" not in compacted["REPORT_CONFIG"]
    assert "enable" not in compacted["ANTI_RAID_CONFIG"]
    assert "window_seconds" not in compacted["ANTI_RAID_CONFIG"]
    assert "enabled" not in compacted["CHECKIN_CONFIG"]


def test_save_config_skips_when_disk_file_is_newer(tmp_path):
    import core.bot_initializer as bi

    original_path = bi.CONFIG_FILE
    original_mtime = bi._loaded_config_mtime
    try:
        config_path = tmp_path / "config.json"
        config_path.write_text('{"RELAY_MODE_ENABLED": false}', encoding="utf-8")
        bi.CONFIG_FILE = str(config_path)
        bi._loaded_config_mtime = 1.0

        ok = bi.save_config({"RELAY_MODE_ENABLED": True})

        assert ok is False
        assert '"RELAY_MODE_ENABLED": false' in config_path.read_text(encoding="utf-8")
    finally:
        bi.CONFIG_FILE = original_path
        bi._loaded_config_mtime = original_mtime
