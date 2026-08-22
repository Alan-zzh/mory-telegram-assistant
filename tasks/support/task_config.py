"""
tasks/support/task_config.py - 任务相关配置解析

集中管理 auto_tasks 中散落的时间配置解析逻辑，避免各任务模块重复实现。
"""

from typing import Tuple

from core.logging_util import get_logger

logger = get_logger("task_config")


def parse_hhmm(value, default_hour: int, default_minute: int) -> Tuple[int, int]:
    """解析 HH:MM 配置，异常时回落默认时间。"""
    try:
        if isinstance(value, str) and ":" in value:
            hour, minute = value.split(":", 1)
            hour_i = int(hour)
            minute_i = int(minute)
            if 0 <= hour_i <= 23 and 0 <= minute_i <= 59:
                return hour_i, minute_i
        if isinstance(value, int) and 0 <= value <= 23:
            return value, default_minute
    except Exception:
        pass
    return default_hour, default_minute


def get_greeting_time(config: dict, period: str) -> Tuple[int, int]:
    """问候时间读取配置，兼容老键。"""
    cfg = config.get("GREETING_CONFIG", {}) if isinstance(config, dict) else {}
    defaults = {
        "morning": (8, 5, "morning_time", "GREETING_HOUR"),
        "afternoon": (12, 35, "afternoon_time", "AFTERNOON_GREETING_HOUR"),
        "evening": (23, 5, "evening_time", "GOODNIGHT_HOUR"),
        "night": (22, 30, "night_time", None),  # 深夜问候：新功能默认关闭，无 legacy 键
    }
    default_hour, default_minute, time_key, legacy_hour_key = defaults.get(period, defaults["morning"])
    if time_key in cfg:
        return parse_hhmm(cfg.get(time_key), default_hour, default_minute)
    if legacy_hour_key in config:
        return parse_hhmm(config.get(legacy_hour_key), default_hour, default_minute)
    return default_hour, default_minute


def is_greeting_enabled(config: dict, period: str) -> bool:
    """早午晚问候分别读取开关，兼容 AUTO_GREETING / AUTO_GOODNIGHT。"""
    cfg = config.get("GREETING_CONFIG", {}) if isinstance(config, dict) else {}
    key_map = {
        "morning": "morning_enabled",
        "afternoon": "afternoon_enabled",
        "evening": "evening_enabled",
        "night": "night_enabled",
    }
    key = key_map.get(period)
    if key in cfg:
        return bool(cfg.get(key))
    if period == "evening":
        return bool(config.get("AUTO_GOODNIGHT", config.get("AUTO_GREETING", False)))
    if period == "night":
        # 深夜问候是新能力，无 legacy 开关，铁律默认关闭
        return False
    return bool(config.get("AUTO_GREETING", False))


def get_mystic_time(config: dict, period: str) -> Tuple[int, int]:
    """风水/塔罗栏目时间读取新配置，不再继承新闻开关。"""
    cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    defaults = {
        "morning": (9, 5, "morning_time"),
        "afternoon": (13, 5, "afternoon_time"),
        "evening": (20, 35, "evening_time"),
    }
    default_hour, default_minute, time_key = defaults.get(period, defaults["morning"])
    return parse_hhmm(cfg.get(time_key), default_hour, default_minute)


def is_mystic_enabled(config: dict) -> bool:
    """玄学播报是新能力，缺少显式开关时必须保持关闭。"""
    cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    return bool(cfg.get("enabled", False))


def get_all_group_ids(config: dict) -> list:
    """
    获取所有管理群组（GROUP_ID + MANAGED_GROUPS 合并去重）。

    Returns:
        群 ID 列表（int），去重后保留顺序。
    """
    group_ids = []
    gid = config.get("GROUP_ID", 0)
    if gid:
        group_ids.append(gid)
    try:
        mg = config.get("MANAGED_GROUPS", [])
        if isinstance(mg, int):
            mg = [mg]
        if mg:
            for g in mg:
                if g and g not in group_ids:
                    group_ids.append(g)
    except Exception as e:
        # MANAGED_GROUPS 配置畸形时禁止静默缩水：定时任务会只发 GROUP_ID 甚至零群且无告警
        logger.error(f"get_all_group_ids：MANAGED_GROUPS 配置解析失败（返回残缺群列表）：{e}")
    return group_ids
