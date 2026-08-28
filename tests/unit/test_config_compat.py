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


def test_normalize_runtime_config_syncs_greeting_legacy_keys():
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
    }

    normalized = normalize_runtime_config(cfg)

    assert normalized["AUTO_GREETING"] is True
    assert normalized["AUTO_GOODNIGHT"] is False
    assert normalized["GREETING_HOUR"] == "08:11"
    assert normalized["AFTERNOON_GREETING_HOUR"] == "12:44"
    assert normalized["GOODNIGHT_HOUR"] == "23:21"
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["enabled"] is False
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["cta_enabled"] is False
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["private_reply_enabled"] is False
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["morning_mode"] == "almanac"
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["afternoon_mode"] == "tarot"
    assert normalized["MYSTIC_BROADCAST_CONFIG"]["evening_mode"] == "iching"


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


def test_model_index_is_not_restored_from_or_written_to_database(tmp_path):
    """旧数据库索引不能覆盖当前模型池真相，也不能被临时切换重新固化。"""
    import core.bot_initializer as bi

    class FakeDB:
        def __init__(self):
            self.writes = []

        def get_system_state(self, key):
            return "7" if key == "CURRENT_MODEL_INDEX" else None

        def set_system_state(self, key, value):
            self.writes.append((key, value))

    original_path = bi.CONFIG_FILE
    original_mtime = bi._loaded_config_mtime
    try:
        config_path = tmp_path / "config.json"
        config_path.write_text('{"CURRENT_MODEL_INDEX": 0}', encoding="utf-8")
        bi.CONFIG_FILE = str(config_path)
        bi._loaded_config_mtime = config_path.stat().st_mtime
        cfg = {"CURRENT_MODEL_INDEX": 0}
        db = FakeDB()

        bi._load_dynamic_states(cfg, db)
        assert cfg["CURRENT_MODEL_INDEX"] == 0

        assert bi.save_config(cfg, db) is True
        assert all(key != "CURRENT_MODEL_INDEX" for key, _value in db.writes)
    finally:
        bi.CONFIG_FILE = original_path
        bi._loaded_config_mtime = original_mtime


def test_compact_runtime_config_strips_plaintext_secrets():
    """凭据唯一存 .env：落盘配置不得携带明文 TOKEN/API_KEY（v5.41.0 红线回归）。"""
    from core.config_compat import compact_runtime_config

    cfg = {
        "TOKEN": "123456:ABC-real-secret",
        "API_KEY": "sk-real-llm-key",
        "NSFW_DETECT_CONFIG": {"enabled": True, "api_key": "nsfw-secret"},
        "SPAM_WATCH_CONFIG": {"spamwatch_token": "spam-secret"},
        "nested": [{"private_key": "private-secret", "max_tokens": 2048}],
        "GROUP_ID": -100123,
        "REPORT_CONFIG": {"enabled": True},
    }

    compacted = compact_runtime_config(cfg)

    assert compacted["TOKEN"] == ""
    assert compacted["API_KEY"] == ""
    assert compacted["NSFW_DETECT_CONFIG"]["api_key"] == ""
    assert compacted["SPAM_WATCH_CONFIG"]["spamwatch_token"] == ""
    assert compacted["nested"][0]["private_key"] == ""
    assert compacted["nested"][0]["max_tokens"] == 2048
    # 非敏感键不受影响
    assert compacted["GROUP_ID"] == -100123
    assert compacted["REPORT_CONFIG"]["enabled"] is True


def test_environment_secrets_are_injected_only_into_runtime_shape():
    from core.config_compat import inject_environment_secrets

    cfg = {"NSFW_DETECT_CONFIG": {"enabled": True}}
    inject_environment_secrets(
        cfg,
        {
            "TG_TOKEN": "telegram-runtime",
            "DASHSCOPE_KEY": "llm-runtime",
            "NSFW_DETECT_API_KEY": "nsfw-runtime",
            "SPAMWATCH_TOKEN": "spam-runtime",
            "EXCHANGE_API_KEY": "exchange-runtime",
        },
    )

    assert cfg["TOKEN"] == "telegram-runtime"
    assert cfg["API_KEY"] == "llm-runtime"
    assert cfg["NSFW_DETECT_CONFIG"]["api_key"] == "nsfw-runtime"
    assert cfg["SPAM_WATCH_CONFIG"]["spamwatch_token"] == "spam-runtime"
    assert cfg["EXCHANGE_API_KEY"] == "exchange-runtime"


def test_save_config_writes_atomically_and_never_persists_secrets(tmp_path):
    """save_config 必须原子写（无 .tmp 残留）且不把环境注入的凭据写回磁盘。"""
    import json

    import core.bot_initializer as bi

    original_path = bi.CONFIG_FILE
    original_mtime = bi._loaded_config_mtime
    try:
        config_path = tmp_path / "config.json"
        config_path.write_text('{"TOKEN": "", "API_KEY": ""}', encoding="utf-8")
        bi.CONFIG_FILE = str(config_path)
        bi._loaded_config_mtime = config_path.stat().st_mtime

        ok = bi.save_config(
            {"TOKEN": "123456:ABC-runtime-env", "API_KEY": "sk-runtime-env"}
        )

        assert ok is True
        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["TOKEN"] == ""
        assert on_disk["API_KEY"] == ""
        # 原子写：同目录不得残留临时文件
        residues = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
        assert residues == []
    finally:
        bi.CONFIG_FILE = original_path
        bi._loaded_config_mtime = original_mtime
