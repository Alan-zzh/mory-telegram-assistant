# -*- coding: utf-8 -*-
"""配置兼容与规范化工具。"""


def _ensure_dict(cfg: dict, key: str) -> dict:
    """确保指定键为 dict。"""
    value = cfg.get(key)
    if not isinstance(value, dict):
        value = {}
        cfg[key] = value
    return value


def _sync_bool_alias(section: dict, primary: str, aliases: list[str], default: bool = False) -> None:
    """同步布尔键别名，优先使用主键，其次使用别名。"""
    value = None
    for key in [primary, *aliases]:
        if key in section:
            value = bool(section.get(key))
            break
    if value is None:
        value = default
    section[primary] = value
    for alias in aliases:
        section[alias] = value


def _sync_scalar_alias(section: dict, primary: str, aliases: list[str], default):
    """同步普通键别名，优先使用主键，其次使用别名。"""
    value = None
    for key in [primary, *aliases]:
        if key in section and section.get(key) not in (None, ""):
            value = section.get(key)
            break
    if value is None:
        value = default
    section[primary] = value
    for alias in aliases:
        section[alias] = value


def normalize_runtime_config(cfg: dict | None) -> dict:
    """统一新旧配置键，避免面板和运行逻辑各读各的。"""
    if not isinstance(cfg, dict):
        return {}

    cfg.pop("⚙️ 设置面板完全体 新增配置项（v5.0.0）", None)

    report_cfg = _ensure_dict(cfg, "REPORT_CONFIG")
    _sync_bool_alias(report_cfg, "enabled", ["enable"], False)

    anti_raid_cfg = _ensure_dict(cfg, "ANTI_RAID_CONFIG")
    _sync_bool_alias(anti_raid_cfg, "enabled", ["enable"], False)
    _sync_scalar_alias(anti_raid_cfg, "window", ["window_seconds"], 60)

    verification_cfg = _ensure_dict(cfg, "VERIFICATION_CONFIG")
    _sync_bool_alias(verification_cfg, "enable", ["enabled"], False)

    night_cfg = _ensure_dict(cfg, "NIGHT_MODE_CONFIG")
    _sync_bool_alias(night_cfg, "enable", ["enabled"], False)

    games_cfg = _ensure_dict(cfg, "GAMES_CONFIG")
    _sync_bool_alias(games_cfg, "enable", ["enabled"], False)

    checkin_cfg = _ensure_dict(cfg, "CHECKIN_CONFIG")
    _sync_bool_alias(checkin_cfg, "enable", ["enabled"], False)

    inactive_cfg = _ensure_dict(cfg, "AUTO_KICK_INACTIVE_DAYS")
    _sync_bool_alias(inactive_cfg, "enable", ["enabled"], False)

    ad_detect_cfg = _ensure_dict(cfg, "AD_DETECT_CONFIG")
    _sync_bool_alias(ad_detect_cfg, "enable", ["enabled"], False)

    for key in ["BLIND_BOX_CONFIG", "LUCKY_WHEEL_CONFIG", "REDPACKET_CONFIG", "LOTTERY_CONFIG", "SHOP_CONFIG", "COUPON_CONFIG", "AFK_CONFIG"]:
        section = _ensure_dict(cfg, key)
        _sync_bool_alias(section, "enabled", ["enable"], False)

    blind_box_cfg = _ensure_dict(cfg, "BLIND_BOX_CONFIG")
    blind_box_cfg["cost"] = int(blind_box_cfg.get("cost", cfg.get("BLIND_BOX_COST", 30)) or 30)
    cfg["BLIND_BOX_COST"] = int(blind_box_cfg["cost"])

    lucky_wheel_cfg = _ensure_dict(cfg, "LUCKY_WHEEL_CONFIG")
    lucky_wheel_cfg["cost"] = int(lucky_wheel_cfg.get("cost", cfg.get("LUCKY_WHEEL_COST", 10)) or 10)
    cfg["LUCKY_WHEEL_COST"] = int(lucky_wheel_cfg["cost"])

    greeting_cfg = _ensure_dict(cfg, "GREETING_CONFIG")
    greeting_cfg["morning_enabled"] = bool(greeting_cfg.get("morning_enabled", cfg.get("AUTO_GREETING", False)))
    greeting_cfg["afternoon_enabled"] = bool(greeting_cfg.get("afternoon_enabled", False))
    greeting_cfg["evening_enabled"] = bool(greeting_cfg.get("evening_enabled", cfg.get("AUTO_GOODNIGHT", greeting_cfg["morning_enabled"])))
    greeting_cfg["morning_time"] = greeting_cfg.get("morning_time", cfg.get("GREETING_HOUR", "08:05"))
    greeting_cfg["afternoon_time"] = greeting_cfg.get("afternoon_time", cfg.get("AFTERNOON_GREETING_HOUR", "12:35"))
    greeting_cfg["evening_time"] = greeting_cfg.get("evening_time", cfg.get("GOODNIGHT_HOUR", "23:05"))
    cfg["AUTO_GREETING"] = bool(greeting_cfg["morning_enabled"])
    cfg["AUTO_GOODNIGHT"] = bool(greeting_cfg["evening_enabled"])
    cfg["GREETING_HOUR"] = greeting_cfg["morning_time"]
    cfg["AFTERNOON_GREETING_HOUR"] = greeting_cfg["afternoon_time"]
    cfg["GOODNIGHT_HOUR"] = greeting_cfg["evening_time"]

    mystic_cfg = _ensure_dict(cfg, "MYSTIC_BROADCAST_CONFIG")
    mystic_cfg["enabled"] = bool(mystic_cfg.get("enabled", False))
    mystic_cfg["cta_enabled"] = bool(mystic_cfg.get("cta_enabled", False))
    mystic_cfg["private_reply_enabled"] = bool(
        mystic_cfg.get("private_reply_enabled", False)
    )
    mystic_cfg["morning_time"] = mystic_cfg.get("morning_time", "09:05")
    mystic_cfg["morning_mode"] = "almanac"
    mystic_cfg["afternoon_time"] = mystic_cfg.get("afternoon_time", "13:05")
    mystic_cfg["afternoon_mode"] = "tarot"
    mystic_cfg["evening_time"] = mystic_cfg.get("evening_time", "20:35")
    mystic_cfg["evening_mode"] = "iching"
    mystic_cfg["legacy_targeted_tarot_enabled"] = bool(
        mystic_cfg.get("legacy_targeted_tarot_enabled", False)
    )

    return cfg


def compact_runtime_config(cfg: dict | None) -> dict:
    """压缩为适合落盘的主键结构，避免把兼容别名都写回文件。"""
    cfg = normalize_runtime_config(dict(cfg or {}))

    for section_key, alias_keys in {
        "REPORT_CONFIG": ["enable"],
        "ANTI_RAID_CONFIG": ["enable", "window_seconds"],
        "LOTTERY_CONFIG": ["enable"],
        "BLIND_BOX_CONFIG": ["enable"],
        "LUCKY_WHEEL_CONFIG": ["enable"],
        "REDPACKET_CONFIG": ["enable"],
        "SHOP_CONFIG": ["enable"],
        "COUPON_CONFIG": ["enable"],
        "AFK_CONFIG": ["enable"],
    }.items():
        section = cfg.get(section_key)
        if isinstance(section, dict):
            for alias in alias_keys:
                section.pop(alias, None)

    for section_key, alias_keys in {
        "VERIFICATION_CONFIG": ["enabled"],
        "NIGHT_MODE_CONFIG": ["enabled"],
        "GAMES_CONFIG": ["enabled"],
        "CHECKIN_CONFIG": ["enabled"],
        "AUTO_KICK_INACTIVE_DAYS": ["enabled"],
        "AD_DETECT_CONFIG": ["enabled"],
    }.items():
        section = cfg.get(section_key)
        if isinstance(section, dict):
            for alias in alias_keys:
                section.pop(alias, None)

    return cfg
