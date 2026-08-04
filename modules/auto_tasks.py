"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/auto_tasks.py  ·  后台自动任务引擎（APScheduler版）        ║
║                                                                        ║
║  【架构重构 v4.5.0】                                                   ║
║    移除了 while True 阻塞循环，改为 APScheduler 独立 Job。            ║
║    各任务互不干扰，解决了「一个任务卡住导致整点新闻漏发」的问题。      ║
║                                                                        ║
║  功能清单：                                                            ║
║    1. 新闻播报（9:00/13:00/20:30）                                    ║
║    2. 早/午/晚安问候（[Codex] 读取 GREETING_CONFIG 配置时间）          ║
║    3. 叫醒服务（每分钟检查）                                           ║
║    4. 阅后即焚探测（每3分钟一次）                                      ║
║    5. 阅后即焚孤儿清理（每小时一次）                                   ║
║    6. 非活跃问候（默认关闭）                                           ║
║    7. 购物车单次预览提醒（默认关闭）                                   ║
║    8. 每周非事实轻互动（默认关闭）                                     ║
║    9. 数据库备份（每小时一次）                                         ║
║    10. TTL历史数据清理（每小时一次）                                    ║
║    11. 配置保存（仅模型索引变化时）                                     ║
║    12. 频道浏览量更新（每小时）                                        ║
║    13. 每日数据报告（9:10 私聊HTML）  ← v4.2.4                       ║
║    14. 每日塔罗搭讪（15:00 30%概率）← v4.2.5新增                    ║
║                                                                        ║
║  启动方式：start_background(bot, config, db, ai, save_config)         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import random
import glob
import os
import json
import copy
import threading
import html
from typing import Any, Dict
from datetime import datetime, timedelta, timezone
from core.broadcast_formatter import build_greeting_html, build_rich_greeting_html, build_rich_news_html
from core.broadcast_image_card import build_broadcast_image_card
from core.broadcast_image_payload import build_news_image_payload
from core.helpers import can_delete_message, can_orphan_cleanup, get_broadcast_auto_delete_config
from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from core.task_transaction import TaskTransactionManager
from tasks.support.message_templates import MessageTemplates
from core.telebot_compat import send_message_compat, send_photo_compat
from modules.redpacket import check_expired_redpackets


logger = get_logger("auto_tasks")


class _TaskAbort(Exception):
    """任务中止（非异常，但不应确认完成，需释放数据库锁）"""
    def __init__(self, message: str, expected: bool = False, context: dict = None):
        super().__init__(message)
        self.expected = expected
        self.context = context or {}

# 尝试导入 APScheduler（可选依赖，未安装则回退到旧版 while True）
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("⚠️ APScheduler 未安装，将使用旧版 while True 循环")

# 记录上次保存的模型索引，避免重复写文件
_last_saved_model_idx = None

# 当日已推送的新闻标题缓存（防止早中晚重复）
_news_pushed_today = set()
_news_cache_lock = threading.Lock()

_AI_FALLBACK_MARKERS = (
    "脑子刚才短路",
    "刚才走神",
    "网络有点卡",
    "刚刚没反应过来",
    "咨询入口这会儿卡住了",
    "抓不到牌位",
    "我这边没接上你的这段情绪",
    "被路况卡住",
    "暂时没法稳定接上模型",
)

_last_task_run = {}
_task_lock = threading.Lock()

_scheduler_instance = None
_startup_maintenance_thread = None

# 【v5.11.0 可靠性框架】注册任务清单 + abort 历史
_REGISTERED_JOBS = []  # [(job_id, trigger, func_name)]
_ABORT_HISTORY = {}  # {task_name: [(time, reason)]}
_ABORT_HISTORY_LOCK = threading.Lock()
_ABORT_P0_ALERTED = set()  # 已发送 P0 告警的 task_name
_LAST_HEARTBEAT = 0
_LAST_HEARTBEAT_LOCK = threading.Lock()
_WATCHDOG_TIMEOUT_SEC = 900  # 15 分钟

# 【v5.31.2 修复】移除重复的 _CRITICAL_TASKS 定义（原 4 元组格式，已被 line ~3907 的 3 元组定义覆盖）
# 健康检查按配置动态生成任务清单，条目格式为 (task_key, task_desc, deadline_hour, deadline_minute)
# 保留 weekly_report/monthly_report 不在此清单内（它们是周/月报，不适合按小时检查）


def _register_job(scheduler, func, job_id: str, **trigger_kwargs):
    """【v5.11.0】统一的 add_job 包装：自动记录到 _REGISTERED_JOBS 用于启动清单"""
    job = scheduler.add_job(func, id=job_id, max_instances=1, coalesce=True, **trigger_kwargs)
    _REGISTERED_JOBS.append({
        "job_id": job_id,
        "func_name": func.__name__ if hasattr(func, "__name__") else str(func),
        "trigger": trigger_kwargs,
    })
    return job


def _record_abort(task_name: str, reason: str):
    """【v5.11.0】记录任务 abort 原因到 _ABORT_HISTORY，连续 3 次触发 P0 告警"""
    now = int(time.time())
    with _ABORT_HISTORY_LOCK:
        if task_name not in _ABORT_HISTORY:
            _ABORT_HISTORY[task_name] = []
        _ABORT_HISTORY[task_name].append((now, reason))
        # 仅保留最近 10 次
        _ABORT_HISTORY[task_name] = _ABORT_HISTORY[task_name][-10:]
        count = len(_ABORT_HISTORY[task_name])
    logger.warning(f"⚠️ [{task_name}] abort: {reason} (连续 {count} 次)")

    # 连续 3 次 abort → P0 告警
    if count >= 3 and task_name not in _ABORT_P0_ALERTED:
        _ABORT_P0_ALERTED.add(task_name)
        try:
            _fault_reporter.report(
                "任务连续abort",
                f"任务 {task_name} 连续 {count} 次被 abort，最近原因: {reason}",
                "🚨"
            )
        except Exception as e:
            logger.error(f"P0 告警失败: {e}")


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


def _get_news_time(config: dict, period: str) -> tuple[int, int]:
    """[Codex] 新闻播报时间读取配置，兼容旧小时键。"""
    cfg = config.get("NEWS_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    defaults = {
        "morning": (9, 5, "morning_time", "NEWS_HOUR_MORNING"),
        "afternoon": (13, 5, "afternoon_time", "NEWS_HOUR_AFTERNOON"),
        "evening": (20, 35, "evening_time", "NEWS_HOUR_EVENING"),
    }
    default_hour, default_minute, time_key, legacy_hour_key = defaults.get(period, defaults["morning"])
    if time_key in cfg:
        return _parse_hhmm(cfg.get(time_key), default_hour, default_minute)
    if legacy_hour_key in config:
        return _parse_hhmm(config.get(legacy_hour_key), default_hour, default_minute)
    return default_hour, default_minute


def _get_news_source_strategy(config: dict) -> str:
    """[Codex] 新闻源优先级：默认真实源优先，TrendRadar 兜底。"""
    cfg = config.get("NEWS_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
    strategy = str(cfg.get("preferred_source", "real_first")).strip().lower()
    if strategy in {"real_first", "trendradar_first"}:
        return strategy
    return "real_first"


def _is_news_window(now: datetime, config: dict, period: str, window_minute: int = 5) -> bool:
    """[Codex] legacy loop 使用新闻配置时间窗口。"""
    hour, minute = _get_news_time(config, period)
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


def _update_heartbeat():
    """【v5.11.0】更新心跳时间戳"""
    global _LAST_HEARTBEAT
    with _LAST_HEARTBEAT_LOCK:
        _LAST_HEARTBEAT = int(time.time())


def _check_heartbeat() -> bool:
    """【v5.11.0】检查心跳是否超时"""
    with _LAST_HEARTBEAT_LOCK:
        return (int(time.time()) - _LAST_HEARTBEAT) > _WATCHDOG_TIMEOUT_SEC


def _format_zero_data(value, kind: str = "count") -> str:
    """【v5.11.0】0 值显示优化：发帖=0 时显示"暂无"，互动=0% 时显示"—"。

    kind:
        - count: 0 → "暂无"
        - percent: 0.0 → "—"
        - ratio: 0.0 → "—"
    """
    if kind == "count":
        return "暂无" if value == 0 else str(value)
    if kind in ("percent", "ratio"):
        return "—" if value == 0 else f"{value:.1f}"
    return str(value)


def _compute_health_score(rm) -> int:
    """【v5.11.0】健康度评分：5 维度 0-100 分。

    维度：
        1. 任务执行率 (30%)
        2. AI 引擎可用性 (25%)
        3. 数据库完整性 (20%)
        4. 配置一致性 (15%)
        5. 磁盘空间 (10%)
    """
    scores = {}

    # 1. 任务执行率
    try:
        recent_tasks = rm.db.get_recent_task_logs(hours=24) if hasattr(rm.db, 'get_recent_task_logs') else []
        if recent_tasks:
            success_rate = sum(1 for t in recent_tasks if t.get("status") == "success") / len(recent_tasks)
            scores["tasks"] = int(success_rate * 100)
        else:
            scores["tasks"] = 100
    except Exception as e:
        logger.debug(f"任务执行率评分失败: {e}")
        scores["tasks"] = 80

    # 2. AI 引擎可用性
    try:
        if rm.ai and hasattr(rm.ai, "ping"):
            scores["ai"] = 100 if rm.ai.ping() else 50
        else:
            scores["ai"] = 75
    except Exception as e:
        logger.debug(f"AI引擎可用性检查失败: {e}")
        scores["ai"] = 60

    # 3. 数据库完整性
    try:
        integrity = rm.db.check_integrity() if hasattr(rm.db, "check_integrity") else "ok"
        scores["db"] = 100 if integrity == "ok" else 70
    except Exception as e:
        logger.debug(f"数据库完整性检查失败: {e}")
        scores["db"] = 70

    # 4. 配置一致性
    try:
        config_ok = rm.config.get("TOKEN", "") and rm.config.get("ADMIN_ID", 0)
        scores["config"] = 100 if config_ok else 50
    except Exception as e:
        logger.debug(f"配置一致性检查失败: {e}")
        scores["config"] = 70

    # 5. 磁盘空间
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        free_pct = (free / total) * 100
        if free_pct > 20:
            scores["disk"] = 100
        elif free_pct > 10:
            scores["disk"] = 70
        else:
            scores["disk"] = 30
    except Exception as e:
        logger.debug(f"磁盘空间检查失败: {e}")
        scores["disk"] = 80

    weights = {"tasks": 0.30, "ai": 0.25, "db": 0.20, "config": 0.15, "disk": 0.10}
    health_score = sum(scores[k] * weights[k] for k in scores)
    return int(health_score)


def _job_heartbeat(rm):
    """【v5.11.0】每 5 分钟更新心跳"""
    _update_heartbeat()


def _job_proactive_audit(rm):
    """【v5.11.0】每天 03:30 预防性自审计：检查 DB / config / AI / 任务 / 日志 / 磁盘 / 备份"""
    try:
        issues = []

        # 1. DB 完整性
        try:
            if hasattr(rm.db, "check_integrity"):
                result = rm.db.check_integrity()
                if result != "ok":
                    issues.append(f"🔴 [P0] 数据库完整性异常: {result}")
        except Exception as e:
            issues.append(f"🟡 [P1] 数据库检查失败: {e}")

        # 2. 配置一致性
        try:
            example_path = os.path.join(os.path.dirname(__file__), "..", "config.json.example")
            with open(example_path, 'r', encoding='utf-8') as f:
                example = json.load(f)
            missing = [k for k in example.keys() if k not in rm.config and k not in ("TOKEN", "ADMIN_ID")]
            if missing:
                issues.append(f"🔴 [P0] 配置缺失 {len(missing)} 项: {missing[:5]}...")
        except Exception as e:
            issues.append(f"🟡 [P1] 配置检查失败: {e}")

        # 3. AI 模型池
        try:
            if rm.ai and hasattr(rm.ai, "ping"):
                if not rm.ai.ping():
                    issues.append("🔴 [P0] AI 引擎不可用")
        except Exception as e:
            issues.append(f"🟡 [P1] AI 检查失败: {e}")

        # 4. 任务执行率
        try:
            if hasattr(rm.db, "get_recent_task_logs"):
                recent = rm.db.get_recent_task_logs(hours=24)
                if recent:
                    failed = sum(1 for t in recent if t.get("status") == "failed")
                    if failed > 0:
                        issues.append(f"🟡 [P1] 24h 内 {failed} 个任务执行失败")
        except Exception as e:
            logger.debug(f"任务执行率检查失败: {e}")

        # 5. 磁盘空间
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_pct = (free / total) * 100
            if free_pct < 10:
                issues.append(f"🔴 [P0] 磁盘空间不足: {free_pct:.1f}%")
            elif free_pct < 20:
                issues.append(f"🟡 [P1] 磁盘空间偏紧: {free_pct:.1f}%")
        except Exception as e:
            logger.debug(f"磁盘空间检查失败: {e}")

        # 6. 备份文件
        try:
            backup_dir = os.path.join(os.path.dirname(__file__), "..", "backup")
            if not os.path.isdir(backup_dir):
                issues.append("🔴 [P0] 备份目录不存在")
            else:
                backups = sorted(glob.glob(os.path.join(backup_dir, "*.db")), key=os.path.getmtime, reverse=True)
                if not backups:
                    issues.append("🔴 [P0] 备份目录为空")
                else:
                    latest = backups[0]
                    age_hours = (time.time() - os.path.getmtime(latest)) / 3600
                    file_size = os.path.getsize(latest)
                    if age_hours >= 25 or file_size <= 0:
                        issues.append(f"🔴 [P0] 备份异常：最新备份 {age_hours:.0f} 小时前，大小 {file_size} 字节")
        except Exception as e:
            logger.debug(f"备份文件检查失败: {e}")

        # 7. 健康度评分
        health_score = _compute_health_score(rm)
        if health_score < 60:
            issues.append(f"🔴 [P0] 健康度过低: {health_score}")
        elif health_score < 80:
            issues.append(f"🟡 [P1] 健康度偏低: {health_score}")

        # 输出报告
        if not issues:
            report = f"✅ 自审计通过\n健康度: {health_score}/100\n所有维度正常"
        else:
            report = (
                f"📊 自审计报告\n"
                f"健康度: {health_score}/100\n"
                f"━━━━━━━━━━━━━━━━\n"
                + "\n".join(issues)
            )

        admin_id = rm.config.get("ADMIN_ID", 0)
        if admin_id:
            with rm.locked('bot'):
                rm.bot.send_message(admin_id, report)
        logger.info(f"预防性自审计完成: 健康度={health_score} 问题={len(issues)}")
    except Exception as e:
        logger.error(f"预防性自审计失败: {e}")


def _job_evaluate_conversation_quality(rm):
    """[v5.26.0] 每日凌晨 3:00 内容质量评估（LLM-as-a-Judge）

    抽样昨日对话 → 投放 LLM 评估 → 存储评分到 interaction_quality_scores 表。
    采样率/预算/开关均从 config 读取，默认关闭。
    """
    try:
        from core.quality_evaluator import QualityEvaluator
        evaluator = QualityEvaluator(ai=rm.ai, db=rm.db, config=rm.config)
        result = evaluator.run_daily_evaluation()
        logger.info(f"📊 内容质量评估任务完成: {result}")
    except Exception as e:
        logger.error(f"内容质量评估任务失败: {e}")


def _watchdog_check(rm):
    """【v5.11.0】watchdog 线程：检测心跳超时 + 自动重启"""
    while True:
        time.sleep(60)
        if _check_heartbeat():
            try:
                _fault_reporter.report(
                    "心跳超时",
                    f"心跳超时 {_WATCHDOG_TIMEOUT_SEC}s，触发自动重启",
                    "🚨"
                )
            except Exception as e:
                logger.warning(f"心跳超时告警上报失败: {e}")
            logger.critical(f"心跳超时 {_WATCHDOG_TIMEOUT_SEC}s，触发自动重启")
            time.sleep(5)
            os._exit(42)  # systemd Restart=always 会自动拉起


def _start_watchdog(rm):
    """【v5.11.0】启动 watchdog 后台线程"""
    _update_heartbeat()  # 初始化心跳
    t = threading.Thread(target=_watchdog_check, args=(rm,), daemon=True)
    t.start()
    logger.info(f"watchdog 启动：超时阈值={_WATCHDOG_TIMEOUT_SEC}s")


class _TaskGuard:
    """
    【v4.9.1】任务执行守卫 - 并发异常检测与预警

    核心能力：
    1. 记录每次任务调用时间戳，同一任务5分钟内被调用≥2次 → 告警管理员
    2. 记录抢占失败原因，连续失败≥3次 → 告警管理员
    3. 健康检查时审计数据库task_log，检测异常重复记录
    """
    _ALERT_WINDOW_SEC = 300
    _ALERT_THRESHOLD = 2
    _CLAIM_FAIL_THRESHOLD = 3

    def __init__(self):
        self._call_history = {}
        self._claim_fail_count = {}
        self._alerted = set()
        self._lock = threading.Lock()
        self._rm = None

    def bind(self, rm):
        self._rm = rm

    def record_call(self, task_name: str):
        now = int(time.time())
        with self._lock:
            if task_name not in self._call_history:
                self._call_history[task_name] = []
            self._call_history[task_name].append(now)
            self._call_history[task_name] = [
                t for t in self._call_history[task_name]
                if now - t < self._ALERT_WINDOW_SEC
            ]
            count = len(self._call_history[task_name])
            if count >= self._ALERT_THRESHOLD:
                alert_key = f"{task_name}_{now // 60}"
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    logger.warning(
                        f"🚨 [TaskGuard] {task_name} 在{self._ALERT_WINDOW_SEC}秒内被调用{count}次！疑似并发异常"
                    )
                    self._send_alert(
                        f"🚨 <b>并发异常预警</b>\n"
                        f"📋 任务：{task_name}\n"
                        f"⚡ {self._ALERT_WINDOW_SEC}秒内被调用{count}次\n"
                        f"🕐 时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"💡 可能存在并发重复执行，请检查日志"
                    )

    def record_intercept(self, task_name: str, reason: str):
        """【v4.13.2】记录正常拦截（内存锁/数据库锁），不触发告警"""
        with self._lock:
            logger.info(f"🛡️ [TaskGuard] {task_name} 正常拦截（{reason}）")

    def record_claim_fail(self, task_name: str, reason: str):
        with self._lock:
            self._claim_fail_count[task_name] = self._claim_fail_count.get(task_name, 0) + 1
            count = self._claim_fail_count[task_name]
            if count >= self._CLAIM_FAIL_THRESHOLD:
                alert_key = f"claim_{task_name}_{now // 3600}" if (now := int(time.time())) else f"claim_{task_name}"
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    logger.warning(
                        f"🚨 [TaskGuard] {task_name} 连续{count}次抢占失败（{reason}）"
                    )
                    self._send_alert(
                        f"⚠️ <b>任务抢占异常</b>\n"
                        f"📋 任务：{task_name}\n"
                        f"🔒 连续{count}次抢占失败\n"
                        f"📌 原因：{reason}\n"
                        f"🕐 时间：{datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"💡 可能是锁未正确释放，请检查数据库task_log"
                    )
                self._claim_fail_count[task_name] = 0

    def record_claim_ok(self, task_name: str):
        with self._lock:
            self._claim_fail_count.pop(task_name, None)

    def audit_task_log(self, db) -> list:
        anomalies = []
        try:
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            with _db_lock_from_db(db):
                rows = db.conn.execute(
                    "SELECT task_key, COUNT(*) as cnt FROM task_log WHERE exec_date=? GROUP BY task_key HAVING cnt > 1",
                    (today,)
                ).fetchall()
            for task_key, cnt in rows:
                anomalies.append(f"• {task_key}：今日{cnt}条记录（正常应1条）")
                logger.warning(f"🚨 [TaskGuard] 数据库异常：{task_key} 今日有{cnt}条task_log记录")
        except Exception as e:
            logger.warning(f"⚠️ [TaskGuard] 审计task_log失败: {e}")
        return anomalies

    def _send_alert(self, msg: str):
        _fault_reporter.report("任务并发异常", msg, "🚨")


_task_guard = _TaskGuard()


class _FaultReporter:
    """
    【v4.9.2】统一故障通知中心 - 所有故障统一入口，自动Telegram通知+本地兜底

    严重度分级：
    - 🚨 P0(瘫痪)：所有模型失败、数据库损坏、Bot崩溃
    - ⚠️ P1(降级)：层级池不可用、Telegram API异常、任务抢占失败
    - 📋 P2(轻微)：非核心功能故障

    防刷机制：同类故障默认5分钟内不重复通知；AI模型全部失败改为30分钟窗口（持久化到文件，重启不丢失）
    兜底机制：Telegram通知失败时写入本地 fault_alerts.log，下次成功时补发
    """
    _DEDUP_SEC = 300
    _AI_FAIL_DEDUP_SEC = 1800
    _ALERT_FILE = "fault_alerts.log"
    _DEDUP_STATE_FILE = "fault_dedup_state.json"
    _MAX_PENDING = 50

    def __init__(self):
        self._rm = None
        self._last_alert = {}
        self._lock = threading.Lock()
        self._pending = []
        self._load_dedup_state()

    def _load_dedup_state(self):
        """从文件加载去重状态（重启后恢复，防止轰炸）"""
        try:
            if os.path.exists(self._DEDUP_STATE_FILE):
                with open(self._DEDUP_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = int(time.time())
                # 只保留未过期的记录
                keep_sec = max(self._DEDUP_SEC, self._AI_FAIL_DEDUP_SEC)
                self._last_alert = {
                    k: v for k, v in data.items()
                    if now - v < keep_sec
                }
        except Exception as e:
            # 【v5.31.2 修复】加载失败清空去重窗口会导致历史告警重新发送（轰炸），必须 warning
            logger.warning(f"告警去重状态加载失败，去重窗口被清空: {e}")
            self._last_alert = {}

    def _save_dedup_state(self):
        """持久化去重状态到文件"""
        try:
            with open(self._DEDUP_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._last_alert, f)
        except Exception as e:
            # 【v5.31.2 修复】告警去重状态持久化失败会导致重复发送历史告警或丢失去重窗口
            logger.warning(f"告警去重状态持久化失败: {e}")

    def bind(self, rm):
        self._rm = rm
        self._flush_pending()

    def report(self, category: str, detail: str, severity: str = "⚠️", extra: str = ""):
        """
        统一故障上报入口

        Args:
            category: 故障类别（如 "AI模型全部失败", "数据库异常", "Telegram API异常"）
            detail: 故障详情
            severity: 严重度图标 🚨/⚠️/📋
            extra: 额外信息（可选）
        """
        now = int(time.time())
        dedup_key = f"{severity}_{category}"
        dedup_sec = self._AI_FAIL_DEDUP_SEC if category == "AI模型全部失败" else self._DEDUP_SEC
        with self._lock:
            if dedup_key in self._last_alert and now - self._last_alert[dedup_key] < dedup_sec:
                logger.debug(f"[FaultReporter] 去重跳过：{category}")
                return
            self._last_alert[dedup_key] = now
            self._save_dedup_state()  # 持久化，重启不丢失

        ts = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"{severity} <b>{category}</b>\n"
            f"📝 {detail}\n"
        )
        if extra:
            msg += f"📎 {extra}\n"
        msg += f"🕐 {ts}"

        logger.warning(f"[FaultReporter] {severity} {category}: {detail}")

        if not self._send_telegram(msg):
            self._save_local(category, detail, severity, ts)

    def _send_telegram(self, msg: str) -> bool:
        if not self._rm:
            return False
        try:
            admin_id = self._rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                return False
            with self._rm.locked('bot'):
                self._rm.bot.send_message(admin_id, msg, parse_mode="HTML")
            return True
        except Exception as e:
            logger.error(f"[FaultReporter] Telegram通知失败: {e}")
            return False

    def _save_local(self, category: str, detail: str, severity: str, ts: str):
        try:
            line = f"[{ts}] {severity} {category} | {detail}\n"
            with open(self._ALERT_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            self._pending.append(line)
            if len(self._pending) > self._MAX_PENDING:
                self._pending = self._pending[-self._MAX_PENDING:]
            logger.info(f"[FaultReporter] 已写入本地告警文件: {category}")
        except Exception as e:
            logger.error(f"[FaultReporter] 本地告警写入失败: {e}")

    def _flush_pending(self):
        if not self._pending or not self._rm:
            return
        pending = list(self._pending)
        self._pending.clear()
        try:
            admin_id = self._rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                return
            count = len(pending)
            if count > 5:
                summary = (
                    f"📋 <b>历史告警补发（{count}条）</b>\n"
                    + "".join(pending[:5])
                    + f"\n... 及其他{count - 5}条"
                )
            else:
                summary = (
                    f"📋 <b>历史告警补发（{count}条）</b>\n"
                    + "".join(pending)
                )
            with self._rm.locked('bot'):
                self._rm.bot.send_message(admin_id, summary, parse_mode="HTML")
            logger.info(f"[FaultReporter] 补发{count}条历史告警")
        except Exception as e:
            logger.error(f"[FaultReporter] 补发失败，重新入队: {e}")
            self._pending.extend(pending)


_fault_reporter = _FaultReporter()


def report_fault(category: str, detail: str, severity: str = "⚠️", extra: str = ""):
    """全局故障上报函数（供其他模块调用）"""
    _fault_reporter.report(category, detail, severity, extra)


# 时区：VPS默认UTC，强制用北京时间(UTC+8)
_CST = timezone(timedelta(hours=8))


def _handle_task_abort(task_name: str, abort: _TaskAbort, time_desc: str = ""):
    """统一处理任务中止异常，区分预期和非预期中止

    Args:
        task_name: 任务名称
        abort: _TaskAbort 异常对象
        time_desc: 时间描述（如"早间"、"午间"等，可选）
    """
    reason = str(abort)
    prefix = f"{time_desc} " if time_desc else ""
    if abort.expected:
        logger.info(f"ℹ️ [{task_name}] {prefix}任务正常中止：{reason}")
    else:
        logger.warning(f"⚠️ [{task_name}] {prefix}任务异常中止：{reason}")
        try:
            _fault_reporter.report(
                f"{task_name}任务异常中止",
                f"任务：{task_name}\n原因：{reason}\n时间描述：{time_desc or '无'}",
                "⚠️"
            )
        except Exception as e:
            logger.debug(f"告警发送失败: {e}")


def _get_scheduler():
    """获取全局APScheduler实例（供_schedule_auto_delete和_retry_task使用）"""
    return _scheduler_instance

def _try_claim_task(task_name: str, min_interval_sec: int = 7200) -> bool:
    """
    【v4.9.0】内存级快速检查（仅检查，不锁定）

    不设置_last_task_run，改为在_confirm_task_done中设置。
    任务失败后不会被内存锁卡住，重试可以正常进行。

    Returns:
        True表示可以执行，False表示距离上次成功运行太近
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.info(f"⏳ [{task_name}] 内存锁跳过，距上次成功{now-last}秒 < {min_interval_sec}秒")
            return False
        logger.info(f"🔓 [{task_name}] 内存锁通过，距上次成功{now-last}秒 >= {min_interval_sec}秒")
        return True


def _try_claim_and_lock(task_name: str, db, min_interval_sec: int = 7200) -> bool:
    """
    【v4.9.1】原子抢占：内存检查 + 数据库原子锁定一步完成 + TaskGuard监控
    【v4.9.3修复】record_call移到锁成功之后，避免被拦截的调用触发误报告警
    【v5.9.0 DEPRECATED】已被 TaskTransactionManager 替代，保留仅供内部兼容

    解决v4.7.0的"先执行后确认"流程导致的并发重复播报：
    两个线程同时通过_try_claim_task和is_task_executed_today检查，
    都执行了发送，然后_confirm_task_done中第二次被数据库拦截，
    但消息已经发出去了。

    新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)

    关键改进：
    - 数据库claim_task在执行前调用，INSERT OR IGNORE保证原子性
    - 如果任务失败，调用_release_task释放数据库锁，允许重试
    - 内存锁在_confirm_task_done中设置（成功后才设）
    - 【v4.9.1】TaskGuard记录每次调用和抢占结果，异常时自动告警
    - 【v4.9.3】record_call只在真正抢占成功时记录，消除锁拦截导致的误报
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.info(f"⏳ [{task_name}] 内存锁跳过，距上次成功{now-last}秒 < {min_interval_sec}秒")
            _task_guard.record_intercept(task_name, "内存锁拦截")
            return False
    try:
        result = db.claim_task(task_name)
        if not result:
            logger.info(f"🔒 [{task_name}] 数据库锁拦截（今日已执行或被其他线程抢占）")
            _task_guard.record_intercept(task_name, "数据库锁拦截")
            return False
        # 【v4.9.3】只在真正抢占成功时记录，避免被锁拦截的调用触发误报
        _task_guard.record_call(task_name)
        logger.info(f"🔓 [{task_name}] 原子抢占成功")
        _task_guard.record_claim_ok(task_name)
        return True
    except Exception as e:
        logger.warning(f"⚠️ [{task_name}] claim_task异常，放行执行: {e}")
        # 异常情况仍记录调用，因为此时没有锁保护
        _task_guard.record_call(task_name)
        return True


def _release_task(task_name: str, db):
    """
    【v4.9.0】任务失败时释放数据库锁，允许重试
    【v5.9.0 DEPRECATED】已被 TaskTransactionManager 替代，保留仅供内部兼容

    配合_try_claim_and_lock使用：抢占成功后如果执行失败，
    必须释放数据库锁，否则重试会被is_task_executed_today拦截。
    """
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    try:
        with _db_lock_from_db(db):
            db.conn.execute("DELETE FROM task_log WHERE task_key=? AND exec_date=?", (task_name, today))
            db.conn.commit()
        logger.info(f"🔓 [{task_name}] 数据库锁已释放，允许重试")
    except Exception as e:
        logger.warning(f"⚠️ [{task_name}] 释放数据库锁失败: {e}")


def _db_lock_from_db(db):
    """获取数据库模块的_db_lock（用于_release_task）"""
    from core.database import _db_lock as db_lock
    return db_lock


def _confirm_task_done(task_name: str, db, min_interval_sec: int = 7200):
    """
    【v4.9.0】任务成功后确认完成：设置内存锁（数据库锁已在_try_claim_and_lock中设置）
    【v5.9.0 DEPRECATED】已被 TaskTransactionManager 替代，保留仅供内部兼容

    流程演变：
    - v4.7.0前：_try_claim_task(提前锁定) → 执行 → 失败后双重锁卡死
    - v4.7.0：_try_claim_task(仅检查) → 执行 → _confirm_task_done(锁定) → 并发重复播报！
    - v4.9.0：_try_claim_and_lock(原子抢占) → 执行 → _confirm_task_done(设内存锁)
    """
    now = int(time.time())
    with _task_lock:
        _last_task_run[task_name] = now
        logger.info(f"🔒 [{task_name}] 内存锁已设置，时间戳={now}")


def _can_run(task_name: str, min_interval_sec: int = 300) -> bool:
    """
    检查任务是否可以运行（仅检查，不标记）
    【v5.9.0 DEPRECATED】已被 TaskTransactionManager 替代，保留仅供内部兼容
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.debug(f"⏳ 任务{task_name}跳过，距离上次运行{now-last}秒 < {min_interval_sec}秒")
            return False
        return True


def _mark_done(task_name: str):
    """【v5.9.0 DEPRECATED】标记任务为已成功完成，已被 TaskTransactionManager 替代，保留仅供内部兼容"""
    now = int(time.time())
    with _task_lock:
        _last_task_run[task_name] = now


def _clear_news_cache_if_new_day():
    """每日凌晨自动清空新闻去重缓存（防止跨天失效），加锁防竞态"""
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    with _news_cache_lock:
        if not getattr(_clear_news_cache_if_new_day, "last_day", None) == today:
            _news_pushed_today.clear()
            _clear_news_cache_if_new_day.last_day = today
            logger.info(" 新闻去重缓存已按日清空")


def _extract_news_key(line: str) -> str:
    """抽取新闻去重键，尽量忽略序号、来源和热度等包装字符"""
    text = line.strip()
    if not text:
        return ""

    if ". " in text[:4]:
        text = text.split(". ", 1)[-1].strip()

    if text.startswith("【") and "】" in text:
        text = text.split("】", 1)[-1].strip()

    if " 🔥" in text:
        text = text.split(" 🔥", 1)[0].strip()

    return text


def _prepare_news_lines(raw_news: str, source_hint: str = "", limit: int = 10) -> list[str]:
    """整理新闻标题，过滤当天已发送内容，但只在真正发送成功后再写入缓存"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        lines = [l.strip() for l in raw_news.split("\n") if l.strip()]
        unique_lines = []
        for line in lines:
            core = _extract_news_key(line)
            if core and core not in _news_pushed_today:
                unique_lines.append(line)
    if source_hint:
        logger.info(f"📰 {source_hint}: 过滤前{len(lines)}条 → 去重后{len(unique_lines)}条")
    return unique_lines[:limit]


def _remember_news_lines(lines: list[str]):
    """新闻真正发送成功后，再把标题写入当天去重缓存"""
    _clear_news_cache_if_new_day()
    with _news_cache_lock:
        for line in lines:
            core = _extract_news_key(line)
            if core:
                _news_pushed_today.add(core)


def _build_news_ai_mode(time_desc: str, source_name: str) -> str:
    """根据时段和新闻源选择对应的AI播报模式"""
    if source_name == "trendradar":
        mapping = {
            "早间": "trendradar_morning_news",
            "午间": "trendradar_noon_news",
            "晚间": "trendradar_evening_news",
        }
        return mapping.get(time_desc, "trendradar_morning_news")

    mapping = {
        "早间": "news",
        "午间": "afternoon_news",
        "晚间": "evening_news",
    }
    return mapping.get(time_desc, "news")


def _looks_like_ai_fallback(text: str) -> bool:
    """识别 AIEngine 所有模型失败后的聊天兜底，避免当新闻播报发送。"""
    value = (text or "").strip()
    return bool(value) and any(marker in value for marker in _AI_FALLBACK_MARKERS)


def _build_news_without_ai(lines: list[str], time_desc: str) -> str:
    """LLM 不可用时，用真实标题生成保守新闻文案。"""
    cleaned = []
    for line in lines[:5]:
        core = line.split("】", 1)[-1].split("🔥", 1)[0].strip()
        if core:
            cleaned.append(core[:36])
    while len(cleaned) < 5:
        cleaned.append("晚点再补一条更稳的消息")
    observation = f"{time_desc}先看这几条，后续有新进展再跟"
    return "\n".join(cleaned[:5] + [observation])


def _get_preferred_news_lines(time_desc: str, config: dict | None = None) -> tuple[list[str], str]:
    """优先用真实新闻源，失败后再降级到聚合热点。"""
    from core.trendradar_news import fetch_trendradar_news, fetch_real_news

    strategy = _get_news_source_strategy(config or {})
    if strategy == "trendradar_first":
        source_chain = [
            ("trendradar", fetch_trendradar_news, f"{time_desc}新闻-TrendRadar"),
            ("fallback", fetch_real_news, f"{time_desc}新闻-真实新闻源"),
        ]
    else:
        source_chain = [
            ("fallback", fetch_real_news, f"{time_desc}新闻-真实新闻源"),
            ("trendradar", fetch_trendradar_news, f"{time_desc}新闻-TrendRadar"),
        ]

    for source_name, fetcher, source_hint in source_chain:
        raw_news = fetcher() or ""
        lines = _prepare_news_lines(raw_news, source_hint)
        if lines:
            return lines, source_name

    return [], "none"


def _retry_task(rm, task_func, task_name: str, delay_sec: int = 300):
    """5分钟后重试失败的任务，仍失败则通知管理员（使用APScheduler调度，避免线程无法取消）

    【v4.7.0】新流程下不需要清数据库锁，因为_confirm_task_done在任务成功后才写入。
    只需清内存锁即可（虽然新流程下内存锁也不会提前设置，但保留以兼容旧逻辑）。
    """
    logger.info(f"🔄 [{task_name}] 调度重试，{delay_sec}秒后执行")
    def _do_retry(rm_inner):
        with _task_lock:
            _last_task_run.pop(task_name, None)
        try:
            logger.info(f"🔄 [{task_name}] 开始重试执行")
            task_func(rm_inner)
        except Exception as e:
            logger.error(f"❌ [{task_name}] 重试仍失败: {e}")
            _notify_admin_failure(rm_inner, task_name, str(e))

    try:
        if HAS_APSCHEDULER and _get_scheduler():
            run_at = datetime.now(_CST) + timedelta(seconds=delay_sec)
            _get_scheduler().add_job(
                _do_retry, trigger='date', run_date=run_at,
                args=[rm], id=f"retry_{task_name}",
                max_instances=1, misfire_grace_time=300,
                replace_existing=True,
            )
        else:
            t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
            t.start()
    except Exception as e:
        logger.error(f"重试任务调度失败: {e}")
        t = threading.Thread(target=_do_retry, args=(rm,), daemon=True, name=f"Retry-{task_name}")
        t.start()
    logger.info(f"⏰ 已安排{task_name}在{delay_sec}秒后重试")


def _notify_admin_failure(rm, task_name: str, error_msg: str):
    """任务重试仍失败时通知管理员（走_FaultReporter统一通道）"""
    _fault_reporter.report("定时任务失败", f"任务: {task_name}，错误: {error_msg[:200]}", "⚠️")


def _notify_admin_news_failure(rm, news_type: str, error_msg: str = ""):
    """新闻源全部失败时通知管理员（走_FaultReporter统一通道）"""
    detail = f"错误: {error_msg[:200]}" if error_msg else "所有新闻源均无法获取"
    _fault_reporter.report("新闻源故障", f"类型: {news_type}，{detail}", "⚠️")


def _notify_admin_system_failure(rm, failure_type: str, detail: str = "", severity: str = "⚠️"):
    """全局系统故障通知管理员（走_FaultReporter统一通道，保持接口兼容）"""
    _fault_reporter.report(failure_type, detail, severity)


def _send_and_track(rm, chat_id, text, user_msg_id=0, parse_mode=None, disable_web_page_preview=None):
    """发送消息并追踪浏览量（主动消息也入库channel_tracking）"""
    try:
        with rm.locked('bot'):
            sent = send_message_compat(
                rm.bot,
                chat_id,
                text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                link_preview_options={
                    "is_disabled": disable_web_page_preview
                } if disable_web_page_preview is not None else None,
            )
        if sent and hasattr(sent, 'message_id'):
            _schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
            if chat_id < 0:
                rm.db.track_channel_message(chat_id, sent.message_id, "text")
                rm.db.track_bot_message(chat_id, sent.message_id)
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


def _send_greeting(rm, chat_id, text, category: str = "greeting"):
    """[Trae CN v5.12.0] 发送早安/午安/晚安问候，支持"发新删旧"链式互删

    行为：
    1. 读取 BROADCAST_AUTO_DELETE.greeting_chain_delete 配置
    2. 若开启，查询本群上一条 category="greeting" 的消息 → 删除
       - 发午安时自动删早安；发晚安时自动删午安
    3. 发送新问候，入库 broadcast_tracking（category=greeting）
    4. 24H TTL兜底删除（依赖 _schedule_auto_delete）

    Args:
        rm: ResourceManager 实例
        chat_id: 群ID
        text: 消息文本
        category: 类别（统一用 "greeting" 实现互删，不分早/午/晚）

    Returns:
        Message对象 或 None
    """
    auto_cfg = get_broadcast_auto_delete_config(rm.config)

    # [Trae CN] 链式互删：发新问候前先删上一条同类问候
    if auto_cfg["greeting_chain_delete"] and hasattr(rm, "db") and rm.db is not None:
        try:
            last = rm.db.get_last_broadcast(chat_id, "greeting")
            if last and last[0]:
                last_msg_id, last_ts = last
                # 安全删除（不抛错）
                try:
                    if can_delete_message(rm.config):
                        with rm.locked('bot'):
                            rm.bot.delete_message(chat_id, last_msg_id)
                        logger.info(
                            f"🗑️ 链式互删：已删除上一条问候 [{category}] msg={last_msg_id} ts={last_ts}"
                        )
                except Exception as del_err:
                    logger.debug(f"链式互删失败（继续发新问候）: {del_err}")
                # 不论成功失败，都清掉旧追踪
                try:
                    rm.db.delete_broadcast(chat_id, "greeting")
                except Exception as e:
                    logger.debug(f"删除旧问候播报追踪失败: {e}")
        except Exception as e:
            logger.debug(f"链式互删查询失败（继续发新问候）: {e}")

    # 发送新问候
    sent = _send_and_track(rm, chat_id, text, parse_mode="HTML")
    if sent and hasattr(sent, 'message_id') and hasattr(rm, "db") and rm.db is not None:
        try:
            rm.db.track_broadcast(chat_id, "greeting", sent.message_id)
            logger.info(f"📌 问候追踪入库：chat={chat_id} category={category} msg={sent.message_id}")
        except Exception as e:
            logger.debug(f"问候追踪入库失败: {e}")
    return sent


def _schedule_auto_delete(rm, chat_id, message_id, delay_seconds):
    """定时消息24小时无人理自动删除（使用APScheduler调度，避免线程泄漏）"""
    try:
        if HAS_APSCHEDULER:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_seconds)
            _get_scheduler().add_job(
                _do_delete_message, trigger='date', run_date=run_at,
                args=[rm, chat_id, message_id],
                id=f"auto_del_{chat_id}_{message_id}",
                max_instances=1, misfire_grace_time=300,
                replace_existing=False,
            )
        else:
            logger.warning("⚠️ APScheduler不可用，跳过定时删除（依赖孤儿清理机制处理）")
    except Exception as e:
        logger.error(f"定时删除调度失败: {e}")


def _do_delete_message(rm, chat_id, message_id):
    """APScheduler回调：删除指定消息"""
    try:
        if can_delete_message(rm.config):
            with rm.locked('bot'):
                rm.bot.delete_message(chat_id, message_id)
            logger.info(f"🗑️ 定时消息已自动删除: chat={chat_id}, msg={message_id}")
        else:
            logger.info(f"消息删除已禁用，跳过删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"定时消息删除失败（可能已被手动删除）: {e}")


_AUTOMATIC_CTA_MARKERS = (
    "@morychannelbot",
    "@moryselect",
    "自助下单",
    "自助订阅",
    "来找mory",
    "私聊我",
    "找我私聊",
    "戳我",
)


def _sanitize_automatic_broadcast_text(text: str) -> str:
    """移除普通新闻/问候里意外生成的销售或私聊 CTA 行。"""
    if not isinstance(text, str):
        return ""
    safe_lines = [
        line for line in text.splitlines()
        if not any(marker in line.lower() for marker in _AUTOMATIC_CTA_MARKERS)
    ]
    return "\n".join(safe_lines).strip()


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _execute_news_task(rm, task_name: str, time_desc: str):
    """
    执行新闻播报任务的公共函数（富文本排版，不附带成交 CTA）。

    【v5.9.0】使用 TaskTransactionManager 替代手动 _try_claim_and_lock / _release_task / _confirm_task_done
    【v5.11.0】abort 原因记录到 _ABORT_HISTORY，连续 3 次触发 P0 告警
    新闻只承担信息播报，不借新闻强塞预览或下单。
    """
    try:
        with TaskTransactionManager(task_name, rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            gid = rm.config.get("GROUP_ID", 0)
            if gid == 0:
                _record_abort(task_name, "GROUP_ID为0")
                raise _TaskAbort("GROUP_ID为0")

            logger.info(f"📰 触发{time_desc}新闻播报（统一主流程）")
            seed = random.randint(100000, 999999)

            lines, source_name = _get_preferred_news_lines(time_desc, rm.config)
            if not lines:
                logger.warning(f"{time_desc}新闻：所有源均失败，跳过发送")
                _notify_admin_news_failure(rm, f"{time_desc}新闻")
                _record_abort(task_name, "新闻源均失败")
                raise _TaskAbort("新闻源均失败")
            news_input = "\n".join(lines)

            ai_mode = _build_news_ai_mode(time_desc, source_name)
            news = rm.ai.ask(news_input, mode=ai_mode, seed=seed, news_content=news_input)
            if not news or _looks_like_ai_fallback(news):
                logger.warning(f"{time_desc}新闻 AI 生成不可用，使用真实标题兜底排版")
                _notify_admin_system_failure(
                    rm,
                    "新闻AI生成降级",
                    f"类型: {time_desc}新闻，模型不可用，已用真实标题兜底，避免重复重试",
                    "⚠️",
                )
                news = _build_news_without_ai(lines, time_desc)

            if news:
                news = _sanitize_automatic_broadcast_text(news)
                if not news:
                    news = _build_news_without_ai(lines, time_desc)
                # 使用 v1.0 富文本新闻排版（自动 HTML 转义 + emoji 点缀 + 观察行 blockquote）
                rich_news = build_rich_news_html(time_desc, news, source_name=source_name)

                # [v5.38.15] 新闻播报也支持图片卡（全局总闸 + NEWS_BROADCAST_CONFIG.image_card_enabled）
                cfg = rm.config or {}
                global_image_enabled = bool(cfg.get("BROADCAST_IMAGE_CARD_ENABLED", False))
                news_cfg = cfg.get("NEWS_BROADCAST_CONFIG", {}) if isinstance(cfg, dict) else {}
                news_image_enabled = global_image_enabled and bool(news_cfg.get("image_card_enabled", False))
                image_path = ""
                if news_image_enabled:
                    try:
                        image_payload = build_news_image_payload(news, time_desc=time_desc)
                        today = datetime.now(_CST).strftime("%Y%m%d")
                        image_path = build_broadcast_image_card(
                            image_payload,
                            cache_key=f"news_{time_desc}_{today}",
                            cta_pool="news",
                            config=cfg,
                            min_height=1100,
                        ) or ""
                        if image_path and not os.path.isfile(image_path):
                            image_path = ""
                    except Exception as e:
                        logger.warning(f"📰 {time_desc}新闻图片卡生成失败，回退文字: {e}")
                        image_path = ""

                # 新闻不附带销售或私聊按钮。
                if image_path:
                    try:
                        with rm.locked('bot'):
                            sent = send_photo_compat(
                                rm.bot, gid, image_path,
                                caption=None,
                                disable_notification=False,
                            )
                        if sent and hasattr(sent, 'message_id'):
                            _schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                            rm.db.track_channel_message(gid, sent.message_id, "image")
                            rm.db.track_bot_message(gid, sent.message_id)
                            _remember_news_lines(lines)
                            logger.info(f"✅ {time_desc}新闻图片卡已发送（来源: {source_name}）")
                            return
                    except Exception as e:
                        logger.warning(f"📰 {time_desc}新闻图片卡发送失败，回退文字: {e}")

                try:
                    with rm.locked('bot'):
                        sent = send_message_compat(
                            rm.bot, gid, rich_news,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                            link_preview_options={"is_disabled": True},
                        )
                    if sent and hasattr(sent, 'message_id'):
                        _schedule_auto_delete(rm, gid, sent.message_id, 24 * 3600)
                        rm.db.track_channel_message(gid, sent.message_id, "text")
                        rm.db.track_bot_message(gid, sent.message_id)
                        _remember_news_lines(lines)
                        logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}，无成交CTA）")
                        return
                except Exception as e:
                    logger.warning(f"{time_desc}新闻富文本发送失败，降级纯文本: {e}")
                    sent = _send_and_track(rm, gid, news)
                    if sent:
                        _remember_news_lines(lines)
                        logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}，纯文本降级）")
                        return

            _record_abort(task_name, "新闻发送失败")
            raise _TaskAbort("新闻发送失败")
    except _TaskAbort as e:
        _handle_task_abort(task_name, e, time_desc)
    except Exception as e:
        logger.error(f"{time_desc}新闻播报失败：{e}")
        _retry_task(rm, lambda rm: _execute_news_task(rm, task_name, time_desc), task_name)


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _job_mystic_morning(rm):
    """早间今日黄历栏目。"""
    from tasks.broadcast.mystic_broadcast_task import execute_mystic_broadcast_task
    execute_mystic_broadcast_task(rm, "mystic_morning", "morning")


def _job_mystic_afternoon(rm):
    """午间三张塔罗栏目。"""
    from tasks.broadcast.mystic_broadcast_task import execute_mystic_broadcast_task
    execute_mystic_broadcast_task(rm, "mystic_afternoon", "afternoon")


def _job_mystic_evening(rm):
    """晚间易经一卦栏目。"""
    from tasks.broadcast.mystic_broadcast_task import execute_mystic_broadcast_task
    execute_mystic_broadcast_task(rm, "mystic_evening", "evening")


# ── 动态随机话术池（去AI化，与ai_engine人设系统一致）── [TRAE SOLO CN]

# 旧调度路径复用统一话术池，普通问候不导私聊、不附带成交 CTA。
_MORNING_SUFFIXES = MessageTemplates.MORNING_SUFFIXES
_AFTERNOON_SUFFIXES = MessageTemplates.AFTERNOON_SUFFIXES
_EVENING_SUFFIXES = MessageTemplates.EVENING_SUFFIXES

_WAKEUP_FALLBACKS = MessageTemplates.WAKEUP_FALLBACKS

_REACTIVATE_FALLBACKS = MessageTemplates.REACTIVATE_FALLBACKS
_CART_RECOVERY_STAGE_1 = MessageTemplates.CART_RECOVERY_STAGE_1
_CART_RECOVERY_STAGE_2 = MessageTemplates.CART_RECOVERY_STAGE_2
_CART_RECOVERY_STAGE_3 = MessageTemplates.CART_RECOVERY_STAGE_3
_CART_RECOVERY_FALLBACKS = MessageTemplates.CART_RECOVERY_FALLBACKS

# 挽回阶段 → 文案池映射
_CART_RECOVERY_POOLS = {
    0: _CART_RECOVERY_STAGE_1,  # 15分钟 → 傲娇催促
    1: _CART_RECOVERY_STAGE_2,  # 2小时 → 利益诱导
    2: _CART_RECOVERY_STAGE_3,  # 24小时 → 清冷关怀
}

_TAROT_HOOKS = MessageTemplates.TAROT_HOOKS

_LEAK_PREFIXES = MessageTemplates.LEAK_PREFIXES
_WEEKLY_INTERACTION_QUESTIONS = MessageTemplates.WEEKLY_INTERACTION_QUESTIONS


def _get_dynamic_suffix(time_period: str) -> str:
    """根据时段获取随机播报尾语 [TRAE SOLO CN]"""
    if time_period == "morning":
        return random.choice(_MORNING_SUFFIXES)
    elif time_period == "afternoon":
        return random.choice(_AFTERNOON_SUFFIXES)
    elif time_period == "evening":
        return random.choice(_EVENING_SUFFIXES)
    return random.choice(_MORNING_SUFFIXES + _AFTERNOON_SUFFIXES + _EVENING_SUFFIXES)


# AI主体已包含功能引导时的关键词检测 [TRAE SOLO CN]
_SUFFIX_TRIGGER_KEYWORDS = MessageTemplates.SUFFIX_TRIGGER_KEYWORDS


def _needs_suffix(msg: str) -> bool:
    """判断AI生成的播报是否已包含功能引导，需要补suffix则返回True [TRAE SOLO CN]"""
    return not any(kw in msg for kw in _SUFFIX_TRIGGER_KEYWORDS)


_GREETING_FALLBACK_POOL = MessageTemplates.GREETING_FALLBACK_POOL


def _get_fallback_greeting(period: str) -> str:
    """从话术池随机选择问候语（AI 生成失败时的兜底）。"""
    pool = _GREETING_FALLBACK_POOL.get(period, [])
    if pool:
        return random.choice(pool)
    return "你好"


def _get_all_group_ids(config) -> list:
    """【v5.31.0 修复 Bug D】获取所有管理群组（GROUP_ID + MANAGED_GROUPS 合并去重）

    复用 ad_scan 的多群遍历模式，统一 greeting/broadcast 多群支持。
    Returns: 群ID列表（int），去重后保留顺序
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
        logger.debug(f"获取MANAGED_GROUPS失败: {e}")
    return group_ids


def _job_greeting_morning(rm):
    """早安问候 [Codex] 时间和开关读取配置，使用 _send_greeting 支持链式互删

    【v5.31.0 修复】task_key 加日期后缀避免 task_log 残留导致永久死锁；
    多群遍历（GROUP_ID + MANAGED_GROUPS）支持多联排
    """
    try:
        if not _is_greeting_enabled(rm.config, "morning"):
            logger.info("[Codex] 早安问候未开启，跳过")
            return
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with TaskTransactionManager(f"greeting_morning_{today}", rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            group_ids = _get_all_group_ids(rm.config)
            if not group_ids:
                _record_abort("greeting_morning", "无管理群")
                raise _TaskAbort("无管理群")

            seed = random.randint(100000, 999999)
            msg = rm.ai.ask("早安", mode="morning", seed=seed)
            msg = _sanitize_automatic_broadcast_text(msg)
            if not msg:
                # AI 生成失败，使用话术池兜底
                msg = _get_fallback_greeting("morning")
                logger.info("☀️ 早安使用话术池兜底")
            msg = msg.replace("\n", " ").strip()[:250]
            suffix = _get_dynamic_suffix("morning") if _needs_suffix(msg) else ""
            rich = build_rich_greeting_html("morning", msg, suffix.strip())
            sent_any = False
            for gid in group_ids:
                try:
                    sent = _send_greeting(rm, gid, rich, "greeting_morning")
                    if sent:
                        sent_any = True
                        logger.info(f"☀️ 早安已发送到群 {gid}：{msg}")
                except Exception as e:
                    logger.warning(f"☀️ 早安发送到群 {gid} 失败: {e}")
            if not sent_any:
                raise _TaskAbort("早安全部群发送失败")
    except _TaskAbort as e:
        _handle_task_abort("greeting_morning", e)
    except Exception as e:
        logger.error(f"早安问候失败：{e}")
        _retry_task(rm, _job_greeting_morning, "greeting_morning")


def _job_greeting_afternoon(rm):
    """午安问候 [Codex] 时间和开关读取配置，使用 _send_greeting 支持链式互删

    【v5.31.0 修复】task_key 加日期后缀避免 task_log 残留导致永久死锁；
    多群遍历（GROUP_ID + MANAGED_GROUPS）支持多联排
    """
    try:
        if not _is_greeting_enabled(rm.config, "afternoon"):
            logger.info("[Codex] 午安问候未开启，跳过")
            return
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with TaskTransactionManager(f"greeting_afternoon_{today}", rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            group_ids = _get_all_group_ids(rm.config)
            if not group_ids:
                _record_abort("greeting_afternoon", "无管理群")
                raise _TaskAbort("无管理群")

            seed = random.randint(100000, 999999)
            msg = rm.ai.ask("午安", mode="afternoon", seed=seed)
            msg = _sanitize_automatic_broadcast_text(msg)
            if not msg:
                # AI 生成失败，使用话术池兜底
                msg = _get_fallback_greeting("afternoon")
                logger.info("🍃 午安使用话术池兜底")
            msg = msg.replace("\n", " ").strip()[:250]
            suffix = _get_dynamic_suffix("afternoon") if _needs_suffix(msg) else ""
            rich = build_rich_greeting_html("afternoon", msg, suffix.strip())
            sent_any = False
            for gid in group_ids:
                try:
                    sent = _send_greeting(rm, gid, rich, "greeting_afternoon")
                    if sent:
                        sent_any = True
                        logger.info(f"🍃 午安已发送到群 {gid}：{msg}")
                except Exception as e:
                    logger.warning(f"🍃 午安发送到群 {gid} 失败: {e}")
            if not sent_any:
                raise _TaskAbort("午安全部群发送失败")
    except _TaskAbort as e:
        _handle_task_abort("greeting_afternoon", e)
    except Exception as e:
        logger.error(f"午安问候失败：{e}")
        _retry_task(rm, _job_greeting_afternoon, "greeting_afternoon")


def _job_greeting_evening(rm):
    """晚安问候 [Codex] 时间和开关读取配置，使用 _send_greeting 支持链式互删

    【v5.31.0 修复】task_key 加日期后缀避免 task_log 残留导致永久死锁；
    多群遍历（GROUP_ID + MANAGED_GROUPS）支持多联排
    """
    try:
        if not _is_greeting_enabled(rm.config, "evening"):
            logger.info("[Codex] 晚安问候未开启，跳过")
            return
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with TaskTransactionManager(f"greeting_evening_{today}", rm.db, resources=None, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            group_ids = _get_all_group_ids(rm.config)
            if not group_ids:
                _record_abort("greeting_evening", "无管理群")
                raise _TaskAbort("无管理群")

            seed = random.randint(100000, 999999)
            msg = rm.ai.ask("晚安", mode="evening", seed=seed)
            msg = _sanitize_automatic_broadcast_text(msg)
            if not msg:
                # AI 生成失败，使用话术池兜底
                msg = _get_fallback_greeting("evening")
                logger.info("🌙 晚安使用话术池兜底")
            msg = msg.replace("\n", " ").strip()[:250]
            suffix = _get_dynamic_suffix("evening") if _needs_suffix(msg) else ""
            rich = build_rich_greeting_html("evening", msg, suffix.strip())
            sent_any = False
            for gid in group_ids:
                try:
                    sent = _send_greeting(rm, gid, rich, "greeting_evening")
                    if sent:
                        sent_any = True
                        logger.info(f"🌙 晚安已发送到群 {gid}：{msg}")
                except Exception as e:
                    logger.warning(f"🌙 晚安发送到群 {gid} 失败: {e}")
            if not sent_any:
                raise _TaskAbort("晚安全部群发送失败")
    except _TaskAbort as e:
        _handle_task_abort("greeting_evening", e)
    except Exception as e:
        logger.error(f"晚安问候失败：{e}")
        _retry_task(rm, _job_greeting_evening, "greeting_evening")


def _generate_wakeup_message(uid: int, now: datetime, rm) -> str:
    """AI生成个性化叫醒语"""
    seed = uid + int(now.timestamp())
    hour = now.hour

    prompt = f"""你是公开身份的 Mory 小助理。现在是北京时间{hour}点。

给用户生成一条叫醒消息，要求：
1. 30-50字，自然利落，像朋友叫你起床
2. 语气自然，不撒娇、不调情、不销售
3. 只根据当前时间提醒，不虚构天气、行程或生活场景
4. seed={seed}，每次必须不同

禁止：
- 不要太长，控制在50字以内
- 不要声明自己是真人，不要撒娇卖萌、刻意可爱
- 不要重复相同的开头"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="wakeup", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成叫醒话术失败: {e}")

    # 备用文案（使用动态话术池）
    return random.choice(_WAKEUP_FALLBACKS)


def _job_wakeup_check(rm):
    """叫醒服务检查（每分钟）- AI生成个性化叫醒语

    【v5.31.2 修复】锁顺序死锁：
    原持有 locked_multi(['db','bot','config']) 期间调用 _generate_wakeup_message
    (内部 locked('ai'))，锁顺序为 config→ai，与 _execute_news_task/_job_leak 的
    ai→config 形成 AB-BA 死锁，30秒超时打破后两任务都失败。
    修复：分离数据读取与 AI 生成，只在读 db 时持锁，AI 生成+发送不持 db/config 锁。
    """
    try:
        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")

        # 只在读取时持有 db 锁，避免与 ai→config 顺序冲突
        with rm.locked('db'):
            wake_ups = [(uid, wt) for uid, wt in rm.db.get_all_wake_ups() if wt == time_str]

        # AI 生成 + 发送不持有 db/config 锁，避免锁顺序冲突
        for uid, _ in wake_ups:
            try:
                wake_msg = _generate_wakeup_message(uid, now, rm)  # 内部自行获取 ai 锁
                with rm.locked('bot'):
                    rm.bot.send_message(uid, wake_msg)
                logger.info(f"⏰ 叫醒服务：uid={uid}")
            except Exception as e:
                logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"叫醒服务检查失败：{e}")


def _job_burn_probe(rm):
    # DEPRECATED: kept for backward compatibility - 旧版 _legacy_task_loop 仍调用此函数
    pass


def _job_clean_relay_sessions(rm):
    """清理过期的中继会话记录（每小时）

    清理超过24小时的relay_sessions记录，释放存储。
    """
    try:
        db = rm.db
        deleted = db.clean_expired(max_age=86400)
        if deleted > 0:
            logger.info(f"🧹 中继会话清理：删除{deleted}条过期记录")
    except Exception as e:
        logger.warning(f"中继会话清理失败：{e}")


def _job_burn_orphan(rm):
    """阅后即焚清理（每6小时）

    两阶段清理：
    Phase 1: 清理超过30分钟的群聊Bot消息（直接删除Bot回复）
    Phase 2: 探测5-30分钟内的未回复消息，检测用户是否已删原消息

    【v5.12.0变更】：
    1. 每次执行都写入 orphan_cleanup_log 表，Dashboard 可视化
    2. ENABLE_MESSAGE_DELETION=False 时不再静默跳过，发管理员告警（每24h一次）

    【v5.12.4变更】：
    1. 窗口从 24小时 缩到 30分钟（用户决策）
    2. 开关从 ENABLE_MESSAGE_DELETION 改为独立 ORPHAN_CLEANUP_ENABLED
    3. 孤儿清理完全独立于全局消息删除开关
    """
    try:
        # ── Phase 1: 清理超时Bot消息（30分钟窗口，用户决策）──
        logger.info("🔍 [Phase1] 检查超时Bot消息（30分钟窗口）...")
        # [v5.12.4] get_orphan_messages 默认窗口改为 1800（30分钟），不再传 86400
        orphans = rm.db.get_orphan_messages()
        active_messages = []
        if hasattr(rm.db, "get_expired_channel_messages"):
            try:
                active_messages = rm.db.get_expired_channel_messages()
            except Exception as active_err:
                logger.warning(f"主动播报追踪查询失败，继续清理reply_tracking: {active_err}")
        pending = {}
        for bot_mid, cid, user_mid in orphans:
            pending[(int(cid), int(bot_mid))] = (int(bot_mid), int(cid), int(user_mid))
        for bot_mid, cid, user_mid in active_messages:
            pending.setdefault((int(cid), int(bot_mid)), (int(bot_mid), int(cid), int(user_mid)))
        targets = list(pending.values())

        if targets:
            # [v5.12.4] 改用独立开关 ORPHAN_CLEANUP_ENABLED（默认 true），不再依赖 ENABLE_MESSAGE_DELETION
            if can_orphan_cleanup(rm.config):
                logger.info(
                    f"🗑️ 发现{len(targets)}条超时Bot消息（>30分钟），"
                    f"reply={len(orphans)} active={len(active_messages)}，开始清理..."
                )
                success_count = 0
                fail_count = 0
                for bot_mid, cid, user_mid in targets:
                    try:
                        with rm.locked('bot'):
                            rm.bot.delete_message(cid, int(bot_mid))
                        success_count += 1
                    except Exception as del_err:
                        fail_count += 1
                        logger.debug(f"  删除失败：bot_mid={bot_mid}, err={del_err}")
                    if hasattr(rm.db, "delete_bot_message_records"):
                        rm.db.delete_bot_message_records(cid, bot_mid)
                    else:
                        rm.db.delete_tracked(bot_mid, cid)
                logger.info(f"✅ Phase1完成：成功{success_count}条，失败{fail_count}条")
                # [Trae CN v5.12.0] 写入 orphan_cleanup_log
                try:
                    rm.db.log_orphan_cleanup(
                        found_count=len(targets),
                        deleted_count=success_count,
                        skipped_count=fail_count,
                        trigger="scheduled",
                    )
                except Exception as log_err:
                    logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")
            else:
                # [v5.12.4] 改用独立开关告警（不依赖 ENABLE_MESSAGE_DELETION）
                _handle_orphan_disabled_alert(rm, len(targets))
                logger.info(f"[孤儿清理] ORPHAN_CLEANUP_ENABLED=False, 跳过删除{len(targets)}条孤儿消息")
                # [TRAE SOLO CN v5.12.3] 修复：开关关闭时不删追踪记录，保留孤儿信息以便后续开启开关后能清理
                # 之前的逻辑会删除追踪记录，导致即使后续开启开关也无法再找到这些孤儿消息
                # [Trae CN v5.12.0] 写入 orphan_cleanup_log 标记 skipped
                try:
                    rm.db.log_orphan_cleanup(
                        found_count=len(targets),
                        deleted_count=0,
                        skipped_count=len(targets),
                        error="ORPHAN_CLEANUP_ENABLED=False",
                        trigger="scheduled",
                    )
                except Exception as log_err:
                    logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")
        else:
            logger.info("✅ Phase1：无超时Bot消息")
            # [Trae CN v5.12.0] 无孤儿时也写一条空运行日志
            try:
                rm.db.log_orphan_cleanup(
                    found_count=0, deleted_count=0, skipped_count=0,
                    trigger="scheduled",
                )
            except Exception as log_err:
                logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")

        # ── Phase 2: 探测用户是否删了原消息 ──
        # 【v4.5.35修复】Phase2 forward探测已废弃，原因：
        # 1. forward_message探测会触发Telegram 429限流
        # 2. 用户删原消息后Bot回复变成"回复了一条不存在消息"，不影响功能
        # 3. Phase1的30分钟TTL清理已足够处理孤儿消息
        # 4. 保留Phase1清理，Phase2改为仅记录日志不执行探测
        logger.info("✅ [Phase2] 已跳过forward探测（v4.5.35废弃），依赖Phase1 TTL清理")

        # ── Phase 3: [Bug-03 修复] channel_tracking 孤儿兜底清扫 ──
        # Phase1 通过 get_expired_channel_messages + delete_bot_message_records 清理，
        # 但当查询失败、LIMIT 截断或消息已被 Telegram 删除时，channel_tracking 表仍会残留。
        # 这里按 posted_at 时间戳批量删除超过 47 小时的孤儿记录，作为兜底。
        try:
            if hasattr(rm.db, "cleanup_channel_tracking_orphan"):
                deleted_ct = rm.db.cleanup_channel_tracking_orphan(max_age_hours=47)
                if deleted_ct > 0:
                    logger.info(f"🧹 [Phase3] channel_tracking 兜底清理：{deleted_ct} 条孤儿记录")
        except Exception as ct_err:
            logger.warning(f"🧹 [Phase3] channel_tracking 兜底清理失败: {ct_err}")

    except Exception as e:
        logger.error(f"❌ 阅后即焚孤儿清理失败：{e}", exc_info=True)
        # [Trae CN v5.12.0] 失败时也写日志
        try:
            rm.db.log_orphan_cleanup(
                found_count=0, deleted_count=0, skipped_count=0,
                error=str(e)[:200], trigger="scheduled",
            )
        except Exception as e:
            logger.debug(f"记录孤儿清理日志失败: {e}")


# [Trae CN v5.12.0] 孤儿清理告警状态（模块级缓存，防刷屏）
_orphan_disabled_alert_state = {"last_alert_ts": 0}
_ORPHAN_DISABLED_ALERT_INTERVAL = 86400  # 24小时一次


def _handle_orphan_disabled_alert(rm, orphan_count: int):
    """[Trae CN v5.12.0] ENABLE_MESSAGE_DELETION=False 时通知管理员（每24h一次）

    之前逻辑：静默跳过，用户在群里看到的孤儿消息永远没删也无处查
    改造后：日志告警 + 管理员私聊（24h内不重复告警）
    """
    now_ts = int(time.time())
    last_ts = _orphan_disabled_alert_state["last_alert_ts"]

    logger.warning(
        f"⚠️ ENABLE_MESSAGE_DELETION=False, {orphan_count} 条孤儿堆积待清理"
    )

    if now_ts - last_ts < _ORPHAN_DISABLED_ALERT_INTERVAL:
        return  # 24h 内不重复告警

    admin_id = rm.config.get("ADMIN_ID", 0)
    if not admin_id:
        return  # 没配置管理员就只写日志

    try:
        alert_msg = (
            f"⚠️ <b>孤儿消息清理告警</b>\n\n"
            f"当前 <code>ENABLE_MESSAGE_DELETION=False</code>，"
            f"本次发现 <b>{orphan_count}</b> 条超时孤儿无法被删除。\n\n"
            f"开启方式：\n"
            f"1. Dashboard → 设置 → 消息管理 → 启用消息删除\n"
            f"2. 或修改 config.json: <code>\"ENABLE_MESSAGE_DELETION\": true</code>\n\n"
            f"本告警每 24 小时最多发送一次。"
        )
        with rm.locked('bot'):
            rm.bot.send_message(admin_id, alert_msg, parse_mode="HTML")
        _orphan_disabled_alert_state["last_alert_ts"] = now_ts
        logger.info(f"📨 孤儿清理告警已发管理员 admin_id={admin_id}")
    except Exception as e:
        logger.error(f"孤儿清理告警发送失败: {e}")


_REACTIVATE_FORBIDDEN_MARKERS = (
    "@", "http", "下单", "购买", "订阅", "预览", "价格", "福利", "优惠", "名额",
    "私聊", "定制", "回复我", "回我", "吃醋", "别人", "忘了我", "亏欠", "陪你",
    "刚醒", "刚洗", "咖啡", "沙发", "窗外", "被窝",
)
_CART_FORBIDDEN_MARKERS = (
    "@morychannelbot", "@moryfansbot", "http", "私聊", "定制", "下单", "订阅",
    "价格", "福利", "优惠", "名额", "限时", "最后", "错过", "稀缺", "大家都",
    "别人都", "刚醒", "刚洗", "咖啡", "沙发", "窗外", "被窝",
)


def _is_safe_reactivate_message(value) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return 10 <= len(text) <= 70 and not any(
        marker in text.lower() for marker in _REACTIVATE_FORBIDDEN_MARKERS
    )


def _is_safe_cart_recovery_message(value) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    lowered = text.lower()
    return (
        10 <= len(text) <= 90
        and lowered.count("@moryselect") == 1
        and "@" not in lowered.replace("@moryselect", "")
        and not any(marker in lowered for marker in _CART_FORBIDDEN_MARKERS)
    )


def _generate_reactivate_message(uid: int, rm) -> str:
    """生成一次中性、无销售的非活跃用户问候。"""
    seed = uid + int(time.time()) // 86400  # 每天固定

    prompt = f"""你是公开身份的 Mory 小助理。
给一位最近没有活跃的用户写一条可忽略的中性问候。

要求：
1. 20-45字，自然、简短、不要求回复
2. 只表达关心，不谈购买、预览、福利或价格
3. 不吃醋、不撒娇、不制造亏欠感，不假装有亲密关系
4. 不含任何入口、CTA、销售、定制、私聊或关系施压
5. seed={seed}

禁止：
- 不提具体未活跃天数
- 不声称自己是真人，不虚构生活场景"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="reactivate", seed=seed)
        if _is_safe_reactivate_message(msg):
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成挽回话术失败: {e}")

    # 备用文案（使用动态话术池）
    return random.choice(_REACTIVATE_FALLBACKS)


def _job_reactivate(rm):
    """非活跃用户问候（默认关闭）。"""
    try:
        cfg = rm.config.get("REACTIVATE_CONFIG", {})
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            logger.info("非活跃用户问候未开启，跳过")
            return
        # 高频任务：每小时一个窗口，避免 task_log UNIQUE 索引拦截
        _window = datetime.now(_CST).strftime("%Y-%m-%d_%H")
        task_key = f"reactivate_{_window}"
        with TaskTransactionManager(task_key, rm.db, resources=None, min_interval_sec=3600) as tx:
            if not tx.claimed:
                return
            ts = int(time.time())
            three_days_ago = ts - 259200

            inactive = rm.db.get_inactive_users(three_days_ago, rm.config.get("ADMIN_ID", 0))
            if not inactive:
                logger.info("非活跃用户问候本轮无候选，正常跳过")
                return

            sent_count = 0
            max_per_run = max(0, min(int(cfg.get("max_per_run", 3)), 10))
            sample_rate = max(0.0, min(float(cfg.get("sample_rate", 0.25)), 1.0))
            for uid, _name in inactive[:max_per_run]:
                if random.random() < sample_rate:
                    try:
                        reactivate_msg = _generate_reactivate_message(uid, rm)
                        with rm.locked('bot'):
                            rm.bot.send_message(uid, reactivate_msg)
                        rm.db.reset_last_active(uid)
                        sent_count += 1
                        logger.info(f"💌 非活跃用户问候：{uid}")
                    except Exception as e:
                        err_str = str(e).lower()
                        if "chat not found" in err_str or "bot was blocked" in err_str or "forbidden" in err_str:
                            rm.db.delete_user(uid)
                            logger.debug(f"非活跃用户问候跳过无效用户 uid={uid}（已清理）")
                        else:
                            logger.warning(f"非活跃用户问候发送失败 uid={uid}：{e}")
            if sent_count == 0:
                raise _TaskAbort("无发送目标", expected=True)
    except _TaskAbort as e:
        _handle_task_abort("reactivate", e)
    except Exception as e:
        logger.error(f"非活跃用户问候失败：{e}")


def _generate_cart_recovery_message(uid: int, rm, stage: int = 0) -> str:
    """生成一次温和的预览提醒；stage 仅用于兼容旧数据。"""
    seed = uid + int(time.time()) // 43200  # 每半天固定

    prompt = f"""你是公开身份的 Mory 小助理。
用户之前表达过了解意向。写一条一次性的温和提醒：
1. 只引导先去 @moryselect 看当前预览
2. 25-55字，明确由用户自行判断，不催促
3. 不给价格、福利、名额、规格或其他未经证实信息
4. 不导私聊、不直接导下单，不制造稀缺、后悔、亏欠或亲密关系
5. seed={seed}
只输出消息正文。"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="cart_recovery", seed=seed)
        if _is_safe_cart_recovery_message(msg):
            return msg.strip()
    except Exception as e:
        logger.debug(f"AI生成购物车挽回话术失败 stage={stage}: {e}")

    # 按阶段 fallback 到对应文案池
    pool = _CART_RECOVERY_POOLS.get(stage, _CART_RECOVERY_FALLBACKS)
    return random.choice(pool)


def _job_cart_recovery(rm):
    """购物车单次预览提醒（默认关闭，成功后立即 cancel）。"""
    try:
        cfg = rm.config.get("CART_RECOVERY_CONFIG", {})
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            logger.info("购物车召回未开启，跳过")
            return
        # 高频任务：每 5 分钟一个窗口，避免 task_log UNIQUE 索引拦截
        _window = datetime.now(_CST).strftime("%Y-%m-%d_%H%M")
        task_key = f"cart_recovery_{_window}"
        with TaskTransactionManager(task_key, rm.db, resources=None,
                                    min_interval_sec=300) as tx:  # 5分钟间隔
            if not tx.claimed:
                return

            sent_count = 0
            max_per_round = max(0, min(int(cfg.get("max_per_round", 10)), 20))
            pending = rm.db.get_pending_cart_recoveries(limit=max_per_round)
            if not pending:
                logger.info("🛒 购物车挽回本轮无可私聊候选，正常跳过")
                return

            for uid, stage in pending:
                if sent_count >= max_per_round:
                    break

                try:
                    # 生成对应阶段的挽回消息
                    cart_msg = _generate_cart_recovery_message(uid, rm, stage)
                    with rm.locked('bot'):
                        rm.bot.send_message(uid, cart_msg)
                    sent_count += 1

                    rm.db.cancel_cart_recovery(uid)
                    logger.info(f"🛒 购物车单次预览提醒完成并取消: uid={uid} old_stage={stage}")

                except Exception as e:
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in (
                        "chat not found", "bot was blocked", "forbidden",
                        "bot was kicked", "user is deactivated"
                    )):
                        rm.db.delete_user(uid)
                        rm.db.cancel_cart_recovery(uid)
                        logger.debug(f"💔 购物车挽回跳过无效用户 uid={uid}（已清理）")
                    else:
                        logger.warning(f"购物车挽回发送失败 uid={uid} stage={stage}: {e}")

            if sent_count == 0:
                raise _TaskAbort("无发送目标", expected=True)
            else:
                logger.info(f"🛒 购物车挽回本轮发送 {sent_count} 条")

    except _TaskAbort as e:
        _handle_task_abort("cart_recovery", e)
    except Exception as e:
        logger.error(f"购物车挽回失败：{e}")


def _job_leak(rm):
    """每周非事实互动（默认关闭，不编造 Mory 生活信息）。"""
    try:
        cfg = rm.config.get("LEAK_CONFIG", {})
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            logger.info("每周轻互动未开启，跳过")
            return
        with TaskTransactionManager("leak", rm.db, resources=None, min_interval_sec=86400) as tx:
            if not tx.claimed:
                return
            now = datetime.now(_CST)
            current_week = now.isocalendar()[1]

            gid = rm.config.get("GROUP_ID", 0)
            last_leak_week = rm.config.get("_LAST_LEAK_WEEK", -1)

            if gid == 0 or current_week == last_leak_week or now.weekday() < 2:
                raise _TaskAbort("条件不满足", expected=True)

            # 只使用已审阅的非事实问题池，不让模型编造生活信息。
            leak = random.choice(_WEEKLY_INTERACTION_QUESTIONS)

            if leak:
                try:
                    leak_prefix = random.choice(_LEAK_PREFIXES)
                    sent = _send_and_track(rm, gid, f"{leak_prefix}{leak}")
                    if sent:
                        rm.config["_LAST_LEAK_WEEK"] = current_week
                        rm.save_config_fn()
                        logger.info(f"每周轻互动触发(周{current_week})：{leak[:30]}")
                        return
                except Exception as e:
                    logger.warning(f"每周轻互动发送失败：{e}")
            raise _TaskAbort("每周轻互动发送失败")
    except _TaskAbort as e:
        _handle_task_abort("leak", e)
    except Exception as e:
        logger.error(f"每周轻互动失败：{e}")
        _retry_task(rm, _job_leak, "leak")


def _job_backup(rm):
    """数据库备份（每小时）。

    【修复v21.47】移除外层锁，利用SQLite自带的WAL热备机制。
    SQLite的.backup() API本身就是为不锁死业务而设计的，外层加锁反而会导致
    备份期间所有消息处理被阻塞（几秒到十几秒的卡顿）。
    """
    try:
        # 直接备份，不阻塞主业务
        _do_backup(rm.db.db_file)
    except Exception as e:
        logger.error(f"数据库备份失败：{e}")


def _job_ttl_cleanup(rm):
    """TTL历史数据清理（每小时）+ 内存字典定期清理"""
    try:
        ts = int(time.time())
        cutoff = ts - 7 * 86400
        deleted_track, deleted_spam, deleted_puzzle = rm.db.cleanup_old_records(cutoff)
        if deleted_track or deleted_spam or deleted_puzzle:
            logger.info(f"🧹 TTL清理: 追踪{deleted_track}条/垃圾{deleted_spam}条/谜题{deleted_puzzle}条")
        rm.db.cleanup_old_task_log()
    except Exception as e:
        logger.error(f"TTL清理失败：{e}")
    try:
        from core.message_dispatcher import _cleanup_conv_tracker, _cleanup_radar_cooldown
        _cleanup_conv_tracker()
        _cleanup_radar_cooldown()
    except Exception as e:
        logger.debug(f"内存字典清理跳过：{e}")
    # 【v5.31.2 修复】注册 antiflood + edit_detector 清理函数（原定义但从未调用导致内存泄漏）
    try:
        from modules.antiflood import cleanup_flood_cache
        cleanup_flood_cache(max_age=300)
    except Exception as e:
        logger.debug(f"刷屏缓存清理跳过：{e}")
    try:
        from modules.edit_detector import cleanup_old_snapshots
        cleanup_old_snapshots(max_age=86400)
    except Exception as e:
        logger.debug(f"编辑快照清理跳过：{e}")


def _job_save_config(rm):
    """配置保存（仅模型索引变化时）"""
    global _last_saved_model_idx
    try:
        with rm.locked('config'):
            current_idx = rm.config.get("CURRENT_MODEL_INDEX", 0)
        if _last_saved_model_idx is None or _last_saved_model_idx != current_idx:
            with rm.locked('config'):
                rm.save_config_fn()
            _last_saved_model_idx = current_idx
    except Exception as e:
        logger.error(f"配置保存失败：{e}")


def _job_channel_views(rm):
    """【v4.9.5】频道/群成员数统计 + 校准 + 频道内容同步"""
    try:
        gid = rm.config.get("GROUP_ID", 0)

        if gid:
            try:
                with rm.locked('bot'):
                    member_count = rm.bot.get_chat_member_count(gid)
                rm.db.update_group_total_members(member_count, gid)
                rm.db.calibrate_group_stats(gid, member_count)
                logger.info(f"👥 群成员数更新: {member_count}")
            except Exception as e:
                logger.debug(f"群成员数获取失败: {e}")

        channel_ids = rm.config.get("CHANNEL_IDS", [])
        if channel_ids:
            _update_channel_member_counts(rm, channel_ids)
            # 【v4.9.7废弃】_sync_channel_posts 已被 channel_post_handler 替代
            # _sync_channel_posts(rm, channel_ids)

        logger.info("✅ 成员数统计任务完成")
    except Exception as e:
        logger.error(f"成员数统计失败：{e}")


def _job_check_expired_redpackets(rm):
    """检查过期红包，退回未领取积分"""
    try:
        check_expired_redpackets(rm.bot, rm.config, rm.db)
    except Exception as e:
        logger.error(f"红包过期检查失败：{e}")


def _job_faq_distill(rm):
    """FAQ蒸馏（每日）- 从用户问题中提取高频问题生成FAQ候选

    扫描最近7天的用户问题，按归一化文本聚合，
    频次>=min_frequency的组创建FAQ候选，通知管理员审核。
    """
    try:
        # 检查FAQ追踪功能是否启用
        if not rm.config.get("FAQ_TRACKING_ENABLED", False):
            return

        min_frequency = rm.config.get("FAQ_MIN_FREQUENCY", 3)

        with TaskTransactionManager("faq_distill", rm.db, min_interval_sec=86400) as tx:
            if not tx.claimed:
                return

            count = rm.db.distill_candidates(min_frequency=min_frequency, days=7)

            if count > 0:
                logger.info(f"📋 FAQ蒸馏完成：发现 {count} 个新高频问题候选")
                # 通知管理员审核
                _fault_reporter.report(
                    "FAQ蒸馏",
                    f"发现 {count} 个新高频问题候选，请到Dashboard审核",
                    "📋",
                )
            else:
                logger.info("📋 FAQ蒸馏完成：无新高频问题候选")
                raise _TaskAbort("无新高频问题候选")
    except _TaskAbort as e:
        _handle_task_abort("faq_distill", e)
    except Exception as e:
        logger.error(f"FAQ蒸馏失败：{e}")
        _fault_reporter.report("FAQ蒸馏失败", str(e)[:200], "⚠️")


def _update_channel_member_counts(rm, channel_ids: list):
    """获取多频道成员数并写入数据库 + 记录快照"""
    snapshot_date = datetime.now(_CST).strftime("%Y-%m-%d-%H")
    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            with rm.locked('bot'):
                count = rm.bot.get_chat_member_count(cid)
            rm.db.update_group_total_members(count, cid)
            rm.db.record_channel_member_snapshot(cid, count, snapshot_date)
            logger.info(f"📊 频道成员数: {cname}={count}")
        except Exception as e:
            logger.debug(f"频道成员数获取失败: {cname} err={e}")


def _refresh_channel_post_views(rm):
    """【v4.9.7新增】定时刷新频道帖子浏览量
    每小时对每个频道最近10条帖子，通过 forwardMessage 获取最新 views
    """
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    admin_id = rm.config.get("ADMIN_ID", 0)
    if not channel_ids or not admin_id:
        return

    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            recent_posts = rm.db.get_channel_recent_posts(cid, limit=10)
            if not recent_posts:
                continue
            for post in recent_posts:
                msg_id = post["message_id"]
                try:
                    # forwardMessage 到管理员私聊获取最新 views
                    with rm.locked('bot'):
                        fwd = rm.bot.forward_message(admin_id, cid, msg_id)
                        # 获取最新浏览量
                        new_views = getattr(fwd, 'views', 0) or 0
                        new_forwards = getattr(fwd, 'forward_count', 0) or 0
                        # 立即删除转发消息（受全局开关控制）
                        if can_delete_message(rm.config):
                            try:
                                rm.bot.delete_message(admin_id, fwd.message_id)
                            except Exception as e:
                                logger.debug(f"删除转发消息失败: {e}")
                    # 更新数据库
                    if new_views > 0:
                        rm.db.update_channel_post_views(cid, msg_id, new_views, new_forwards)
                    # 限流保护：每条帖间隔1秒
                    time.sleep(1)
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Too Many Requests" in err_str:
                        logger.warning(f"⚠️ 频道浏览量刷新遇429限流，停止: {cname}")
                        return  # 遇限流立即停止整个任务
                    logger.debug(f"频道帖子刷新失败: {cname} msg={msg_id} err={e}")
            logger.info(f"📺 频道浏览量刷新完成: {cname} {len(recent_posts)}条")
        except Exception as e:
            logger.debug(f"频道浏览量刷新异常: {cname} err={e}")


def _job_daily_report(rm):
    """【v5.9.0】每日数据报告 - 使用 TaskTransactionManager"""
    try:
        with TaskTransactionManager("daily_report", rm.db, min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            admin_id = rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                raise _TaskAbort("ADMIN_ID为0")

            now = datetime.now(_CST)
            today = now.strftime("%Y-%m-%d")
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            gid = rm.config.get("GROUP_ID", 0)

            def trend(cur, prev):
                if cur > prev: return "📈"
                if cur < prev: return "📉"
                return "➖"

            _send_daily_group_report(rm, admin_id, today, yesterday, gid, trend)
            _send_daily_channel_report(rm, admin_id, today, trend)

            logger.info(f"✅ 每日数据报告已发送（群+频道）")
    except _TaskAbort as e:
        _handle_task_abort("daily_report", e)
    except Exception as e:
        logger.error(f"每日数据报告失败：{e}")
        _retry_task(rm, _job_daily_report, "daily_report")


def _send_daily_group_report(rm, admin_id: int, today: str, yesterday: str, gid: int, trend_fn):
    """【Codex】群数据日报：原始数据优先，分析后置，不做主观裁判。"""
    token = rm.config.get("TOKEN", "")
    api_data = None
    api_yest_data = None
    use_api = False

    if token and gid:
        try:
            # 【v5.11.0】预留：未来接入 getChatStatistics API
            # api_data = rm.bot.getChatStatistics(chat_id=gid) if has_perm else None
            api_data = None
            if api_data:
                use_api = True
                logger.info(f"📊 群日报使用API数据")
        except Exception as e:
            logger.debug(f"getChatStatistics群失败: {e}")

    group_stats_today = rm.db.get_group_stats_by_date(today)
    group_stats_yesterday = rm.db.get_group_stats_by_date(yesterday)

    joined_today_db = left_today_db = net_today_db = 0
    for row in group_stats_today:
        if len(row) >= 6:
            joined_today_db += row[2] or 0
            left_today_db += row[3] or 0
            net_today_db += row[4] or 0

    joined_yest_db = left_yest_db = net_yest_db = 0
    for row in group_stats_yesterday:
        if len(row) >= 6:
            joined_yest_db += row[2] or 0
            left_yest_db += row[3] or 0
            net_yest_db += row[4] or 0

    if use_api and api_data:
        joined_today = max(api_data.get("growth_today", 0), 0)
        net_today = api_data.get("growth_today", 0)
        left_today = max(-net_today, 0) if net_today < 0 else 0
        total_members = api_data.get("current_count", 0)
        active_today = api_data.get("interactions_today", 0)
        msgs_today = api_data.get("messages_today", 0)
        if joined_today == 0 and left_today == 0 and net_today == 0 and (joined_today_db or left_today_db):
            joined_today = joined_today_db
            left_today = left_today_db
            net_today = net_today_db
            logger.info(f"📊 API数据为0，用自统计补充: 入群{joined_today} 离群{left_today}")
        data_source = "📡 Telegram官方统计"
    else:
        joined_today = joined_today_db
        left_today = left_today_db
        net_today = net_today_db
        total_members = 0
        if gid:
            try:
                with rm.locked('bot'):
                    total_members = rm.bot.get_chat_member_count(gid)
            except Exception as e:
                logger.warning(f"auto_task 获取群成员数失败，降级用DB缓存: {e}")
                total_members = rm.db.get_group_total_members_latest(gid)
        active_today = rm.db.get_daily_active_users(today, gid)
        row = rm.db.conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date=? AND chat_id=?",
            (today, gid),
        ).fetchone()
        msgs_today = row[0] if row else 0
        data_source = "📊 自统计（事件追踪+校准）"

    joined_yest = joined_yest_db
    left_yest = left_yest_db
    net_yest = net_yest_db
    active_yest = rm.db.get_daily_active_users(yesterday, gid)
    row = rm.db.conn.execute(
        "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date=? AND chat_id=?",
        (yesterday, gid),
    ).fetchone()
    msgs_yest = row[0] if row else 0

    # ── 数据分析（基于上面的原始数据，不替用户下结论） ──
    activity_rate = (active_today / max(total_members, 1)) * 100
    activity_rate_yest = (active_yest / max(total_members, 1)) * 100

    silence_ratio = ((total_members - active_today) / max(total_members, 1)) * 100

    avg_msgs_per_active = (msgs_today / max(active_today, 1)) if active_today else 0
    if joined_today > 0:
        flow_ratio = f"{(left_today / joined_today) * 100:.0f}%"
    elif left_today > 0:
        flow_ratio = f"无新增 / 离群{left_today}"
    else:
        flow_ratio = "当日无入离群"

    html = f"""🏠 <b>群数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>原始数据</b>
├ 今日入群：{joined_today} {trend_fn(joined_today, joined_yest)}
├ 今日离群：{left_today} {trend_fn(left_today, left_yest)}
├ 净增人数：{net_today:+d} {trend_fn(net_today, net_yest)}
├ 群成员数：{total_members}
├ 活跃互动：{active_today} {trend_fn(active_today, active_yest)}
└ 群内发言：{msgs_today} {trend_fn(msgs_today, msgs_yest)}

━━━━━━━━━━━━━━━━━━

📎 <b>数据分析</b>
├ 活跃覆盖：{activity_rate:.1f}% {trend_fn(activity_rate, activity_rate_yest)}
├ 沉默比例：{silence_ratio:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
└ 离群/入群比：{flow_ratio}

━━━━━━━━━━━━━━━━━━

🌙 <b>昨日同期</b>
├ 入群{joined_yest}/离群{left_yest}/净增{net_yest:+d}
├ 互动{active_yest}/发言{msgs_yest}
└ 活跃覆盖{activity_rate_yest:.1f}%"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 群日报已发送: 入群{joined_today} 离群{left_today} 净增{net_today} 来源={'API' if use_api else '自统计'}")


def _send_daily_channel_report(rm, admin_id: int, today: str, trend_fn):
    """【Codex】频道数据日报：真实数据优先，保留轻量分析，不做打分裁判。"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return

    token = rm.config.get("TOKEN", "")
    yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
    gid = rm.config.get("GROUP_ID", 0)

    channel_lines = []
    stats_lines = []
    ops_lines = []
    total_posts_today = 0
    total_views_today = 0
    total_forwards_today = 0
    total_channel_members = 0
    any_api = False

    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

        # ── 获取当前成员数 ──
        ch_count = 0
        try:
            with rm.locked('bot'):
                ch_count = rm.bot.get_chat_member_count(cid)
        except Exception as e:
            logger.debug(f"频道成员数获取失败: {cname} err={e}")
            ch_count = rm.db.get_group_total_members_latest(cid)
        total_channel_members += ch_count

        ch_type = ch.get("type", "频道") if isinstance(ch, dict) else "频道"

        # ── 获取今日新增/离开数据 ──
        member_changes = rm.db.get_channel_member_changes(cid, yesterday, today)
        joined = member_changes["joined"]
        left = member_changes["left"]
        net = joined - left

        # ── 构建频道概况行 ──
        if joined > 0 or left > 0:
            channel_lines.append(f"├ {cname}：{ch_count}人 ({ch_type}) 今日+{joined}/-{left} 净{net:+d}")
        else:
            channel_lines.append(f"├ {cname}：{ch_count}人 ({ch_type}) 今日无变化")

        # ── 获取发帖/浏览数据 ──
        # 【v5.11.0】移除硬编码占位：api_ch = None 已删，保留 API 接入位
        api_ch = None
        if token:
            try:
                # 【v5.11.0】预留：未来接入 Telegram Bot API getChatStatistics
                # 需要 bot 在频道中是 admin 且 Telegram 开通了统计 API 权限
                # api_ch = rm.bot.get_chat_statistics(chat_id=cid)
                api_ch = None
                if api_ch:
                    any_api = True
            except Exception as e:
                logger.debug(f"获取频道统计API失败: {e}")

        yest_stats = rm.db.get_channel_daily_stats(cid, yesterday)
        posts_yest = yest_stats.get("posts", 0)
        views_yest = yest_stats.get("views", 0)

        posts_today = 0
        views_today = 0
        forwards_today = 0
        avg_views = 0
        has_data = False  # 【v5.11.0】追踪是否有真实数据

        if api_ch:
            posts_today = api_ch.get("messages_today", 0)
            views_today = api_ch.get("views_today", 0)
            forwards_today = api_ch.get("forwards_today", 0)
            if posts_today == 0 and views_today == 0:
                db_stats = rm.db.get_channel_daily_stats(cid, today)
                posts_today = db_stats.get("posts", 0)
                views_today = db_stats.get("views", 0)
                forwards_today = rm.db.get_channel_post_stats(cid, today).get("forwards", 0)
            avg_views = views_today // max(posts_today, 1)
            has_data = posts_today > 0 or views_today > 0
        else:
            try:
                today_stats = rm.db.get_channel_daily_stats(cid, today)
                native_stats = rm.db.get_channel_post_stats(cid, today)
                posts_today = today_stats.get("posts", 0)
                views_today = today_stats.get("views", 0)
                forwards_today = native_stats.get("forwards", 0)
                avg_views = today_stats.get("avg_views", 0)
                has_data = posts_today > 0 or views_today > 0
            except Exception as e:
                logger.debug(f"频道统计获取失败: {cname} err={e}")

        total_posts_today += posts_today
        total_views_today += views_today
        total_forwards_today += forwards_today

        # 【v5.11.0】0 值显示优化：发帖=0 时显示"暂无"，均阅=0 时显示"—"
        posts_str = _format_zero_data(posts_today, "count")
        views_str = _format_zero_data(views_today, "count")
        avg_views_str = "—" if avg_views == 0 else str(avg_views)

        stats_lines.append(
            f"├ {cname}："
            f"发帖{posts_str}{trend_fn(posts_today, posts_yest)} "
            f"浏览{views_str}{trend_fn(views_today, views_yest)} "
            f"均阅{avg_views_str}"
        )

        # ── 运营指标计算 ──
        reach_rate = (views_today / max(ch_count, 1)) * 100
        interact_rate = (forwards_today / max(views_today, 1)) * 100
        hot_posts = rm.db.get_channel_top_posts(cid, today, threshold=2.0)

        # 【v5.11.0】0 值显示优化
        reach_str = _format_zero_data(reach_rate, "percent")
        interact_str = _format_zero_data(interact_rate, "percent")

        ops_lines.append(
            f"├ {cname}：触达{reach_str}% 互动{interact_str}% 爆款{hot_posts}条"
        )

        if not has_data:
            logger.info(f"📊 频道 {cname} 当日无发帖/浏览数据，显示为'暂无'")

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    # ── 数据分析：保留可复核指标，不给主观评分 ──
    group_stats_today = rm.db.get_group_stats_by_date(today)
    net_group = 0
    for row in group_stats_today:
        if len(row) >= 6:
            net_group += row[4] or 0
    total_net = net_group + sum(
        rm.db.get_channel_member_changes(
            ch.get("id", 0) if isinstance(ch, dict) else ch, yesterday, today
        )["joined"] - rm.db.get_channel_member_changes(
            ch.get("id", 0) if isinstance(ch, dict) else ch, yesterday, today
        )["left"]
        for ch in channel_ids
    )
    total_reach_rate = (total_views_today / max(total_channel_members, 1)) * 100

    active_today = rm.db.get_daily_active_users(today)
    total_members_group = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members_group = rm.bot.get_chat_member_count(gid)
        except Exception as e:
            logger.warning(f"auto_task 获取群成员数失败，降级用DB缓存: {e}")
            total_members_group = rm.db.get_group_total_members_latest(gid)
    activity_rate = (active_today / max(total_members_group, 1)) * 100

    growth_note = f"全域净增 {total_net:+d}"
    avg_views_per_post = (total_views_today / total_posts_today) if total_posts_today else 0

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"

    html = f"""📢 <b>频道数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📈 <b>各频道概况</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📊 <b>原始数据</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

📎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 频道总触达：{total_reach_rate:.1f}%
├ 群活跃覆盖：{activity_rate:.1f}%
├ 单帖均阅：{avg_views_per_post:.1f}
└ 汇总：发帖{total_posts_today}条 / 浏览{total_views_today}次 / 转发{total_forwards_today}次 / {growth_note}"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 频道日报已发送: 发帖{total_posts_today} 浏览{total_views_today} API={'是' if any_api else '否'}")


def _job_weekly_report(rm):
    """【v5.9.0】每周数据报告 - 使用 TaskTransactionManager"""
    try:
        with TaskTransactionManager("weekly_report", rm.db, min_interval_sec=86400) as tx:
            if not tx.claimed:
                return
            admin_id = rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                raise _TaskAbort("ADMIN_ID为0")

            now = datetime.now(_CST)
            today = now.strftime("%Y-%m-%d")
            week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
            two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
            week_ago_ts = int((now - timedelta(days=7)).timestamp())
            now_ts = int(now.timestamp())

            _send_weekly_group_report(rm, admin_id, today, week_ago, two_weeks_ago)
            _send_weekly_channel_report(rm, admin_id, today, week_ago, week_ago_ts, now_ts)

            logger.info("✅ 每周数据报告已发送（群+频道）")
    except _TaskAbort as e:
        _handle_task_abort("weekly_report", e)
    except Exception as e:
        logger.error(f"每周数据报告失败：{e}")
        _retry_task(rm, _job_weekly_report, "weekly_report")


def _send_weekly_group_report(rm, admin_id: int, today: str, week_ago: str, two_weeks_ago: str):
    """群数据周报：原始数据优先，再补充趋势分析，不做主观裁判。"""
    gid = rm.config.get("GROUP_ID", 0)
    this_week = rm.db.get_weekly_group_stats(week_ago, today, chat_id=gid)
    last_week = rm.db.get_weekly_group_stats(two_weeks_ago, week_ago, chat_id=gid)

    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception as e:
            logger.warning(f"auto_task 获取群成员数失败，降级用DB缓存: {e}")
            total_members = rm.db.get_group_total_members_latest(gid)

    def pct(cur, prev):
        if prev == 0: return "🆕" if cur > 0 else "➖"
        diff = ((cur - prev) / prev) * 100
        if diff > 0: return f"📈+{diff:.0f}%"
        if diff < 0: return f"📉{diff:.0f}%"
        return "➖0%"

    def trend(cur, prev):
        if cur > prev: return "📈"
        if cur < prev: return "📉"
        return "➖"

    activity_rate = (this_week.get("active_users", 0) / max(total_members, 1)) * 100
    row = rm.db.conn.execute(
        "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
        (week_ago, today, gid),
    ).fetchone()
    speech_total = row[0] if row else 0
    avg_msgs_per_active = (speech_total / max(this_week.get("active_users", 0), 1)) if this_week.get("active_users", 0) else 0
    if this_week["joined"] > 0:
        leave_join_ratio = f"{(this_week['left'] / this_week['joined']) * 100:.0f}%"
    elif this_week["left"] > 0:
        leave_join_ratio = f"无新增 / 离群{this_week['left']}"
    else:
        leave_join_ratio = "本周无入离群"

    data_source = "📊 自统计（事件追踪+校准）"

    html = f"""🏠 <b>群数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>本周群动态</b>
├ 入群：{this_week['joined']} {trend(this_week['joined'], last_week['joined'])}
├ 离群：{this_week['left']} {trend(this_week['left'], last_week['left'])}
├ 净增：{this_week['net']:+d} {trend(this_week['net'], last_week['net'])}
├ 当前成员：{total_members}
└ 群内发言：{speech_total}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
├ 活跃覆盖：{activity_rate:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
├ 离群/入群比：{leave_join_ratio}
└ 周均成员：{this_week['avg_members']}

━━━━━━━━━━━━━━━━━━

📈 <b>周环比</b>
├ 入群变化：{pct(this_week['joined'], last_week['joined'])}
├ 离群变化：{pct(this_week['left'], last_week['left'])}
└ 净增变化：{pct(this_week['net'], last_week['net'])}

━━━━━━━━━━━━━━━━━━

📉 <b>上周同期</b>
├ 入群{last_week['joined']}/离群{last_week['left']}/净增{last_week['net']:+d}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 群周报已发送")


def _send_weekly_channel_report(rm, admin_id: int, today: str, week_ago: str, week_ago_ts: int, now_ts: int):
    """频道数据周报：先给真实统计，再补充触达和转发趋势。"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return

    token = rm.config.get("TOKEN", "")
    channel_lines = []
    stats_lines = []
    ops_lines = []
    any_api = False
    total_posts = 0
    total_views = 0

    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

        # ── 获取当前成员数 ──
        ch_count = 0
        try:
            with rm.locked('bot'):
                ch_count = rm.bot.get_chat_member_count(cid)
        except Exception as e:
            logger.debug(f"频道周报获取失败: {cname} err={e}")
            ch_count = rm.db.get_group_total_members_latest(cid)

        # ── 获取本周成员变化 ──
        member_changes = rm.db.get_channel_weekly_member_changes(cid, week_ago, today)
        joined = member_changes["joined"]
        left = member_changes["left"]
        net = joined - left

        channel_lines.append(f"├ {cname}：{ch_count}人 周+{net:+d} (+{joined}/-{left})")

        # ── 发帖/浏览统计 ──
        api_ch = None
        if token:
            try:
                api_ch = None
                if api_ch:
                    any_api = True
            except Exception as e:
                logger.debug(f"获取频道API数据失败: {e}")

        posts = 0
        views = 0
        forwards = 0

        if api_ch:
            posts = api_ch.get("messages_today", 0)
            views = api_ch.get("views_today", 0)
            forwards = api_ch.get("forwards_today", 0)
            stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")
        else:
            db_stats = rm.db.get_channel_posts_in_range(cid, week_ago_ts, now_ts)
            posts = db_stats.get("posts", 0) if db_stats else 0
            views = db_stats.get("views", 0) if db_stats else 0
            forwards = db_stats.get("forwards", 0) if db_stats else 0
            stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")

        reach_rate = (views / max(ch_count, 1)) * 100
        interact_rate = (forwards / max(views, 1)) * 100
        ops_lines.append(f"├ {cname}：触达约{reach_rate:.0f}% 转发率{interact_rate:.1f}%")
        total_posts += posts
        total_views += views

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"
    avg_views_per_post = (total_views / total_posts) if total_posts else 0

    html = f"""📢 <b>频道数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道周数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 周总发帖：{total_posts}
└ 单帖均阅：{avg_views_per_post:.1f}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 频道周报已发送 API={'是' if any_api else '否'}")


def _job_monthly_report(rm):
    """【v5.9.0】每月数据报告 - 使用 TaskTransactionManager"""
    try:
        with TaskTransactionManager("monthly_report", rm.db, min_interval_sec=86400 * 28) as tx:
            if not tx.claimed:
                return
            admin_id = rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                raise _TaskAbort("ADMIN_ID为0")

            now = datetime.now(_CST)
            today = now.strftime("%Y-%m-%d")
            # 本月1号
            month_start = now.replace(day=1).strftime("%Y-%m-%d")
            # 上月1号（用于环比）
            if now.month == 1:
                prev_month_start = now.replace(year=now.year - 1, month=12, day=1).strftime("%Y-%m-%d")
            else:
                prev_month_start = now.replace(month=now.month - 1, day=1).strftime("%Y-%m-%d")

            _send_monthly_group_report(rm, admin_id, today, month_start, prev_month_start)
            _send_monthly_channel_report(rm, admin_id, today, month_start, prev_month_start)

            logger.info("✅ 每月数据报告已发送（群+频道）")
    except _TaskAbort as e:
        _handle_task_abort("monthly_report", e)
    except Exception as e:
        logger.error(f"每月数据报告失败：{e}")
        _retry_task(rm, _job_monthly_report, "monthly_report")


def _send_monthly_group_report(rm, admin_id: int, today: str, month_start: str, prev_month_start: str):
    """群数据月报：原始数据优先，再补充趋势分析，不做主观裁判。"""
    gid = rm.config.get("GROUP_ID", 0)
    this_month = rm.db.get_weekly_group_stats(month_start, today, chat_id=gid)
    last_month = rm.db.get_weekly_group_stats(prev_month_start, month_start, chat_id=gid)

    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception as e:
            logger.warning(f"auto_task 获取群成员数失败，降级用DB缓存: {e}")
            total_members = rm.db.get_group_total_members_latest(gid)

    def pct(cur, prev):
        if prev == 0: return "🆕" if cur > 0 else "➖"
        diff = ((cur - prev) / prev) * 100
        if diff > 0: return f"📈+{diff:.0f}%"
        if diff < 0: return f"📉{diff:.0f}%"
        return "➖0%"

    def trend(cur, prev):
        if cur > prev: return "📈"
        if cur < prev: return "📉"
        return "➖"

    activity_rate = (this_month.get("active_users", 0) / max(total_members, 1)) * 100
    row = rm.db.conn.execute(
        "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
        (month_start, today, gid),
    ).fetchone()
    speech_total = row[0] if row else 0
    avg_msgs_per_active = (speech_total / max(this_month.get("active_users", 0), 1)) if this_month.get("active_users", 0) else 0
    if this_month["joined"] > 0:
        leave_join_ratio = f"{(this_month['left'] / this_month['joined']) * 100:.0f}%"
    elif this_month["left"] > 0:
        leave_join_ratio = f"无新增 / 离群{this_month['left']}"
    else:
        leave_join_ratio = "本月无入离群"

    data_source = "📊 自统计（事件追踪+校准）"
    month_display = month_start[:7]

    html = f"""🏠 <b>群数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>本月群动态</b>
├ 入群：{this_month['joined']} {trend(this_month['joined'], last_month['joined'])}
├ 离群：{this_month['left']} {trend(this_month['left'], last_month['left'])}
├ 净增：{this_month['net']:+d} {trend(this_month['net'], last_month['net'])}
├ 当前成员：{total_members}
└ 群内发言：{speech_total}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
├ 月活跃覆盖：{activity_rate:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
└ 离群/入群比：{leave_join_ratio}

━━━━━━━━━━━━━━━━━━

📈 <b>月环比</b>
├ 入群变化：{pct(this_month['joined'], last_month['joined'])}
├ 离群变化：{pct(this_month['left'], last_month['left'])}
└ 净增变化：{pct(this_month['net'], last_month['net'])}

━━━━━━━━━━━━━━━━━━

📉 <b>上月同期</b>
├ 入群{last_month['joined']}/离群{last_month['left']}/净增{last_month['net']:+d}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 群月报已发送")


def _send_monthly_channel_report(rm, admin_id: int, today: str, month_start: str, prev_month_start: str):
    """频道数据月报：先给真实统计，再补充触达和转发趋势。"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return

    token = rm.config.get("TOKEN", "")
    channel_lines = []
    stats_lines = []
    ops_lines = []
    any_api = False
    month_display = month_start[:7]
    total_posts = 0
    total_views = 0

    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

        # ── 获取当前成员数 ──
        ch_count = 0
        try:
            with rm.locked('bot'):
                ch_count = rm.bot.get_chat_member_count(cid)
        except Exception as e:
            logger.debug(f"频道月报获取失败: {cname} err={e}")
            ch_count = rm.db.get_group_total_members_latest(cid)

        # ── 获取本月成员变化 ──
        member_changes = rm.db.get_channel_monthly_member_changes(cid, month_display)
        joined = member_changes["joined"]
        left = member_changes["left"]
        net = joined - left

        channel_lines.append(f"├ {cname}：{ch_count}人 月+{net:+d} (+{joined}/-{left})")

        # ── 发帖/浏览统计 ──
        month_start_ts = int(datetime.strptime(month_start, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        now_ts = int(datetime.now(_CST).timestamp())

        api_ch = None
        if token:
            try:
                api_ch = None
                if api_ch:
                    any_api = True
            except Exception as e:
                logger.debug(f"获取频道API数据失败: {e}")

        posts = 0
        views = 0
        forwards = 0

        if api_ch:
            posts = api_ch.get("messages_today", 0)
            views = api_ch.get("views_today", 0)
            forwards = api_ch.get("forwards_today", 0)
            stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")
        else:
            db_stats = rm.db.get_channel_posts_in_range(cid, month_start_ts, now_ts)
            posts = db_stats.get("posts", 0) if db_stats else 0
            views = db_stats.get("views", 0) if db_stats else 0
            forwards = db_stats.get("forwards", 0) if db_stats else 0
            stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")

        reach_rate = (views / max(ch_count, 1)) * 100
        interact_rate = (forwards / max(views, 1)) * 100
        ops_lines.append(f"├ {cname}：触达约{reach_rate:.0f}% 转发率{interact_rate:.1f}%")
        total_posts += posts
        total_views += views

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"
    avg_views_per_post = (total_views / total_posts) if total_posts else 0

    html = f"""📢 <b>频道数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道月数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 月总发帖：{total_posts}
└ 单帖均阅：{avg_views_per_post:.1f}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 频道月报已发送 API={'是' if any_api else '否'}")


# ═══════════════════════════════════════════════════════════════════════════
# 塔罗缓存：同一人同一天结果固定（北京时间为准）
# ═══════════════════════════════════════════════════════════════════════════
_tarot_daily_cache: Dict[str, Dict] = {}  # {user_id_date: {...}}
_tarot_cache_last_date: str = ""  # 【v4.3.2修复M-03】上次缓存日期，用于清理
_TAROT_CACHE_MAX_SIZE = 500  # 【v4.5.35修复】缓存上限，防止内存泄漏


def _get_tarot_cache(uid: int, dt: datetime) -> Dict:
    """获取/生成某用户当日的塔罗运势（北京时间）"""
    global _tarot_daily_cache, _tarot_cache_last_date
    cst_now = dt.astimezone(_CST)
    date_key = cst_now.strftime("%Y-%m-%d")

    if date_key != _tarot_cache_last_date:
        _tarot_daily_cache = {}
        _tarot_cache_last_date = date_key

    # 【v4.5.35修复】缓存上限保护，防止群成员过多导致内存泄漏
    if len(_tarot_daily_cache) >= _TAROT_CACHE_MAX_SIZE:
        # 随机淘汰20%旧缓存
        import random
        keys = list(_tarot_daily_cache.keys())
        for k in random.sample(keys, len(keys) // 5):
            del _tarot_daily_cache[k]
        logger.debug(f"🎴 塔罗缓存触发LRU淘汰，当前大小={len(_tarot_daily_cache)}")

    cache_key = f"{uid}_{date_key}"

    if cache_key not in _tarot_daily_cache:
        # 生成新数据并缓存
        _tarot_daily_cache[cache_key] = _generate_tarot_data(uid)

    return _tarot_daily_cache[cache_key]


def _get_fallback_hook(theme: str, uname: str) -> str:
    """群内继续互动的中性钩子，不导私聊或成交。"""
    return random.choice(_TAROT_HOOKS)


def _generate_tarot_data(seed_uid: int) -> Dict:
    """根据用户ID生成稳定的塔罗数据（牌名预设，其余由AI生成）"""
    rng = random.Random(seed_uid)  # 用用户ID做种子，同一人永远同结果

    # 牌名和主题预设（保持神秘感和随机性）
    themes = ["整体运势", "爱情运势", "财运", "工作运", "健康运", "桃花运"]
    fortune_theme = rng.choice(themes)

    major = ["愚者", "魔术师", "女祭司", "女皇", "皇帝", "教皇", "恋人", "战车",
             "力量", "隐士", "命运之轮", "正义", "吊人", "死神", "节制", "恶魔",
             "塔", "星星", "月亮", "太阳", "审判", "世界"]
    suits = ["权杖", "圣杯", "宝剑", "金币"]
    card_name = rng.choice(major + [f"{s}{rng.randint(1,10)}" for s in suits])
    card_position = rng.choice(["正位", "逆位"])

    # 基础数据（供AI prompt使用）
    return {
        "theme": fortune_theme,
        "card": card_name,
        "position": card_position,
        "seed": seed_uid,  # 传给AI用
    }


def _generate_tarot_ai_content(tarot: Dict, seed: int, rm) -> Dict:
    """调用AI生成完整的塔罗运势内容（整卡控制在一屏内，约130字）"""
    seed_for_ai = seed or random.randint(100000, 999999)

    prompt = f"""你是公开身份的 Mory 小助理，正在主持一个娱乐性质的塔罗互动。

根据以下信息生成塔罗运势，全部要浓缩在一屏能看完的长度：

【运势类型】：{tarot['theme']}
【塔罗牌】：{tarot['card']} {tarot['position']}

请按以下格式生成：

1. 牌面描述（一句话，15-25字，有画面感，带一个emoji）
2. 今日解读（1-2句话，30-40字，有故事感，带emoji）
3. 今日建议（一句话，15字以内，带emoji）
4. 幸运色（只写颜色，2-4字）

其他信息（幸运方位、幸运数字、贵人星座、幸运时段）可以自由发挥，用自然的方式融入解读中，不需要单独列出。

seed={seed_for_ai}
要求：
- 语气自然友好，并提醒这只是轻松互动
- 禁止空话套话，用画面感语言
- 解读要有故事感，别超过40字
- 每次seed不同，内容必须不同"""

    try:
        with rm.locked('ai'):
            ai_response = rm.ai.ask(prompt, mode="tarot_interpret", seed=seed_for_ai)

        if not ai_response or len(ai_response) < 50:
            raise ValueError("AI返回内容太短")

        # 解析AI返回的内容
        content = _parse_tarot_ai_response(ai_response, tarot)
        return content
    except Exception as e:
        logger.warning(f"AI生成塔罗内容失败，使用备用方案: {e}")
        return _get_fallback_tarot_content(tarot)


def _parse_tarot_ai_response(ai_response: str, tarot: Dict) -> Dict:
    """
    解析AI返回的塔罗内容（正则增强版）

    【v4.2.8修复】采用正则表达式精准捕获，防止AI输出格式不标准导致的解析失败
    """
    import re

    lines = ai_response.strip().split('\n')
    full_text = ai_response.strip()

    result = {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 今日牌面呈现吉祥之象",  # 默认
        "meaning": "今日运势平稳，保持积极心态...",  # 默认
        "advice": "保持好心情，顺势而为",  # 默认
        "result": "会有好事发生",  # 默认
        "color": None,  # 待解析
        "dir": None,   # 待解析
        "nums": None,  # 待解析
        "star": None,  # 待解析
        "time": None,  # 待解析
    }

    # ─── 正则表达式精准匹配 ─────────────────────────────────────────────

    # 1. 牌面描述：匹配 "牌面：" 或 "描述：" 后面的内容
    mood_match = re.search(r'(?:牌面描述?|[:：].*?)[:：]\s*(.+?)(?:\n|$)', full_text)
    if mood_match:
        result["mood"] = mood_match.group(1).strip()
    else:
        # 容错：找包含🌟或✨的长句
        for line in lines:
            if ('🌟' in line or '✨' in line) and len(line) > 15:
                result["mood"] = line.strip()
                break

    # 2. 今日解读：匹配 "解读：" 或 "今日解读：" 后面的内容
    meaning_match = re.search(r'(?:今日)?(?:解读?|💫|📖)[:：]\s*(.+?)(?:\n|$)', full_text)
    if meaning_match:
        result["meaning"] = meaning_match.group(1).strip()
    else:
        # 容错：找最长的句子作为解读
        candidates = [l.strip() for l in lines if 30 < len(l.strip()) < 100]
        if candidates:
            result["meaning"] = candidates[0]

    # 3. 建议：匹配 "建议：" 后面的内容
    advice_match = re.search(r'(?:今日)?(?:建议?|💡|🌱)[:：]\s*(.+?)(?:\n|$)', full_text)
    if advice_match:
        result["advice"] = advice_match.group(1).strip()
    else:
        # 容错：找短句
        for line in lines:
            if len(line.strip()) < 30 and ('💡' in line or '🌱' in line):
                result["advice"] = line.strip()
                break

    # 4. 幸运色：匹配 "色：" 后面的颜色词
    color_match = re.search(r'(?:幸运)?(?:色|🌈|🎨)[:：]\s*(\S{1,4})', full_text)
    if not color_match:
        # 直接在全文中找颜色词
        colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色", "橙色", "黄色", "青色", "棕色"]
        for c in colors:
            if c in full_text:
                result["color"] = c
                break
    if color_match:
        result["color"] = color_match.group(1).strip()
    if not result["color"]:
        result["color"] = "蓝色"  # 最终兜底

    # 5. 幸运方位
    dir_match = re.search(r'(?:幸运)?(?:方位?|方向?|📍|🧭)[:：]\s*(\S{1,4})', full_text)
    if not dir_match:
        dirs = ["东方", "西方", "南方", "北方", "东南", "东北", "西南", "西北", "东", "南", "西", "北"]
        for d in dirs:
            if d in full_text:
                result["dir"] = d
                break
    if dir_match:
        result["dir"] = dir_match.group(1).strip()
    if not result["dir"]:
        result["dir"] = "东方"  # 最终兜底

    # 6. 幸运数字：提取3个数字
    nums = re.findall(r'\b(\d{1,3})\b', full_text)
    nums = [n for n in nums if 1 <= int(n) <= 99][:3]  # 只取1-99范围内的数字，最多3个
    if len(nums) >= 3:
        result["nums"] = f"{nums[0]}, {nums[1]}, {nums[2]}"
    else:
        result["nums"] = "7, 23, 45"  # 兜底

    # 7. 贵人星座
    star_match = re.search(r'(?:贵人)?(?:星座?|⭐|🌟)[:：]\s*(\S{2,4}座?)', full_text)
    if not star_match:
        stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
                 "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座",
                 "白羊", "金牛", "双子", "巨蟹", "狮子", "处女",
                 "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼"]
        for s in stars:
            if s in full_text:
                result["star"] = s if "座" in s else s + "座"
                break
    if star_match:
        result["star"] = star_match.group(1).strip()
    if not result["star"]:
        result["star"] = "天秤座"  # 兜底

    # 8. 幸运时段
    time_match = re.search(r'(?:幸运)?(?:时段?|时间?|⏰|🕐)[:：]\s*(.+?)(?:\n|$)', full_text)
    if time_match:
        result["time"] = time_match.group(1).strip()
    else:
        # 容错：找包含时间关键词的行
        for line in lines:
            if any(x in line for x in ['点', '时', '早', '午', '晚', '上', '下']):
                if len(line.strip()) < 15:
                    result["time"] = line.strip()
                    break
    if not result["time"]:
        result["time"] = "上午9-11点"  # 兜底

    return result


def _get_fallback_tarot_content(tarot: Dict) -> Dict:
    """备用塔罗内容（AI失败时使用）"""
    rng = random.Random(tarot.get('seed', 42))

    meanings = {
        "正位": ["内心充满希望，适合开展新计划", "感情上可能有惊喜",
                "财运上升，适合投资", "人际关系和谐"],
        "逆位": ["有些迷茫，需要冷静思考", "感情上可能有误会",
                "财务上要谨慎", "工作上可能遇小阻碍"]
    }

    colors = ["白色", "黑色", "红色", "蓝色", "绿色", "紫色", "粉色", "金色"]
    dirs = ["东方", "西方", "南方", "北方", "东南", "东北"]
    stars = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座", "天秤座", "天蝎座"]

    return {
        "theme": tarot['theme'],
        "card": tarot['card'],
        "position": tarot['position'],
        "mood": "✨ 牌面呈现吉祥之象",
        "meaning": rng.choice(meanings[tarot['position']]),
        "advice": rng.choice(["大胆尝试新事物", "多倾听少说话", "主动出击别犹豫"]),
        "result": rng.choice(["会有意外收获", "会有贵人相助", "会有好运降临"]),
        "color": rng.choice(colors),
        "dir": rng.choice(dirs),
        "nums": f"{rng.randint(1,99)}, {rng.randint(1,99)}, {rng.randint(1,99)}",
        "star": rng.choice(stars),
        "time": rng.choice(["早上9-11点", "下午15-17点", "晚上19-21点"]),
    }


def _job_tarot_flirt(rm):
    """【v5.9.0】每日塔罗搭讪（30%概率，针对群里活跃用户）- 使用 TaskTransactionManager

    【特性】
    - 同一人同一天结果固定（北京时间为准）
    - 高度随机：40%短版 / 60%长版
    - 卡片式排版，手机一屏可看完
    """
    global _tarot_daily_cache, _tarot_cache_last_date
    today_key = datetime.now(_CST).strftime("%Y-%m-%d")
    if today_key != _tarot_cache_last_date:
        _tarot_daily_cache = {}
        _tarot_cache_last_date = today_key

    try:
        with TaskTransactionManager("tarot_flirt", rm.db, resources=['ai', 'bot'], min_interval_sec=7200) as tx:
            if not tx.claimed:
                return
            if random.random() > 0.30:
                raise _TaskAbort("30%概率跳过", expected=True)

            gid = rm.config.get("GROUP_ID", 0)
            admin_id = rm.config.get("ADMIN_ID", 0)
            if not gid or not admin_id:
                raise _TaskAbort("群ID或管理员ID为0", expected=True)

            logger.info("🎴 触发每日塔罗搭讪任务")

            try:
                members = rm.bot.get_chat_member_count(gid)
                if members < 5:
                    raise _TaskAbort("群成员太少", expected=True)
            except _TaskAbort:
                raise
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            recent_users = {}
            try:
                ts_1h_ago = int(time.time()) - 3600
                active_users = rm.db.get_active_users(ts_1h_ago)
                for uid, uname, keywords in active_users[:20]:
                    if uid != admin_id:
                        recent_users[uid] = (uname or "哥哥", keywords or "")
            except Exception as e:
                logger.debug(f"获取活跃用户失败：{e}")
                raise _TaskAbort("获取活跃用户失败")

            if not recent_users:
                raise _TaskAbort("无活跃用户", expected=True)

            uid, (uname, user_msg) = random.choice(list(recent_users.items()))

            logger.info(f"🎴 塔罗搭讪目标: {uname} 说: {user_msg[:30]}")

            tarot_base = _get_tarot_cache(uid, datetime.now(_CST))

            tarot = _generate_tarot_ai_content(tarot_base, uid, rm)

            opener_text = random.choice(['哥哥～', '嘿～', '在吗～', '哎～', '诶～'])
            opener_action = random.choice(['看到你说的', '刷到你这句', '你刚才说'])

            convert_seed = random.randint(10000, 99999)
            convert_prompt = f"""你是公开身份的 Mory 小助理，刚在群里给「{uname}」做了「{tarot['theme']}」娱乐互动。
写一句自然的群内承接问题。
要求：20-35字，不导私聊、不谈商业、不声称还有隐藏内容。
seed={convert_seed}"""

            try:
                convert_hint = rm.ai.ask(convert_prompt, mode="convert_hook", seed=convert_seed)
                if not convert_hint or len(convert_hint) < 10:
                    convert_hint = _get_fallback_hook(tarot['theme'], uname)
            except Exception as e:
                logger.warning(f"auto_task AI转换钩子失败，降级用兜底文案: {e}")
                convert_hint = _get_fallback_hook(tarot['theme'], uname)

            short_mode = random.random() < 0.4

            safe_uname = html.escape(str(uname))
            safe_opener = html.escape(str(opener_text))
            safe_action = html.escape(str(opener_action))
            safe_user_msg = html.escape(str(user_msg[:10]))
            safe_card = html.escape(str(tarot['card']))
            safe_position = html.escape(str(tarot['position']))
            safe_theme = html.escape(str(tarot['theme']))
            safe_meaning = html.escape(str(tarot['meaning']))
            safe_advice = html.escape(str(tarot['advice']))
            safe_color = html.escape(str(tarot['color']))
            safe_dir = html.escape(str(tarot['dir']))
            safe_nums = html.escape(str(tarot['nums']))
            safe_star = html.escape(str(tarot['star']))
            safe_time = html.escape(str(tarot['time']))
            safe_convert = html.escape(str(convert_hint))

            if short_mode:
                html_reply = f"""🎴 <b>{safe_card} {safe_position}</b>

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

🌈 {safe_color} · 📍 {safe_dir}

{safe_convert}"""
            else:
                html_reply = f"""🎴 <b>{safe_theme}</b> · {safe_card} {safe_position}

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

💡 {safe_advice}

🌈 {safe_color} · 📍 {safe_dir} · 🔢 {safe_nums} · ⭐ {safe_star} · ⏰ {safe_time}

{safe_convert}"""

            try:
                rm.bot.send_message(gid, html_reply, parse_mode="HTML")
                logger.info(f" 塔罗搭讪成功: @{uname}")
            except Exception as e:
                logger.error(f"塔罗搭讪发送失败：{e}")
                raise
    except _TaskAbort as e:
        _handle_task_abort("tarot_flirt", e)
    except Exception as e:
        logger.error(f"塔罗搭讪任务失败：{e}")


def _do_backup(db_file: str):
    """执行数据库备份
    保留策略 [v5.16.5 改]：每小时 1 份×最近 24 小时 + 每天 1 份×最近 7 天 = 最多 31 份
    旧策略保留 168 份（7 天×24 小时）→ 200MB+ 占用
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(base_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts_str = datetime.now(_CST).strftime("%Y%m%d_%H00")
    dest = os.path.join(backup_dir, f"mory_backup_{ts_str}.db")
    try:
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_file)
        dst_conn = _sqlite3.connect(dest)
        try:
            # 【TRAE SOLO CN v5.18.3审计修复】备份连接加 busy_timeout，防止与 Bot 进程互锁
            src_conn.execute("PRAGMA busy_timeout=30000")
            src_conn.backup(dst_conn)
        finally:
            # 【v5.31.2 修复】backup 失败时也要关闭连接，避免源库读锁残留阻塞 Bot 写操作
            dst_conn.close()
            src_conn.close()
        # [v5.16.5] 按时间分层保留：24 小时内全部保留 + 24 小时外每天 1 份×7 天
        all_backups = sorted(glob.glob(os.path.join(backup_dir, "mory_backup_*.db")))
        now_ts = time.time()
        hourly_keep = []  # 24 小时内全保留
        daily_keep = []   # 24 小时外按天保留最新 1 份×7 天
        daily_seen = {}   # {date_str: path}
        for path in all_backups:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            age_hours = (now_ts - mtime) / 3600
            if age_hours <= 24:
                hourly_keep.append(path)
            else:
                # 从文件名 mory_backup_YYYYMMDD_HH00.db 提取日期
                # split("_") = ['mory', 'backup', 'YYYYMMDD', 'HH00.db']，索引 2 才是日期
                basename = os.path.basename(path)
                parts = basename.split("_")
                if len(parts) >= 3 and parts[2][:8].isdigit():
                    date_str = parts[2][:8]
                else:
                    continue
                # 同一天内只保留最新 1 份
                if date_str not in daily_seen or os.path.getmtime(daily_seen[date_str]) < mtime:
                    daily_seen[date_str] = path
        daily_keep = list(daily_seen.values())[-7:]  # 最多 7 天
        keep = set(hourly_keep + daily_keep)
        removed = 0
        for old in all_backups:
            if old not in keep:
                try:
                    os.remove(old)
                    removed += 1
                except OSError as e:
                    logger.debug(f"auto_task 删除旧备份跳过: {e}")
        # 【v5.31.x 优化】硬上限兜底：极端情况下（清理失败累积）限制总份数，防磁盘无限增长
        MAX_BACKUPS = 60
        remaining = sorted(glob.glob(os.path.join(backup_dir, "mory_backup_*.db")), key=os.path.getmtime)
        extra_removed = 0
        while len(remaining) > MAX_BACKUPS:
            old = remaining.pop(0)
            try:
                os.remove(old)
                extra_removed += 1
            except OSError as e:
                logger.debug(f"auto_task 硬上限删除旧备份跳过: {e}")
                break
        removed += extra_removed
        logger.info(f"💾 备份完成：{dest}（保留 {len(keep)} 份，清理 {removed} 份）")
    except Exception as e:
        logger.error(f"备份失败：{e}")


def _job_daily_backup(rm):
    """每日自动备份任务（凌晨3:00）

    备份 mory.db 和 config.json 到 backups/ 目录
    文件名格式：backup_YYYYMMDD_HHMMSS.db / backup_YYYYMMDD_HHMMSS.json
    保留最近7天的备份，删除更早的
    """
    if not rm.config.get("DAILY_BACKUP_ENABLED", False):
        return

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backup_dir = os.path.join(base_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)

        ts_str = datetime.now(_CST).strftime("%Y%m%d_%H%M%S")

        # 备份数据库
        db_src = rm.db.db_file
        db_dest = os.path.join(backup_dir, f"backup_{ts_str}.db")
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_src)
        dst_conn = _sqlite3.connect(db_dest)
        try:
            # 【TRAE SOLO CN v5.18.3审计修复】备份连接加 busy_timeout，防止与 Bot 进程互锁
            src_conn.execute("PRAGMA busy_timeout=30000")
            src_conn.backup(dst_conn)
        finally:
            # 【v5.31.2 修复】backup 失败时也要关闭连接，避免源库读锁残留阻塞 Bot 写操作
            dst_conn.close()
            src_conn.close()

        # 备份配置文件
        config_src = os.path.join(base_dir, "config.json")
        config_dest = os.path.join(backup_dir, f"backup_{ts_str}.json")
        if os.path.exists(config_src):
            import shutil
            shutil.copy2(config_src, config_dest)

        # 清理7天前的备份
        cutoff_time = time.time() - (7 * 86400)
        removed_count = 0
        for filename in os.listdir(backup_dir):
            if not (filename.endswith('.db') or filename.endswith('.json')):
                continue
            filepath = os.path.join(backup_dir, filename)
            try:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    removed_count += 1
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        logger.info(f"💾 每日备份完成：数据库+配置文件（清理 {removed_count} 个旧备份）")

    except Exception as e:
        logger.error(f"每日备份失败：{e}")


def _job_log_cleanup(rm):
    """日志自动清理任务（凌晨4:00）

    删除超过 LOG_RETENTION_DAYS 天的日志文件
    【TRAE SOLO CN v5.18.3审计修复】追加清理 7 张无清理逻辑的日志表（30天）+ 90天日志表
    """
    try:
        from core.logging_util import cleanup_old_logs

        retention_days = rm.config.get("LOG_RETENTION_DAYS", 30)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_dir = os.path.join(base_dir, "logs")

        removed_count = cleanup_old_logs(log_dir, retention_days)
        if removed_count > 0:
            logger.info(f"🧹 日志清理完成：删除 {removed_count} 个超过 {retention_days} 天的日志文件")

        # 【TRAE SOLO CN v5.18.3审计修复】清理数据库日志表（30天）
        import time as _time
        now_ts = int(_time.time())
        cutoff_30 = now_ts - 30 * 86400
        cutoff_90 = now_ts - 90 * 86400
        try:
            db = rm.db
            with db.lock:
                # 30 天前的日志表（表名 → 实际时间戳列名，避免 no such column: ts）
                tables_30 = {
                    "task_log": "exec_ts",
                    "spam_track": "window_start",
                    "puzzle_daily": "ts",
                    "broadcast_tracking": "ts",
                    "orphan_cleanup_log": "run_at",
                    "group_join_log": "ts",
                    "group_left_log": "ts",
                    "proactive_engage_log": "ts",
                    "retroactive_scan_log": "ts",
                    "button_click_stats": "last_updated",
                }
                for table, ts_col in tables_30.items():
                    try:
                        db.conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff_30,))
                    except Exception as de:
                        logger.debug(f"清理 {table} 跳过: {de}")
                # 90 天前的日志表
                tables_90 = {
                    "admin_logs": "ts",
                    "telemetry_events": "ts",
                    "conversation_telemetry": "ts",
                    "ab_guardian_log": "ts",
                    "points_log": "ts",
                    "deleted_messages": "ts",
                    "message_snapshots": "ts",
                    "ab_test_stats": "ts",
                    "weekly_ab_report": "generated_at",
                }
                for table, ts_col in tables_90.items():
                    try:
                        db.conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff_90,))
                    except Exception as de:
                        logger.debug(f"清理 {table} 跳过: {de}")
                db.conn.commit()
            logger.info(f"🧹 数据库日志表清理完成（30天+90天）")
        except Exception as dbe:
            logger.warning(f"数据库日志表清理失败（非致命）: {dbe}")

    except Exception as e:
        logger.error(f"日志清理失败：{e}")


def _job_startup_history_cleanup(rm):
    """[TRAE SOLO CN] v5.15.3 新增：启动追溯清理黑名单用户历史消息
    AGENTS.md 教训 #17 落实：从 message_snapshots 读 blacklist 用户的所有历史消息，逐一删除
    这是 v5.15.2 之前漏的：18:36 教白嫖消息因 P1 拦截不记 msg_id 而无法追溯删除
    修复后所有进分发流程的消息都入 message_snapshots，未来再发生类似情况 100% 可追溯
    """
    try:
        bot = rm.bot
        db = rm.db
        CONFIG = rm.config
        # 找管理的群
        chat_ids = []
        gid = CONFIG.get("GROUP_ID", 0)
        if gid:
            chat_ids = [gid]
        else:
            try:
                mg = CONFIG.get("MANAGED_GROUPS", [])
                if isinstance(mg, int):
                    chat_ids = [mg]
                elif mg:
                    chat_ids = list(mg)
            except Exception as e:
                logger.warning(f"获取管理群组列表失败: {e}")
                chat_ids = []
        if not chat_ids:
            logger.info("[启动历史清理] 未找到管理的群组，跳过")
            return
        # 收集所有 blacklist + global_blacklist 的 uid
        all_banned_uids = set()
        try:
            for row in db.conn.execute("SELECT uid FROM blacklist").fetchall():
                all_banned_uids.add(int(row[0]))
        except Exception as e:
            logger.warning(f"查询blacklist表失败: {e}")
        try:
            for row in db.conn.execute("SELECT user_id FROM global_blacklist").fetchall():
                all_banned_uids.add(int(row[0]))
        except Exception as e:
            logger.warning(f"查询global_blacklist表失败: {e}")
        if not all_banned_uids:
            logger.info("[启动历史清理] 无黑名单用户，跳过")
            return
        logger.info(f"[启动历史清理] 开始清理 {len(all_banned_uids)} 个黑名单用户的历史消息")
        total_deleted = 0
        for uid in all_banned_uids:
            for cid in chat_ids:
                try:
                    msgs = db.get_user_ad_messages(uid, cid, limit=500)
                except Exception as e:
                    logger.warning(f"auto_task 获取用户消息失败，降级空列表: {e}")
                    msgs = []
                for mm in msgs:
                    mid = mm.get("msg_id")
                    if not mid: continue
                    try:
                        from modules.ad_enforcement import delete_confirmed_ad_message
                        deletion = delete_confirmed_ad_message(bot, db, cid, mid)
                        if deletion["deleted"]:
                            total_deleted += 1
                    except Exception:
                        # 消息已删/无权/超时，静默
                        pass
        logger.info(f"[启动历史清理] 完成，共清理 {total_deleted} 条黑名单用户历史消息")
    except Exception as e:
        logger.error(f"[启动历史清理] 异常: {e}")


def _job_startup_member_scan(rm):
    """[TRAE SOLO CN] v5.8.1 启动时扫描群成员（数据库驱动+用户名/Bio/头像检测）"""
    try:
        # 【v5.31.2 修复】高频任务 task_key 加时间窗口后缀，避免 UNIQUE 索引拦截
        _hour = datetime.now(_CST).strftime("%Y-%m-%d_%H")
        with TaskTransactionManager(f"startup_member_scan_{_hour}", rm.db, resources=None, min_interval_sec=3600) as tx:
            if not tx.claimed:
                return

            logger.info("[启动扫描] 开始扫描群成员...")

            CONFIG = rm.config
            bot = rm.bot
            db = rm.db

            group_ids = []
            gid = CONFIG.get("GROUP_ID", 0)
            if gid:
                group_ids = [gid]
            else:
                try:
                    mg = CONFIG.get("MANAGED_GROUPS", [])
                    if isinstance(mg, int):
                        group_ids = [mg]
                    elif mg:
                        group_ids = mg
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
            if not group_ids:
                logger.info("[启动扫描] 未找到管理的群组，跳过成员扫描")
                raise _TaskAbort("未找到管理的群组")

            import re
            from modules.ad_patterns_encoded import USERNAME_PATTERNS, BIO_PATTERNS

            admin_id = CONFIG.get("ADMIN_ID", 0)
            whitelist_cfg = CONFIG.get("AD_WHITELIST", {})
            whitelist_uids = set(whitelist_cfg.get("user_ids", []) if isinstance(whitelist_cfg, dict) else [])

            total_banned = 0
            total_scanned = 0

            for chat_id in group_ids:
                try:
                    admins = bot.get_chat_administrators(chat_id)
                    admin_ids = {a.user.id for a in admins}
                    admin_ids.add(bot.get_me().id)
                except Exception as e:
                    logger.warning(f"auto_task 获取管理员失败，降级空集合: {e}")
                    admin_ids = set()
                    try:
                        admin_ids.add(bot.get_me().id)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                all_uids = set()
                uid_queries = [
                    "SELECT uid FROM users",
                    "SELECT user_id FROM group_join_log",
                    "SELECT user_id FROM ad_suspicious_users",
                    "SELECT uid FROM user_levels",
                    "SELECT DISTINCT uid FROM speech_daily",
                    "SELECT DISTINCT uid FROM deleted_messages",
                    "SELECT DISTINCT uid FROM checkin_records",
                    "SELECT DISTINCT uid FROM points_log",
                    "SELECT uid FROM user_tags",
                    "SELECT uid FROM user_notes",
                    "SELECT DISTINCT uid FROM achievements",
                    "SELECT DISTINCT uid FROM redpacket_claims",
                    "SELECT DISTINCT uid FROM lottery_participants",
                ]
                for query in uid_queries:
                    try:
                        rows = db.conn.execute(query).fetchall()
                        for row in rows:
                            uid = row[0]
                            if uid and isinstance(uid, int) and uid > 0:
                                all_uids.add(uid)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                try:
                    gm_rows = db.conn.execute("SELECT uid FROM group_members WHERE chat_id=?", (chat_id,)).fetchall()
                    for row in gm_rows:
                        all_uids.add(row[0])
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
                logger.info(f"[启动扫描] 群{chat_id}: 聚合{len(all_uids)}个用户ID")

                for uid in all_uids:
                    if uid in admin_ids or uid in whitelist_uids:
                        continue

                    try:
                        member = bot.get_chat_member(chat_id, uid)
                        if member.status in ("left", "kicked"):
                            continue
                        user = member.user
                        if user.is_bot:
                            continue
                    except Exception as e:
                        logger.debug(f"auto_task 扫描成员跳过: {e}")
                        continue

                    total_scanned += 1
                    user_name = (user.first_name or "") + (user.last_name or "")
                    tg_username = getattr(user, 'username', None) or ""

                    uname_score = 0
                    for pat in USERNAME_PATTERNS:
                        try:
                            if re.search(pat, user_name + (" @" + tg_username if tg_username else ""), re.IGNORECASE):
                                uname_score += 2
                                break
                        except Exception as e:
                            logger.debug(f"操作异常: {e}")
                    if tg_username and re.match(r'^[a-z]{1,4}\d{2,4}$', tg_username, re.IGNORECASE):
                        uname_score += 2

                    bio_text = ""
                    try:
                        chat_info = bot.get_chat(user.id)
                        bio_text = getattr(chat_info, 'bio', None) or ""
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                    bio_score = 0
                    if bio_text:
                        for pat in BIO_PATTERNS:
                            try:
                                if re.search(pat, bio_text, re.IGNORECASE):
                                    bio_score += 3
                                    break
                            except Exception as e:
                                logger.debug(f"操作异常: {e}")
                    should_ban = False
                    ban_reason = ""

                    if uname_score >= 1 and bio_score >= 3:
                        should_ban = True
                        ban_reason = f"两层组合(用户名+Bio)"

                    if should_ban:
                        try:
                            # [Codex] 广告治理策略：永久禁言+黑名单+删消息，不踢人
                            from modules.ad_enforcement import enforce_ad_user
                            enforce_ad_user(
                                bot=bot,
                                db=db,
                                config=CONFIG,
                                chat_id=chat_id,
                                uid=user.id,
                                uname=user_name,
                                reason=f"启动扫描-{ban_reason}",
                                notify_admin=False,
                            )
                            total_banned += 1
                            logger.warning(f"[启动扫描] 🚫 永久禁言: {user_name}({user.id}) {ban_reason}")
                        except Exception as e:
                            logger.debug(f"[启动扫描] 封禁失败 {user_name}({user.id}): {e}")

                    if total_scanned % 30 == 0:
                        time.sleep(1.5)

            if admin_id and (total_banned > 0 or total_scanned > 0):
                try:
                    bot.send_message(admin_id,
                        f"🔍 启动扫描完成\n"
                        f"📊 扫描群组：{len(group_ids)}个\n"
                        f"👥 检查成员：{total_scanned}人\n"
                        f"🚫 封禁广告号：{total_banned}人")
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
            logger.info(f"[启动扫描] 完成：扫描{len(group_ids)}群/{total_scanned}人，封禁{total_banned}人")
    except _TaskAbort as e:
        _handle_task_abort("startup_member_scan", e)
    except Exception as e:
        logger.error(f"启动成员扫描失败：{e}")


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
        group_ids = _get_all_group_ids(config)
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


def _job_health_check(rm):
    """【v4.9.1】任务健康检查 - 检查关键任务是否按时执行 + 数据库锁审计 + 并发异常检测"""
    try:
        now = datetime.now(_CST)
        current_hour = now.hour
        today = now.strftime("%Y-%m-%d")
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            logger.warning("⚠️ [health_check] ADMIN_ID为空，跳过健康检查")
            return

        logger.info(f"🏥 [health_check] 开始检查，当前时间{current_hour}:00，检查日期{today}")

        missed = []
        for task in _build_critical_tasks(rm.config, today):
            task_desc = task["desc"]
            deadline_hour = task["deadline_hour"]
            deadline_minute = task["deadline_minute"]
            if not _is_deadline_reached(now, deadline_hour, deadline_minute):
                logger.debug(f"🏥 [health_check] {task_desc} 未到截止时间({deadline_hour:02d}:{deadline_minute:02d})，跳过")
                continue
            missing_keys = _missing_task_keys_today(rm.db, task.get("keys", []))
            if missing_keys:
                suffix = ""
                if len(missing_keys) <= 3:
                    suffix = f"：{', '.join(missing_keys)}"
                else:
                    suffix = f"：缺失 {len(missing_keys)} 个目标"
                missed.append(f"• {task_desc}（应在{deadline_hour:02d}:{deadline_minute:02d}前执行）{suffix}")
                logger.info(f"🏥 [health_check] ❌ {task_desc} 今日未执行完整: {missing_keys[:5]}")
            else:
                logger.debug(f"🏥 [health_check] ✅ {task_desc} 今日已执行")

        anomalies = _task_guard.audit_task_log(rm.db)

        parts = []
        if missed:
            parts.append(f"⚠️ <b>任务未执行</b>\n" + "\n".join(missed))
        if anomalies:
            parts.append(f"🚨 <b>任务防重记录异常</b>\n" + "\n".join(anomalies))

        if parts:
            msg = f"🏥 <b>任务健康检查</b> · {today}\n\n" + "\n\n".join(parts)
            try:
                with rm.locked('bot'):
                    rm.bot.send_message(admin_id, msg, parse_mode="HTML")
                logger.warning(f"⚠️ [health_check] 发现异常，已通知管理员")
            except Exception as e:
                logger.error(f"⚠️ [health_check] 通知发送失败：{e}")
                raise
        else:
            logger.info(f"✅ [health_check] 所有关键任务仅正常执行，数据库无异常")
    except Exception as e:
        logger.error(f"❌ [health_check] 健康检查失败：{e}")
        raise


# ── 【v4.13.1新增】夜间模式定时任务 ───────────────────────────────────
def _job_night_mode_start(rm):
    """夜间模式开启"""
    try:
        # 【v5.31.2 修复】task_key 加日期后缀，避免 UNIQUE 索引拦截当日重试
        _today = datetime.now(_CST).strftime("%Y-%m-%d")
        with TaskTransactionManager(f"night_mode_start_{_today}", rm.db, resources=None, min_interval_sec=3600) as tx:
            if not tx.claimed:
                return
            from modules.night_mode import start_night_mode
            gid = rm.config.get("GROUP_ID", 0)
            if gid:
                start_night_mode(rm.bot, gid, rm.config)
            else:
                raise _TaskAbort("GROUP_ID为0")
    except _TaskAbort as e:
        _handle_task_abort("night_mode_start", e)
    except Exception as e:
        logger.error(f"🌙 夜间模式开启失败: {e}")


def _job_night_mode_end(rm):
    """夜间模式关闭"""
    try:
        # 【v5.31.2 修复】task_key 加日期后缀，避免 UNIQUE 索引拦截当日重试
        _today = datetime.now(_CST).strftime("%Y-%m-%d")
        with TaskTransactionManager(f"night_mode_end_{_today}", rm.db, resources=None, min_interval_sec=3600) as tx:
            if not tx.claimed:
                return
            from modules.night_mode import end_night_mode
            gid = rm.config.get("GROUP_ID", 0)
            if gid:
                end_night_mode(rm.bot, gid, rm.config)
            else:
                raise _TaskAbort("GROUP_ID为0")
    except _TaskAbort as e:
        _handle_task_abort("night_mode_end", e)
    except Exception as e:
        logger.error(f"☀️ 夜间模式关闭失败: {e}")


# ── 【v4.13.1新增】定点播报注册 ─────────────────────────────────────
def _register_scheduled_broadcasts(scheduler, rm):
    """根据config注册定点播报任务"""
    from modules.scheduled_broadcast import get_broadcast_schedule, execute_scheduled_broadcast
    schedule = get_broadcast_schedule(rm.config)
    gid = rm.config.get("GROUP_ID", 0)

    for bc in schedule:
        bc_id = bc.get("id", "")
        if not bc_id:
            continue

        hour = bc.get("hour")
        minute = bc.get("minute")
        if hour is None or minute is None:
            continue

        cron_kwargs = {"hour": hour, "minute": minute, "args": [rm, gid, bc_id],
                       "id": f"broadcast_{bc_id}", "max_instances": 1,
                       "coalesce": True, "misfire_grace_time": 300}

        # 周几执行
        if bc.get("day_of_week") is not None:
            cron_kwargs["day_of_week"] = bc["day_of_week"]
        # 几号执行
        if bc.get("day_of_month") is not None:
            cron_kwargs["day"] = bc["day_of_month"]

        scheduler.add_job(_job_scheduled_broadcast, "cron", **cron_kwargs)
        logger.info(f"📢 注册定点播报: {bc_id} ({hour:02d}:{minute:02d})")


_COMMERCIAL_BROADCAST_MARKERS = (
    "下单", "订阅", "购买", "价格", "福利", "内容",
    "morychannelbot", "fansone",
)


def _build_reply_contract_broadcast_config(config: dict) -> dict:
    """给旧定点播报做发送前适配：成交类只保留一个预览目标。"""
    safe = copy.deepcopy(config) if isinstance(config, dict) else {}
    # 旧模块的随机变体会编造刚起床、喝咖啡、洗澡等生活场景。
    safe["BROADCAST_TEMPLATE_VARIATION_ENABLED"] = False
    broadcasts = safe.get("SCHEDULED_BROADCASTS", [])
    if not isinstance(broadcasts, list):
        return safe
    for item in broadcasts:
        if not isinstance(item, dict):
            continue
        combined = " ".join(str(item.get(key, "") or "") for key in (
            "content", "footer", "button_text", "button_url",
        )).lower()
        if not any(marker in combined for marker in _COMMERCIAL_BROADCAST_MARKERS):
            continue
        for key in ("content", "footer"):
            value = str(item.get(key, "") or "")
            value = value.replace("@MorychannelBot", "@moryselect")
            value = value.replace("@morychannelbot", "@moryselect")
            item[key] = value
        item["button_text"] = "🎞 查看当前预览"
        item["button_url"] = "https://t.me/moryselect"
    return safe


def _job_scheduled_broadcast(rm, chat_id, broadcast_id):
    """执行定点播报（多群遍历）

    【v5.31.0 修复 Bug C】移除外层 TaskTransactionManager（双层 claim 冗余），
    只依赖 execute_scheduled_broadcast 内层 claim（task_key 带 chat_id + 日期）。
    外层 broadcast_{id} 无日期后缀曾导致 task_log 残留→claim_task 永久失败→播报全灭。
    【v5.31.0 修复 Bug D】多群遍历（GROUP_ID + MANAGED_GROUPS）支持多联排。
    chat_id 参数保留兼容 cron 注册签名，实际使用 _get_all_group_ids 遍历。
    """
    try:
        from modules.scheduled_broadcast import execute_scheduled_broadcast
        group_ids = _get_all_group_ids(rm.config)
        if not group_ids:
            logger.warning(f"⚠️ 定点播报 {broadcast_id} 无管理群，跳过")
            return
        for gid in group_ids:
            try:
                safe_config = _build_reply_contract_broadcast_config(rm.config)
                execute_scheduled_broadcast(
                    rm.bot, gid, safe_config, rm.db,
                    target_broadcast_id=broadcast_id,
                    ai_engine=getattr(rm, "ai", None),
                )
            except Exception as e:
                logger.warning(f"📢 定点播报 {broadcast_id} 发送到群 {gid} 失败: {e}")
                # [v5.38.21] 发送终态失败后当天安排一次延迟重试（5 分钟后），
                # 避免瞬时网络/Telegram 抖动导致当天播报永久缺失。
                _retry_task(
                    rm,
                    lambda rm_inner: _job_scheduled_broadcast(rm_inner, gid, broadcast_id),
                    f"scheduled_broadcast_{broadcast_id}_{gid}",
                )
    except Exception as e:
        logger.error(f"📢 定点播报执行失败 {broadcast_id}: {e}")


def _job_rbac_audit(rm):
    """[阶段3-E] 每月 RBAC 权限审计：扫描 user_roles + permission_change_requests，输出报告到 logs/"""
    try:
        # 配置开关：RBAC_APPROVAL_ENABLED 关闭时也允许审计（只读操作，无副作用）
        audit_day = rm.config.get("RBAC_AUDIT_DAY_OF_MONTH", 1)
        now = datetime.now(_CST)
        # 仅在配置指定的日期执行（默认每月 1 日）
        if now.day != int(audit_day):
            logger.debug(f"[RBAC审计] 今日 {now.day} 日，非审计日（配置: {audit_day} 日），跳过")
            return

        logger.info(f"[RBAC审计] 开始执行权限审计 ({now.strftime('%Y-%m-%d %H:%M')})")

        # 收集审计数据（复用 dashboard.rbac_approval 的数据收集函数）
        audit_data = None
        try:
            # 用独立连接查询，避免与 Bot 进程的 db 单例冲突
            import sqlite3
            _mory_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            _mode = os.environ.get("DASHBOARD_MODE", "main")
            _db_name = "mory_media.db" if _mode == "media" else "mory.db"
            _db_path = os.path.join(_mory_root, _db_name)
            if not os.path.exists(_db_path):
                logger.warning(f"[RBAC审计] 数据库不存在: {_db_path}，跳过")
                return
            _conn = sqlite3.connect(_db_path, timeout=30.0)
            _conn.row_factory = sqlite3.Row
            try:
                audit_data = _collect_rbac_audit_data(_conn)
            finally:
                _conn.close()
        except Exception as e:
            logger.error(f"[RBAC审计] 收集数据失败: {e}")
            return

        if not audit_data:
            logger.warning("[RBAC审计] 未收集到数据，跳过报告生成")
            return

        # 生成报告
        report_path = _write_rbac_audit_report(audit_data, now)
        logger.info(f"[RBAC审计] 报告已生成: {report_path}")

        # 通过告警 Bot 发送审计摘要（可选）
        try:
            from core.alert_bot import send_alert
            role_counts = audit_data.get("role_counts", {})
            orphan_count = len(audit_data.get("orphan_permissions", []))
            recent_count = len(audit_data.get("recent_changes", []))
            summary = (
                f"RBAC 月度审计完成\n"
                f"角色分布: admin={role_counts.get('admin', 0)} "
                f"operator={role_counts.get('operator', 0)} "
                f"viewer={role_counts.get('viewer', 0)}\n"
                f"近30天变更申请: {recent_count} 条\n"
                f"孤儿权限: {orphan_count} 条\n"
                f"报告路径: {report_path}"
            )
            send_alert("INFO", "RBAC 月度审计摘要", summary)
        except Exception as e:
            logger.debug(f"[RBAC审计] 告警 Bot 推送失败（非致命）: {e}")

    except Exception as e:
        logger.error(f"[RBAC审计] 任务异常: {e}")


def _collect_rbac_audit_data(db) -> dict:
    """[阶段3-E] 收集 RBAC 审计数据（独立连接版本，供定时任务使用）"""
    result = {
        "role_counts": {"admin": 0, "operator": 0, "viewer": 0},
        "recent_changes": [],
        "orphan_permissions": [],
        "total_users": 0,
    }
    try:
        # 幂等确保 user_roles 表存在
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'viewer',
                assigned_by TEXT,
                assigned_at TIMESTAMP
            )
        """)
        db.commit()

        # 1. 各角色用户数
        cur = db.execute("SELECT role, COUNT(*) FROM user_roles GROUP BY role")
        for role, cnt in cur.fetchall():
            if role in result["role_counts"]:
                result["role_counts"][role] = cnt

        # 2. user_roles 总数
        result["total_users"] = db.execute("SELECT COUNT(*) FROM user_roles").fetchone()[0]

        # 3. 最近 30 天权限变更申请
        cutoff_ts = datetime.now(_CST).timestamp() - 30 * 86400
        cutoff_str = datetime.fromtimestamp(cutoff_ts, _CST).isoformat()
        rows = db.execute(
            """SELECT * FROM permission_change_requests
               WHERE created_at >= ?
               ORDER BY created_at DESC LIMIT 200""",
            (cutoff_str,),
        ).fetchall()
        result["recent_changes"] = [dict(r) for r in rows]

        # 4. 孤儿权限：user_roles 有记录但 users 表无此 uid
        rows = db.execute(
            """SELECT ur.user_id, ur.role, ur.assigned_by, ur.assigned_at
               FROM user_roles ur
               LEFT JOIN users u ON ur.user_id = u.uid
               WHERE u.uid IS NULL"""
        ).fetchall()
        result["orphan_permissions"] = [dict(r) for r in rows]

    except Exception as e:
        logger.error(f"[RBAC审计] 收集数据异常: {e}")
    return result


def _write_rbac_audit_report(audit_data: dict, now: datetime) -> str:
    """[阶段3-E] 生成 RBAC 审计报告 Markdown 文件，返回绝对路径"""
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    try:
        os.makedirs(logs_dir, exist_ok=True)
    except Exception as e:
        logger.warning(f"[RBAC审计] 创建 logs 目录失败: {e}")

    date_str = now.strftime("%Y%m%d")
    report_path = os.path.join(logs_dir, f"rbac_audit_report_{date_str}.md")

    role_counts = audit_data.get("role_counts", {})
    recent_changes = audit_data.get("recent_changes", [])
    orphans = audit_data.get("orphan_permissions", [])
    total_users = audit_data.get("total_users", 0)

    lines = []
    lines.append(f"# RBAC 权限审计报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {now.strftime('%Y-%m-%d %H:%M:%S')} (CST)")
    lines.append(f"**审计范围**: user_roles 表 + permission_change_requests 表（最近 30 天）")
    lines.append(f"")
    lines.append(f"## 1. 角色分布")
    lines.append(f"")
    lines.append(f"| 角色 | 用户数 |")
    lines.append(f"|------|--------|")
    for role in ("admin", "operator", "viewer"):
        lines.append(f"| {role} | {role_counts.get(role, 0)} |")
    lines.append(f"| **合计** | {total_users} |")
    lines.append(f"")
    lines.append(f"## 2. 最近 30 天权限变更申请（{len(recent_changes)} 条）")
    lines.append(f"")
    if recent_changes:
        lines.append(f"| ID | 申请人 | 被授权用户 | 申请角色 | 状态 | 审批人 | 创建时间 |")
        lines.append(f"|----|--------|-----------|---------|------|--------|---------|")
        for r in recent_changes[:50]:
            lines.append(
                f"| {r.get('id', '')} | {r.get('requester_id', '')} | "
                f"{r.get('target_user_id', '')} | {r.get('requested_role', '')} | "
                f"{r.get('status', '')} | {r.get('approver_id', '') or '-'} | "
                f"{r.get('created_at', '')} |"
            )
        if len(recent_changes) > 50:
            lines.append(f"")
            lines.append(f"> 仅显示前 50 条，共 {len(recent_changes)} 条")
    else:
        lines.append(f"无变更记录")
    lines.append(f"")
    lines.append(f"## 3. 孤儿权限（user_roles 有记录但 users 表无此用户）")
    lines.append(f"")
    if orphans:
        lines.append(f"| user_id | 角色 | 授权者 | 授权时间 |")
        lines.append(f"|---------|------|--------|---------|")
        for o in orphans:
            lines.append(
                f"| {o.get('user_id', '')} | {o.get('role', '')} | "
                f"{o.get('assigned_by', '') or '-'} | {o.get('assigned_at', '') or '-'} |"
            )
    else:
        lines.append(f"无孤儿权限")
    lines.append(f"")
    lines.append(f"## 4. 建议清理项")
    lines.append(f"")
    suggestions = []
    if orphans:
        suggestions.append(f"- 清理 {len(orphans)} 条孤儿权限（user_roles 中存在但 users 表无此用户）")
    admin_count = role_counts.get("admin", 0)
    if admin_count > 3:
        suggestions.append(f"- admin 角色用户数 {admin_count} 偏多，建议核查是否必要")
    if not suggestions:
        suggestions.append("- 无需清理")
    lines.extend(suggestions)
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*本报告由 _job_rbac_audit 自动生成*")

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logger.error(f"[RBAC审计] 写报告失败: {e}")
        return ""
    return report_path


def _job_sync_user_lifecycle_buckets(rm):
    """[v5.26.0] 同步用户生命周期阶段标签（每日凌晨 2:00）"""
    try:
        from core.user_lifecycle import UserLifecycleManager
        mgr = UserLifecycleManager(rm.db)
        dist = mgr.sync_lifecycle_buckets()
        logger.info(f"用户生命周期同步完成: {dist}")
    except Exception as e:
        logger.error(f"用户生命周期同步失败：{e}")


def start_background(bot, config: Dict[str, Any], db, ai, save_config_fn):
    """启动后台任务引擎（v5.31.x 重构后使用 TaskScheduler）"""
    # 【v4.9.3】防重入保护：避免重复启动导致多个scheduler实例并发调度
    global _scheduler_instance
    if _scheduler_instance is not None and getattr(_scheduler_instance, 'running', False):
        logger.warning("⚠️ 后台任务引擎已在运行，跳过重复启动")
        return

    rm = ResourceManager(bot=bot, ai=ai, db=db, config=config, save_config_fn=save_config_fn)
    TaskTransactionManager.bind(rm)
    _task_guard.bind(rm)
    _fault_reporter.bind(rm)

    if HAS_APSCHEDULER:
        _start_with_task_scheduler(rm)
    else:
        # APScheduler 是必装依赖（requirements.lock），此分支永远不会执行
        raise RuntimeError("APScheduler 未安装，请运行 pip install apscheduler")


def _start_with_task_scheduler(rm):
    """新调度器入口：自动发现并注册 tasks/ 下所有任务。"""
    global _scheduler_instance
    from tasks.task_scheduler import create_scheduler

    scheduler = create_scheduler(rm)
    _scheduler_instance = scheduler.scheduler

    # 场景化触发器注册（默认关闭，需 config 开启）
    from modules.triggers.cold_group import ColdGroupTrigger
    from modules.triggers.night_hint import NightHintTrigger
    ColdGroupTrigger().register(_scheduler_instance, rm)
    NightHintTrigger().register(_scheduler_instance, rm)

    # 附加调度监控（监听 EXECUTED/ERROR/MISSED 事件）
    from core.scheduler_monitor import attach_to_scheduler
    attach_to_scheduler(_scheduler_instance, db=rm.db)

    # 注册/监控均成功后才启动并落跨进程心跳，再异步执行耗时的全员扫描。
    # 否则数千人的 Telegram API 调用会在 scheduler.start() 前阻塞数分钟，
    # Dashboard 将旧心跳判为 503，外部 watchdog 还会形成误重启循环。
    scheduler.start()
    _persist_startup_heartbeat(rm)

    # 看门狗必须在 scheduler 与首个持久心跳成功后启动，失败则阻止残缺服务继续。
    from tasks.monitoring.watchdog_task import WatchdogTask
    WatchdogTask(rm).start(timeout_sec=_WATCHDOG_TIMEOUT_SEC)
    _start_startup_maintenance(rm)


def _persist_startup_heartbeat(rm):
    """启动扫描前立即写入内存与数据库心跳。"""
    now = int(time.time())
    from tasks.monitoring.heartbeat_task import update_heartbeat
    update_heartbeat()
    rm.db.set_system_state("last_heartbeat", str(now))


def _run_startup_maintenance(rm):
    """后台串行执行启动扫描和历史清理，不阻塞 scheduler/polling。"""
    try:
        from tasks.maintenance.startup_member_scan_task import StartupMemberScanTask
        StartupMemberScanTask(rm).run()
    except Exception as e:
        logger.warning(f"启动成员扫描失败: {e}")

    try:
        from tasks.maintenance.startup_history_cleanup_task import StartupHistoryCleanupTask
        StartupHistoryCleanupTask(rm).run()
    except Exception as e:
        logger.warning(f"启动历史清理失败: {e}")


def _start_startup_maintenance(rm):
    """启动唯一的后台维护线程；返回线程供测试与诊断。"""
    global _startup_maintenance_thread
    if _startup_maintenance_thread is not None and _startup_maintenance_thread.is_alive():
        logger.warning("启动维护线程已在运行，跳过重复启动")
        return _startup_maintenance_thread
    _startup_maintenance_thread = threading.Thread(
        target=_run_startup_maintenance,
        args=(rm,),
        name="mory-startup-maintenance",
        daemon=True,
    )
    _startup_maintenance_thread.start()
    return _startup_maintenance_thread
