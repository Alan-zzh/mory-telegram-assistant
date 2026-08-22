"""健康检查关键任务簇（自 modules/auto_tasks.py v5.38.69 收敛迁移）。

供 tasks/monitoring/health_check_task.py 与相关测试使用：
- 问候/传统文化栏目时间窗解析（与播报任务共用同一真相源）
- 关键任务清单构建（从真实配置生成，避免硬编码误报/漏报）
"""

from datetime import datetime

from core.logging_util import get_logger
from tasks.support.task_config import get_all_group_ids

logger = get_logger("critical_tasks")


def _parse_hhmm(value, default_hour: int, default_minute: int) -> tuple[int, int]:
    """[Codex] 解析 HH:MM 配置，异常时回落默认时间。"""
    try:
        if isinstance(value, str) and ":" in value:
            hour, minute = value.split(":", 1)
            hour_i = int(hour)
            minute_i = int(minute)
            if 0 <= hour_i <= 23 and 0 <= minute_i <= 59:
                return hour_i, minute_i
        if isinstance(value, int) and 0 <= value <= 23:
            return value, default_minute
    except Exception as e:
        logger.debug(f"时间配置解析失败，使用默认值: {e}")
    return default_hour, default_minute


def _get_greeting_time(config: dict, period: str) -> tuple[int, int]:
    """[Codex] 问候时间读取配置，兼容老键。"""
    cfg = config.get("GREETING_CONFIG", {}) if isinstance(config, dict) else {}
    defaults = {
        "morning": (8, 5, "morning_time", "GREETING_HOUR"),
        "afternoon": (12, 35, "afternoon_time", "AFTERNOON_GREETING_HOUR"),
        "evening": (23, 5, "evening_time", "GOODNIGHT_HOUR"),
    }
    default_hour, default_minute, time_key, legacy_hour_key = defaults.get(period, defaults["morning"])
    if time_key in cfg:
        return _parse_hhmm(cfg.get(time_key), default_hour, default_minute)
    if legacy_hour_key in config:
        return _parse_hhmm(config.get(legacy_hour_key), default_hour, default_minute)
    return default_hour, default_minute


def _is_greeting_enabled(config: dict, period: str) -> bool:
    """[Codex] 早午晚问候分别读取开关，兼容 AUTO_GREETING / AUTO_GOODNIGHT。"""
    cfg = config.get("GREETING_CONFIG", {}) if isinstance(config, dict) else {}
    key_map = {
        "morning": "morning_enabled",
        "afternoon": "afternoon_enabled",
        "evening": "evening_enabled",
    }
    if key_map.get(period) in cfg:
        return bool(cfg.get(key_map[period]))
    if period == "evening":
        return bool(config.get("AUTO_GOODNIGHT", config.get("AUTO_GREETING", False)))
    return bool(config.get("AUTO_GREETING", False))


def _is_greeting_window(now: datetime, config: dict, period: str, window_minute: int = 5) -> bool:
    """[Codex] legacy loop 使用配置时间窗口，不再写死 8/12/23 点。"""
    hour, minute = _get_greeting_time(config, period)
    return now.hour == hour and minute <= now.minute < min(60, minute + window_minute)


def _get_mystic_time(config: dict, period: str) -> tuple[int, int]:
    """legacy 路径读取风水/塔罗栏目时间。"""
    cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    defaults = {
        "morning": (9, 5, "morning_time"),
        "afternoon": (13, 5, "afternoon_time"),
        "evening": (20, 35, "evening_time"),
    }
    default_hour, default_minute, time_key = defaults.get(period, defaults["morning"])
    return _parse_hhmm(cfg.get(time_key), default_hour, default_minute)


def _is_mystic_window(now: datetime, config: dict, period: str, window_minute: int = 5) -> bool:
    """legacy loop 只触发新玄学栏目，不再触发新闻。"""
    hour, minute = _get_mystic_time(config, period)
    return now.hour == hour and minute <= now.minute < min(60, minute + window_minute)


def _deadline_after(hour: int, minute: int, grace_minutes: int) -> tuple[int, int]:
    total = hour * 60 + minute + grace_minutes
    return (total // 60) % 24, total % 60


def _is_deadline_reached(now: datetime, deadline_hour: int, deadline_minute: int) -> bool:
    return (now.hour, now.minute) >= (deadline_hour, deadline_minute)


def _is_mystic_enabled(config: dict) -> bool:
    cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    return bool(cfg.get("enabled", False))


def _is_broadcast_scheduled_for_date(broadcast: dict, today: str) -> bool:
    """按实际 APScheduler 日期约束判断动态播报今天是否应执行。"""
    try:
        day = datetime.strptime(today, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效健康检查日期: {today}") from exc

    day_of_week = broadcast.get("day_of_week")
    if day_of_week is not None:
        weekday_names = {
            "mon": 0, "tue": 1, "wed": 2, "thu": 3,
            "fri": 4, "sat": 5, "sun": 6,
        }
        normalized = weekday_names.get(str(day_of_week).strip().lower())
        if normalized is None:
            try:
                normalized = int(day_of_week)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"无效 day_of_week: {day_of_week}") from exc
        if normalized not in range(7):
            raise ValueError(f"无效 day_of_week: {day_of_week}")
        if day.weekday() != normalized:
            return False

    day_of_month = broadcast.get("day_of_month")
    if day_of_month is not None:
        try:
            normalized_day = int(day_of_month)
            if normalized_day not in range(1, 32):
                raise ValueError(f"无效 day_of_month: {day_of_month}")
            if day.day != normalized_day:
                return False
        except (TypeError, ValueError) as exc:
            raise ValueError(f"无效 day_of_month: {day_of_month}") from exc
    return True


def _build_critical_tasks(config: dict, today: str) -> list[dict]:
    """从真实配置生成健康检查任务，避免硬编码 ID/时间造成误报或漏报。"""
    tasks = []

    for period, desc in (
        ("morning", "早安问候"),
        ("afternoon", "午安问候"),
        ("evening", "晚安问候"),
    ):
        if not _is_greeting_enabled(config, period):
            continue
        hour, minute = _get_greeting_time(config, period)
        grace = 90 if period != "evening" else 40
        deadline_hour, deadline_minute = _deadline_after(hour, minute, grace)
        tasks.append({
            "desc": desc,
            "deadline_hour": deadline_hour,
            "deadline_minute": deadline_minute,
            "keys": [f"greeting_{period}_{today}"],
        })

    if _is_mystic_enabled(config):
        for period, task_key, desc in (
            ("morning", "mystic_morning", "早间今日黄历"),
            ("afternoon", "mystic_afternoon", "午间三张塔罗"),
            ("evening", "mystic_evening", "晚间易经一卦"),
        ):
            hour, minute = _get_mystic_time(config, period)
            deadline_hour, deadline_minute = _deadline_after(hour, minute, 60)
            tasks.append({
                "desc": desc,
                "deadline_hour": deadline_hour,
                "deadline_minute": deadline_minute,
                "keys": [task_key],
            })

    tasks.append({
        "desc": "每日日报",
        "deadline_hour": 10,
        "deadline_minute": 0,
        "keys": ["daily_report"],
    })

    try:
        from modules.scheduled_broadcast import get_broadcast_schedule
        group_ids = get_all_group_ids(config)
        due_broadcasts = [
            bc for bc in get_broadcast_schedule(config)
            if _is_broadcast_scheduled_for_date(bc, today)
        ]
        if due_broadcasts and not group_ids:
            raise ValueError("存在今日已启用的定点播报，但未配置任何管理群")
        for bc in due_broadcasts:
            bc_id = bc.get("id", "")
            if not bc_id:
                continue
            hour = int(bc.get("hour", 0))
            minute = int(bc.get("minute", 0))
            deadline_hour, deadline_minute = _deadline_after(hour, minute, 60)
            keys = [
                f"scheduled_broadcast_{bc_id}_{gid}_{today}"
                for gid in group_ids
            ]
            tasks.append({
                "desc": f"定点播报:{bc_id}",
                "deadline_hour": deadline_hour,
                "deadline_minute": deadline_minute,
                "keys": keys,
            })
    except Exception as e:
        logger.error(f"🏥 [health_check] 动态播报任务生成失败: {e}")
        raise

    return tasks


def _missing_task_keys_today(db, task_keys: list[str]) -> list[str]:
    """返回今天缺失的 task_log key；多群播报逐群检查。"""
    missing = []
    for key in task_keys:
        if not db.is_task_executed_today(key):
            missing.append(key)
    return missing
