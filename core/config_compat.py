# -*- coding: utf-8 -*-
"""配置兼容、环境凭据注入与落盘规范化工具。"""

import copy
import os

# 凭据唯一存 .env（AGENTS.md 红线）：任何落盘配置不得携带明文凭据。
# 启动时由 bot_initializer 以 TG_TOKEN / DASHSCOPE_KEY 环境变量覆盖注入，
# 因此落盘前剥离不影响运行，仅防止"运行时保存把环境变量里的密钥写回文件"。
SECRET_CONFIG_KEYS = ("TOKEN", "API_KEY")
REMOVED_CONFIG_FIELDS = frozenset({
    # 已确认没有运行入口；部署与运行时保存都必须移除，避免幽灵配置复活。
    "STATS_REPORT_CONFIG",
    "NEWS_BROADCAST_CONFIG",
    "AUTO_NEWS",
    "NEWS_HOUR_MORNING",
    "NEWS_HOUR_AFTERNOON",
    "NEWS_HOUR_EVENING",
    "CONVERSION_HOOKS",
    "FLIRT_TEMPLATES",
    "SHOP_ITEMS",
    "COST_STRATEGY",
    # 旧版复数凭据容器；当前凭据只允许由 .env 注入明确的单一运行时键。
    "API_KEYS",
    # 旧面板/自然语言入口曾允许写入，但业务运行链从不读取；保留只会制造假生效。
    "ANTI_REVOKE",
    "BURN_AFTER",
    "RECOVER_ENABLED",
    "REPLY_DELAY_MIN",
    "REPLY_DELAY_MAX",
    "MAX_MSG_LENGTH",
    "BAN_DURATION_DEFAULT",
    "MAX_REQUESTS_PER_USER",
    "AUTO_REPLY_TRIGGERS",
    "BACKUP_INTERVAL",
    "GOODNIGHT_TEMPLATE",
    "GREETING_TEMPLATE",
    "MAX_LOG_SIZE",
    "MAX_STICKERS_PER_DAY",
    "POINTS_PER_SIGNUP",
    "SIGNUP_RESET_HOUR",
    "RATE_LIMIT_WINDOW",
})

# 这些名称只用于把自然语言指令路由到 MYSTIC_BROADCAST_CONFIG 的嵌套字段，
# 绝不是合法顶层配置。Dashboard/部署/落盘必须拒绝或清掉顶层副本。
NESTED_CONFIG_PSEUDO_FIELDS = frozenset({
    "MYSTIC_BROADCAST_ENABLED",
    "MYSTIC_HOUR_MORNING",
    "MYSTIC_HOUR_AFTERNOON",
    "MYSTIC_HOUR_EVENING",
})

INVALID_TOP_LEVEL_CONFIG_FIELDS = REMOVED_CONFIG_FIELDS | NESTED_CONFIG_PSEUDO_FIELDS
_SECRET_KEY_SUFFIXES = (
    "_token",
    "_api_key",
    "_apikey",
    "_secret",
    "_password",
    "_password_hash",
    "_credential",
    "_credentials",
    "_private_key",
    "_api_keys",
    "_secrets",
    "_passwords",
)
_SECRET_KEY_NAMES = {
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "password_hash",
    "credential",
    "credentials",
    "private_key",
    "tokens",
    "api_keys",
    "apikeys",
    "secrets",
    "passwords",
}
_ENV_SECRET_OVERRIDES = {
    ("TOKEN",): "TG_TOKEN",
    ("API_KEY",): "DASHSCOPE_KEY",
    ("NSFW_DETECT_CONFIG", "api_key"): "NSFW_DETECT_API_KEY",
    ("SPAM_WATCH_CONFIG", "spamwatch_token"): "SPAMWATCH_TOKEN",
    ("EXCHANGE_API_KEY",): "EXCHANGE_API_KEY",
}


def is_sensitive_config_key(key: object) -> bool:
    """判断配置字段是否承载凭据，不误伤 max_tokens/token_budget 等调优键。"""
    normalized = str(key or "").strip().lower().replace("-", "_")
    return normalized in _SECRET_KEY_NAMES or normalized.endswith(_SECRET_KEY_SUFFIXES)


def redact_sensitive_config(value, replacement="***"):
    """递归复制并脱敏配置，供 API/日志输出使用。"""
    if isinstance(value, dict):
        return {
            key: replacement if is_sensitive_config_key(key)
            else redact_sensitive_config(item, replacement)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_config(item, replacement) for item in value]
    return value


def _blank_sensitive_values(value):
    """递归复制配置并清空凭据值，保留键形状以兼容旧读取方。"""
    if isinstance(value, dict):
        return {
            key: "" if is_sensitive_config_key(key) else _blank_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_blank_sensitive_values(item) for item in value]
    return value


def inject_environment_secrets(cfg: dict | None, environ=None) -> dict:
    """把 .env/进程环境中的凭据注入运行时配置，不写回 config.json。"""
    result = cfg if isinstance(cfg, dict) else {}
    source = os.environ if environ is None else environ
    for path, env_key in _ENV_SECRET_OVERRIDES.items():
        env_value = source.get(env_key, "")
        if not env_value:
            continue
        target = result
        for part in path[:-1]:
            target = _ensure_dict(target, part)
        target[path[-1]] = env_value
    return result


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
    # 新能力默认关闭（v5.39 内容丰富计划）：节气提示注入 greeting prompt
    greeting_cfg["solar_term_hint_enabled"] = bool(
        greeting_cfg.get("solar_term_hint_enabled", False)
    )

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
    # 新能力默认关闭（v5.39 内容丰富计划）：免责尾注 / 塔罗牌阵轮换 / 敏感分流
    mystic_cfg["disclaimer_note_enabled"] = bool(
        mystic_cfg.get("disclaimer_note_enabled", False)
    )
    mystic_cfg["tarot_spread_rotation_enabled"] = bool(
        mystic_cfg.get("tarot_spread_rotation_enabled", False)
    )
    mystic_cfg["private_sensitive_guard_enabled"] = bool(
        mystic_cfg.get("private_sensitive_guard_enabled", False)
    )

    return cfg


def compact_runtime_config(cfg: dict | None) -> dict:
    """压缩为适合落盘的主键结构，避免把兼容别名都写回文件。

    【v5.41.0】落盘前剥离明文凭据（TOKEN/API_KEY）：凭据唯一存 .env，
    运行值由环境变量在启动时注入，写回文件只会造成凭据常驻磁盘。
    """
    cfg = normalize_runtime_config(copy.deepcopy(cfg or {}))
    cfg = _blank_sensitive_values(cfg)

    for key in INVALID_TOP_LEVEL_CONFIG_FIELDS:
        cfg.pop(key, None)

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
