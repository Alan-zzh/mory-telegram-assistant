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
║    2. 早/午/晚安问候（8:00/12:30/23:00）                             ║
║    3. 叫醒服务（每分钟检查）                                           ║
║    4. 阅后即焚探测（每3分钟一次）                                      ║
║    5. 阅后即焚孤儿清理（每小时一次）                                   ║
║    6. 醋意挽回（每小时一次）                                           ║
║    7. 购物车挽回（每小时一次）                                         ║
║    8. 背刺泄密（每周一次）                                             ║
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
import threading
import html
from typing import Any, Dict
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from core.telegram_stats import get_group_daily_stats, get_channel_daily_stats, test_api_availability

logger = get_logger("auto_tasks")

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

_last_task_run = {}
_task_lock = threading.Lock()

_scheduler_instance = None


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
    
    防刷机制：同类故障5分钟内不重复通知
    兜底机制：Telegram通知失败时写入本地 fault_alerts.log，下次成功时补发
    """
    _DEDUP_SEC = 300
    _ALERT_FILE = "fault_alerts.log"
    _MAX_PENDING = 50

    def __init__(self):
        self._rm = None
        self._last_alert = {}
        self._lock = threading.Lock()
        self._pending = []

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
        with self._lock:
            if dedup_key in self._last_alert and now - self._last_alert[dedup_key] < self._DEDUP_SEC:
                logger.debug(f"[FaultReporter] 去重跳过：{category}")
                return
            self._last_alert[dedup_key] = now

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
            _task_guard.record_claim_fail(task_name, "内存锁拦截")
            return False
    try:
        result = db.claim_task(task_name)
        if not result:
            logger.info(f"🔒 [{task_name}] 数据库锁拦截（今日已执行或被其他线程抢占）")
            _task_guard.record_claim_fail(task_name, "数据库锁拦截")
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
    注意：已被_try_claim_task替代，保留以兼容旧代码
    """
    now = int(time.time())
    with _task_lock:
        last = _last_task_run.get(task_name, 0)
        if now - last < min_interval_sec:
            logger.debug(f"⏳ 任务{task_name}跳过，距离上次运行{now-last}秒 < {min_interval_sec}秒")
            return False
        return True


def _mark_done(task_name: str):
    """标记任务为已成功完成（仅在实际成功后调用）"""
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


def _prepare_news_lines(raw_news: str, source_hint: str = "", limit: int = 5) -> list[str]:
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


def _get_preferred_news_lines(time_desc: str) -> tuple[list[str], str]:
    """优先用 TrendRadar，失败后再降级到原多源新闻"""
    from core.trendradar_news import fetch_trendradar_news
    from core.ai_engine import fetch_real_news

    trendradar_news = fetch_trendradar_news() or ""
    lines = _prepare_news_lines(trendradar_news, f"{time_desc}新闻-TrendRadar")
    if lines:
        return lines, "trendradar"

    raw_news = fetch_real_news() or ""
    lines = _prepare_news_lines(raw_news, f"{time_desc}新闻-多源热点")
    if lines:
        return lines, "fallback"

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


def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息并追踪浏览量（主动消息也入库channel_tracking）"""
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        if sent and hasattr(sent, 'message_id'):
            _schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
            if chat_id < 0:
                rm.db.track_channel_message(chat_id, sent.message_id, "text")
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


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
        with rm.locked('bot'):
            rm.bot.delete_message(chat_id, message_id)
        logger.info(f"🗑️ 定时消息已自动删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"定时消息删除失败（可能已被手动删除）: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _execute_news_task(rm, task_name: str, time_desc: str):
    """
    执行新闻播报任务的公共函数
    
    【v4.9.0】新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)
    """
    if not _try_claim_and_lock(task_name, rm.db, 7200):
        return
    
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            _release_task(task_name, rm.db)
            return
        
        logger.info(f"📰 触发{time_desc}新闻播报（统一主流程）")
        seed = random.randint(100000, 999999)

        lines, source_name = _get_preferred_news_lines(time_desc)
        if not lines:
            logger.warning(f"{time_desc}新闻：所有源均失败，跳过发送")
            _notify_admin_news_failure(rm, f"{time_desc}新闻")
            _release_task(task_name, rm.db)
            return
        news_input = "\n".join(lines)

        ai_mode = _build_news_ai_mode(time_desc, source_name)
        with rm.locked('ai'):
            news = rm.ai.ask(news_input, mode=ai_mode, seed=seed)

        if news:
            sent = _send_and_track(rm, gid, news)
            if sent:
                _remember_news_lines(lines)
                _confirm_task_done(task_name, rm.db, 7200)
                logger.info(f"✅ {time_desc}新闻已发送（来源: {source_name}）")
                return
        _release_task(task_name, rm.db)
    except Exception as e:
        logger.error(f"{time_desc}新闻播报失败：{e}")
        _release_task(task_name, rm.db)
        _retry_task(rm, lambda rm: _execute_news_task(rm, task_name, time_desc), task_name)


# ═══════════════════════════════════════════════════════════════════════════
# APScheduler 版本：独立 Job，互不干扰
# ═══════════════════════════════════════════════════════════════════════════

def _job_news_morning(rm):
    """早间新闻播报（9:00）"""
    _execute_news_task(rm, "news_morning", "早间")


def _job_news_afternoon(rm):
    """午间新闻播报（13:00）"""
    _execute_news_task(rm, "news_afternoon", "午间")


def _job_news_evening(rm):
    """晚间新闻播报（20:35）"""
    _execute_news_task(rm, "news_evening", "晚间")


def _job_trendradar_morning(rm):
    """旧的TrendRadar早间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_morning 已并入 news_morning 统一主流程")


def _job_trendradar_noon(rm):
    """旧的TrendRadar午间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_noon 已并入 news_afternoon 统一主流程")


def _job_trendradar_evening(rm):
    """旧的TrendRadar晚间播报入口已停用，保留函数仅兼容历史调用"""
    logger.info("ℹ️ trendradar_evening 已并入 news_evening 统一主流程")


def _job_greeting_morning(rm):
    """早安问候（8:00）"""
    if not _try_claim_and_lock("greeting_morning", rm.db, 7200):
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            _release_task("greeting_morning", rm.db)
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("早安", mode="morning", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            unban_hint = "\n\n🆘 误封或有问题？私聊我，Mory秒帮你处理～"
            sent = _send_and_track(rm, gid, f"☀️ {msg}{unban_hint}")
            if sent:
                _confirm_task_done("greeting_morning", rm.db, 7200)
                logger.info(f"☀️ 早安已发送：{msg}")
                return
        _release_task("greeting_morning", rm.db)
    except Exception as e:
        logger.error(f"早安问候失败：{e}")
        _release_task("greeting_morning", rm.db)
        _retry_task(rm, _job_greeting_morning, "greeting_morning")


def _job_greeting_afternoon(rm):
    """午安问候（12:30）"""
    if not _try_claim_and_lock("greeting_afternoon", rm.db, 7200):
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            _release_task("greeting_afternoon", rm.db)
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("午安", mode="afternoon", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            unban_hint = "\n\n🆘 误封或有问题？私聊我，Mory秒帮你处理～"
            sent = _send_and_track(rm, gid, f"🍃 {msg}{unban_hint}")
            if sent:
                _confirm_task_done("greeting_afternoon", rm.db, 7200)
                logger.info(f"🍃 午安已发送：{msg}")
                return
        _release_task("greeting_afternoon", rm.db)
    except Exception as e:
        logger.error(f"午安问候失败：{e}")
        _release_task("greeting_afternoon", rm.db)
        _retry_task(rm, _job_greeting_afternoon, "greeting_afternoon")


def _job_greeting_evening(rm):
    """晚安问候（23:00）"""
    if not _try_claim_and_lock("greeting_evening", rm.db, 7200):
        return
    try:
        with rm.locked('config'):
            gid = rm.config.get("GROUP_ID", 0)
        if gid == 0:
            _release_task("greeting_evening", rm.db)
            return
        
        seed = random.randint(100000, 999999)
        with rm.locked('ai'):
            msg = rm.ai.ask("晚安", mode="evening", seed=seed)
        if msg:
            msg = msg.replace("\n", " ").strip()[:250]
            unban_hint = "\n\n🆘 误封或有问题？私聊我，Mory秒帮你处理～"
            sent = _send_and_track(rm, gid, f"🌙 {msg}{unban_hint}")
            if sent:
                _confirm_task_done("greeting_evening", rm.db, 7200)
                logger.info(f"🌙 晚安已发送：{msg}")
                return
        _release_task("greeting_evening", rm.db)
    except Exception as e:
        logger.error(f"晚安问候失败：{e}")
        _release_task("greeting_evening", rm.db)
        _retry_task(rm, _job_greeting_evening, "greeting_evening")


def _generate_wakeup_message(uid: int, now: datetime, rm) -> str:
    """AI生成个性化叫醒语"""
    seed = uid + int(now.timestamp())
    hour = now.hour
    
    prompt = f"""你是Mory老板，一个贴心的小姐姐。现在是北京时间{hour}点。

给用户生成一条叫醒消息，要求：
1. 30-50字，撒娇撩人风格
2. 像闺蜜私聊一样自然
3. 随机选择一个场景/理由叫醒他
4. 结尾要有emoji
5. seed={seed}，每次必须不同

禁止：
- 不要太长，控制在50字以内
- 不要重复相同的开头"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="wakeup", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception:
        pass
    
    # 备用文案
    fallbacks = [
        "起床啦哥哥～ 太阳晒屁股了，新的一天也要充满活力哦！☀️",
        "嘿～该起来啦！再睡就要错过好运了哦～🌞",
        "哥哥醒醒～小Mory都醒了，你还在赖床吗？快起来嘛～💪",
        "早安呀哥哥！新的一天，新的运气，快起来迎接美好吧～✨",
    ]
    return random.choice(fallbacks)


def _job_wakeup_check(rm):
    """叫醒服务检查（每分钟）- AI生成个性化叫醒语"""
    try:
        now = datetime.now(_CST)
        time_str = now.strftime("%H:%M")
        
        with rm.locked_multi(['db', 'bot', 'config']):
            for uid, wake_time in rm.db.get_all_wake_ups():
                if wake_time == time_str:
                    try:
                        wake_msg = _generate_wakeup_message(uid, now, rm)
                        rm.bot.send_message(uid, wake_msg)
                        logger.info(f"⏰ 叫醒服务：uid={uid}")
                    except Exception as e:
                        logger.warning(f"叫醒服务发送失败 uid={uid}：{e}")
    except Exception as e:
        logger.error(f"叫醒服务检查失败：{e}")


def _job_burn_probe(rm):
    """
    【v4.5.35彻底废弃】阅后即焚探测已完全移除

    原因：
    1. forward_message探测会触发Telegram 429限流
    2. main.py的global_reply_sniffer已实时标记replied=1
    3. _job_burn_orphan的Phase1 TTL清理已足够处理孤儿消息
    4. 此函数保留空实现仅兼容旧版循环调用，APScheduler中已移除调度
    """
    pass


def _job_burn_orphan(rm):
    """阅后即焚孤儿清理（每10分钟）
    
    两阶段清理：
    Phase 1: 清理超过30分钟未回复的孤儿消息（直接删除Bot回复）
    Phase 2: 探测5-30分钟内的未回复消息，检测用户是否已删原消息
    """
    try:
        # ── Phase 1: 清理超时孤儿（24小时窗口）──
        logger.info("🔍 [Phase1] 检查超时孤儿消息...")
        orphans = rm.db.get_orphan_messages(86400)
        if orphans:
            logger.info(f"🗑️ 发现{len(orphans)}条超时孤儿（>24小时未回复），开始清理...")
            success_count = 0
            fail_count = 0
            for bot_mid, cid, user_mid in orphans:
                try:
                    with rm.locked('bot'):
                        rm.bot.delete_message(cid, int(bot_mid))
                    success_count += 1
                except Exception as del_err:
                    fail_count += 1
                    logger.debug(f"  删除失败：bot_mid={bot_mid}, err={del_err}")
                rm.db.delete_tracked(bot_mid, cid)
            logger.info(f"✅ Phase1完成：成功{success_count}条，失败{fail_count}条")
        else:
            logger.info("✅ Phase1：无超时孤儿")

        # ── Phase 2: 探测用户是否删了原消息 ──
        # 【v4.5.35修复】Phase2 forward探测已废弃，原因：
        # 1. forward_message探测会触发Telegram 429限流
        # 2. 用户删原消息后Bot回复变成"回复了一条不存在消息"，不影响功能
        # 3. Phase1的24小时TTL清理已足够处理孤儿消息
        # 4. 保留Phase1清理，Phase2改为仅记录日志不执行探测
        logger.info("✅ [Phase2] 已跳过forward探测（v4.5.35废弃），依赖Phase1 TTL清理")

    except Exception as e:
        logger.error(f"❌ 阅后即焚孤儿清理失败：{e}", exc_info=True)


def _generate_reactivate_message(uid: int, rm) -> str:
    """AI生成醋意挽回消息"""
    seed = uid + int(time.time()) // 86400  # 每天固定
    
    prompt = f"""你是Mory老板，一个有点小醋意的小姐姐。

一个用户已经3天没来聊天了，你要写一条消息把他叫回来。

要求：
1. 40-60字，撒娇吃醋风格
2. 像闺蜜私聊一样，带点小委屈小醋意
3. 不要太直白，要撩人要心痒痒
4. 可以暗示：你是不是有别人了/你是不是把我忘了/是不是我哪里不够好
5. 结尾要有emoji
6. seed={seed}，每次必须不同

禁止：
- 不要出现"3天"这个具体数字
- 不要太长，控制在60字以内"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="reactivate", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception:
        pass
    
    # 备用文案
    fallbacks = [
        "哥哥这几天去哪了呀？是不是有新欢了？Mory都想你了呢...快回来嘛～💕",
        "你是不是把人家忘了呀...好几天都不来找我，是不是外面有别的猫猫了？😢",
        "诶？哥哥是不是把我忘了...好伤心哦，有空回来陪Mory聊聊天嘛～🥺",
        "哼！都不来找我，是不是觉得我不可爱了？快回来让我看看你！👀",
    ]
    return random.choice(fallbacks)


def _job_reactivate(rm):
    """醋意挽回（每小时）- AI生成个性化消息"""
    if not _try_claim_and_lock("reactivate", rm.db, 3600):
        return
    try:
        ts = int(time.time())
        three_days_ago = ts - 259200
        
        with rm.locked_multi(['db', 'bot', 'config']):
            inactive = rm.db.get_inactive_users(three_days_ago, rm.config.get("ADMIN_ID", 0))
            sent_count = 0
            for uid, _name in inactive[:3]:
                if random.random() < 0.25:
                    try:
                        reactivate_msg = _generate_reactivate_message(uid, rm)
                        rm.bot.send_message(uid, reactivate_msg)
                        rm.db.reset_last_active(uid)
                        sent_count += 1
                        logger.info(f"💌 醋意挽回：{uid}")
                    except Exception as e:
                        err_str = str(e).lower()
                        if "chat not found" in err_str or "bot was blocked" in err_str or "forbidden" in err_str:
                            rm.db.delete_user(uid)
                            logger.debug(f"💔 醋意挽回跳过无效用户 uid={uid}（已清理）")
                        else:
                            logger.warning(f"醋意挽回发送失败 uid={uid}：{e}")
            if sent_count > 0:
                _confirm_task_done("reactivate", rm.db, 3600)
            else:
                _release_task("reactivate", rm.db)
    except Exception as e:
        logger.error(f"醋意挽回失败：{e}")
        _release_task("reactivate", rm.db)


def _generate_cart_recovery_message(uid: int, rm) -> str:
    """AI生成购物车挽回消息"""
    seed = uid + int(time.time()) // 43200  # 每半天固定
    
    prompt = f"""你是Mory老板，一个贴心的小姐姐。

一个用户昨天问了门槛/价格但没付费就走了，你要写一条消息把他叫回来。

要求：
1. 40-60字，撒娇但不卑微
2. 像闺蜜私聊一样自然撩人
3. 不要直接提"门槛"或"价格"，要隐晦表达
4. 可以暗示：是不是有什么顾虑/是不是钱不够/是不是不好意思
5. 要让人感觉来了会有好事发生
6. 结尾要有emoji
7. seed={seed}，每次必须不同

禁止：
- 不要出现"门槛"、"价格"、"付费"、"钱"这些词
- 不要太长，控制在60字以内"""

    try:
        with rm.locked('ai'):
            msg = rm.ai.ask(prompt, mode="cart_recovery", seed=seed)
        if msg and len(msg) > 10:
            return msg.strip()
    except Exception:
        pass
    
    # 备用文案
    fallbacks = [
        "哥哥昨天问完就跑了...是不是有什么顾虑呀？有什么想问的尽管问嘛，Mory帮你解答～😊",
        "是不是钱不够呀？没关系呀，先来聊聊天嘛～说不定有惊喜哦！💕",
        "哥哥昨天是不是不好意思呀？放心，Mory很温柔的，来嘛来嘛～🌸",
        "昨天问了就不理人家了...Mory可是专门在想哥哥呢，快回来嘛～✨",
    ]
    return random.choice(fallbacks)


def _job_cart_recovery(rm):
    """购物车挽回（每小时）- AI生成个性化消息"""
    if not _try_claim_and_lock("cart_recovery", rm.db, 3600):
        return
    try:
        with rm.locked_multi(['db', 'bot', 'config']):
            sent_count = 0
            for uid in rm.db.get_expired_carts(86400):
                try:
                    cart_msg = _generate_cart_recovery_message(uid, rm)
                    rm.bot.send_message(uid, cart_msg)
                    rm.db.log_conversion_event(uid, "interested")
                    sent_count += 1
                    logger.info(f"🛒 购物车挽回：{uid}")
                except Exception as e:
                    err_str = str(e).lower()
                    if "chat not found" in err_str or "bot was blocked" in err_str or "forbidden" in err_str:
                        rm.db.delete_user(uid)
                        logger.debug(f"💔 购物车挽回跳过无效用户 uid={uid}（已清理users+cart_recovery）")
                    else:
                        logger.warning(f"购物车挽回发送失败 uid={uid}：{e}")
            if sent_count > 0:
                _confirm_task_done("cart_recovery", rm.db, 3600)
            else:
                _release_task("cart_recovery", rm.db)
    except Exception as e:
        logger.error(f"购物车挽回失败：{e}")
        _release_task("cart_recovery", rm.db)


def _job_leak(rm):
    """【v4.9.0】背刺泄密（每周一次）
    
    新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)
    """
    if not _try_claim_and_lock("leak", rm.db, 86400):
        return
    try:
        now = datetime.now(_CST)
        current_week = now.isocalendar()[1]
        
        with rm.locked_multi(['config']):
            gid = rm.config.get("GROUP_ID", 0)
            last_leak_week = rm.config.get("_LAST_LEAK_WEEK", -1)
        
        if gid == 0 or current_week == last_leak_week or now.weekday() < 2:
            _release_task("leak", rm.db)
            return
        
        seed = random.randint(100000, 999999)
        scene_hint = random.choice([
            "在便利店买东西", "一个人看电视剧", "刷手机的时候",
            "发呆的时候", "跟闺蜜聊天", "自拍的时候", "做饭的时候",
            "洗澡前", "刚睡醒", "走路的时候", "吃零食的时候",
            "整理房间", "加班的时候", "逛街的时候", "坐地铁的时候",
            "打视频电话", "化妆的时候", "喝奶茶的时候", "拍照片",
        ])
        leak_prompt = (
            f"种子{seed}，场景：{scene_hint}。"
            f"用极度八卦、偷偷摸摸的语气，泄露一个关于Mory老板非常可爱、"
            f"生活化的小癖好或小秘密。要求：\n"
            f"1. 必须是全新的、独特的内容，绝对不能重复\n"
            f"2. 要有画面感和生活气息\n"
            f"3. 控制在25字以内\n"
            f"4. 不要出现任何编号、序号或列表格式"
        )
        
        with rm.locked('ai'):
            leak = rm.ai.ask(leak_prompt, mode="leak")
        
        if leak:
            try:
                sent = _send_and_track(rm, gid, f"🤫 老板不在... 偷偷跟你们说：\n\n{leak}")
                if sent:
                    rm.config["_LAST_LEAK_WEEK"] = current_week
                    rm.save_config_fn()
                    _confirm_task_done("leak", rm.db, 86400)
                    logger.info(f"🤫 背刺泄密触发(周{current_week})：{leak[:30]}")
                    return
            except Exception as e:
                logger.warning(f"背刺泄密发送失败：{e}")
        _release_task("leak", rm.db)
    except Exception as e:
        logger.error(f"背刺泄密失败：{e}")
        _release_task("leak", rm.db)
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
        from main import _cleanup_conv_tracker, _cleanup_radar_cooldown
        _cleanup_conv_tracker()
        _cleanup_radar_cooldown()
    except Exception as e:
        logger.debug(f"内存字典清理跳过：{e}")


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


def _sync_channel_posts(rm, channel_ids: list):
    """【v4.9.7废弃】此函数通过 get_updates() 获取频道帖子，但 infinity_polling 已消费所有更新，永远获取不到数据。
    已被 channel_post_handler + _refresh_channel_post_views 替代。保留函数体避免引用报错。"""
    for ch in channel_ids:
        cid = ch.get("id", 0) if isinstance(ch, dict) else ch
        cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
        try:
            # 获取频道最近24小时的消息
            now = int(time.time())
            day_ago = now - 86400
            # 使用 getUpdates 或 getChatHistory 获取消息
            # 注意：Bot API 不直接支持 getChatHistory，这里用 getUpdates 过滤
            with rm.locked('bot'):
                # 获取Bot在频道中的最新消息ID
                updates = rm.bot.get_updates(limit=100, timeout=10)
                for update in updates:
                    if hasattr(update, 'channel_post') and update.channel_post:
                        msg = update.channel_post
                        if msg.chat.id == cid and msg.date >= day_ago:
                            views = getattr(msg, 'views', 0) or 0
                            forwards = getattr(msg, 'forward_count', 0) or 0
                            rm.db.track_channel_post(
                                cid, msg.message_id, msg.date,
                                views=views, forwards=forwards,
                                content_type=getattr(msg, 'content_type', 'text')
                            )
                            # 更新浏览量
                            if views > 0:
                                rm.db.update_channel_post_views(cid, msg.message_id, views, forwards)
            logger.info(f"📊 频道内容同步: {cname}")
        except Exception as e:
            logger.debug(f"频道内容同步失败: {cname} err={e}")


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
                        # 立即删除转发消息
                        try:
                            rm.bot.delete_message(admin_id, fwd.message_id)
                        except Exception:
                            pass
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
    """【v4.9.0】每日数据报告 - 拆分为群报告+频道报告，私聊发送
    
    新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)
    """
    if not _try_claim_and_lock("daily_report", rm.db, 7200):
        return
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            _release_task("daily_report", rm.db)
            return
        
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
        
        _confirm_task_done("daily_report", rm.db, 7200)
        logger.info(f"✅ 每日数据报告已发送（群+频道）")
    except Exception as e:
        logger.error(f"每日数据报告失败：{e}")
        _release_task("daily_report", rm.db)
        _retry_task(rm, _job_daily_report, "daily_report")


def _send_daily_group_report(rm, admin_id: int, today: str, yesterday: str, gid: int, trend_fn):
    """【v4.9.7重构】群数据日报 — 移除浏览/回复，新增运营洞察"""
    token = rm.config.get("TOKEN", "")
    api_data = None
    api_yest_data = None
    use_api = False

    if token and gid:
        try:
            api_data = get_group_daily_stats(token, gid)
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
            except Exception:
                total_members = rm.db.get_group_total_members_latest(gid)
        active_today = rm.db.get_daily_active_users(today)
        msgs_today = rm.db.get_daily_bot_messages(today)
        data_source = "📊 自统计（事件追踪+校准）"

    joined_yest = joined_yest_db
    left_yest = left_yest_db
    net_yest = net_yest_db
    active_yest = rm.db.get_daily_active_users(yesterday)
    msgs_yest = rm.db.get_daily_bot_messages(yesterday)

    # ── 运营指标计算 ──
    # 活跃度
    activity_rate = (active_today / max(total_members, 1)) * 100
    activity_rate_yest = (active_yest / max(total_members, 1)) * 100

    # 沉默比例
    silence_ratio = ((total_members - active_today) / max(total_members, 1)) * 100

    # 流失预警
    churn_warning = ""
    if joined_today > 0 and (left_today / joined_today) > 0.5:
        churn_warning = " ⚠️"
    elif left_today > 0 and joined_today == 0:
        churn_warning = " 🔴"

    # Bot互动率
    bot_interact_rate = 0
    if msgs_today > 0:
        replies_today = rm.db.get_daily_replies(today)
        bot_interact_rate = (replies_today / msgs_today) * 100

    html = f"""🏠 <b>群数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📊 <b>群动态</b>
├ 今日入群：{joined_today} {trend_fn(joined_today, joined_yest)}
├ 今日离群：{left_today} {trend_fn(left_today, left_yest)}
├ 净增人数：{net_today:+d} {trend_fn(net_today, net_yest)}
└ 群成员数：{total_members}

━━━━━━━━━━━━━━━━━━

👥 <b>活跃度</b>
├ 活跃互动：{active_today} {trend_fn(active_today, active_yest)}
└ 消息数：{msgs_today} {trend_fn(msgs_today, msgs_yest)}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
├ 活跃度：{activity_rate:.1f}% {trend_fn(activity_rate, activity_rate_yest)}
├ 沉默比例：{silence_ratio:.1f}%
├ 流失预警：{'离群/入群=' + f'{left_today}/{joined_today}' + churn_warning if joined_today > 0 else f'离群{left_today}' + churn_warning}
└ Bot互动率：{bot_interact_rate:.0f}%

━━━━━━━━━━━━━━━━━━

🌙 <b>昨日同期</b>
├ 入群{joined_yest}/离群{left_yest}/净增{net_yest:+d}
├ 互动{active_yest}/消息{msgs_yest}

━━━━━━━━━━━━━━━━━━
<i>{data_source} · Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 群日报已发送: 入群{joined_today} 离群{left_today} 净增{net_today} 来源={'API' if use_api else '自统计'}")


def _send_daily_channel_report(rm, admin_id: int, today: str, trend_fn):
    """【v4.9.7重构】频道数据日报 — 运营指标 + 健康度评分"""
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
        api_ch = None
        if token:
            try:
                api_ch = get_channel_daily_stats(token, cid)
                if api_ch:
                    any_api = True
            except Exception:
                pass

        yest_stats = rm.db.get_channel_daily_stats(cid, yesterday)
        posts_yest = yest_stats.get("posts", 0)
        views_yest = yest_stats.get("views", 0)

        posts_today = 0
        views_today = 0
        forwards_today = 0
        avg_views = 0

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
        else:
            try:
                today_stats = rm.db.get_channel_daily_stats(cid, today)
                native_stats = rm.db.get_channel_post_stats(cid, today)
                posts_today = today_stats.get("posts", 0)
                views_today = today_stats.get("views", 0)
                forwards_today = native_stats.get("forwards", 0)
                avg_views = today_stats.get("avg_views", 0)
            except Exception as e:
                logger.debug(f"频道统计获取失败: {cname} err={e}")

        total_posts_today += posts_today
        total_views_today += views_today
        total_forwards_today += forwards_today

        stats_lines.append(
            f"├ {cname}："
            f"发帖{posts_today}{trend_fn(posts_today, posts_yest)} "
            f"浏览{views_today}{trend_fn(views_today, views_yest)} "
            f"均阅{avg_views}"
        )

        # ── 运营指标计算 ──
        reach_rate = (views_today / max(ch_count, 1)) * 100
        interact_rate = (forwards_today / max(views_today, 1)) * 100
        hot_posts = rm.db.get_channel_top_posts(cid, today, threshold=2.0)

        ops_lines.append(
            f"├ {cname}：触达{reach_rate:.0f}% 互动{interact_rate:.1f}% 爆款{hot_posts}条"
        )

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    # ── 综合健康度评分 ──
    # 成员增长 30%
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
    if total_net > 0:
        growth_score = 30
    elif total_net == 0:
        growth_score = 15
    else:
        growth_score = max(0, 30 + total_net * 2)

    # 内容触达 25%
    total_reach_rate = (total_views_today / max(total_channel_members, 1)) * 100
    reach_score = min(25, total_reach_rate / 4)

    # 社群活跃 25%
    active_today = rm.db.get_daily_active_users(today)
    total_members_group = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members_group = rm.bot.get_chat_member_count(gid)
        except Exception:
            total_members_group = rm.db.get_group_total_members_latest(gid)
    activity_rate = (active_today / max(total_members_group, 1)) * 100
    activity_score = min(25, activity_rate / 2)

    # 内容更新 20%
    if total_posts_today >= 3:
        content_score = 20
    elif total_posts_today >= 1:
        content_score = 10
    else:
        content_score = 0

    health_score = int(growth_score + reach_score + activity_score + content_score)
    if health_score >= 70:
        health_icon = "🟢"
    elif health_score >= 40:
        health_icon = "🟡"
    else:
        health_icon = "🔴"

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"

    html = f"""📢 <b>频道数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📈 <b>各频道概况</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📊 <b>今日发帖/浏览</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
{chr(10).join(ops_lines)}

━━━━━━━━━━━━━━━━━━

🏥 <b>综合健康度</b> {health_icon} {health_score}/100
├ 成员增长{growth_score:.0f}/30 · 内容触达{reach_score:.0f}/25
├ 社群活跃{activity_score:.0f}/25 · 内容更新{content_score:.0f}/20
└ 汇总：发帖{total_posts_today}条 / 浏览{total_views_today}次 / 转发{total_forwards_today}次

━━━━━━━━━━━━━━━━━━
<i>{data_source} · Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 频道日报已发送: 发帖{total_posts_today} 浏览{total_views_today} 健康度{health_score} API={'是' if any_api else '否'}")


def _job_weekly_report(rm):
    """【v4.9.0】每周数据报告 - 群周报+频道周报，含趋势分析
    
    新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)
    """
    if not _try_claim_and_lock("weekly_report", rm.db, 86400):
        return
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            _release_task("weekly_report", rm.db)
            return
        
        now = datetime.now(_CST)
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
        week_ago_ts = int((now - timedelta(days=7)).timestamp())
        now_ts = int(now.timestamp())
        
        _send_weekly_group_report(rm, admin_id, today, week_ago, two_weeks_ago)
        _send_weekly_channel_report(rm, admin_id, today, week_ago, week_ago_ts, now_ts)
        
        _confirm_task_done("weekly_report", rm.db, 86400)
        logger.info("✅ 每周数据报告已发送（群+频道）")
    except Exception as e:
        logger.error(f"每周数据报告失败：{e}")
        _release_task("weekly_report", rm.db)
        _retry_task(rm, _job_weekly_report, "weekly_report")


def _send_weekly_group_report(rm, admin_id: int, today: str, week_ago: str, two_weeks_ago: str):
    """【v4.9.7重构】群数据周报 — 移除浏览/回复，新增运营洞察"""
    gid = rm.config.get("GROUP_ID", 0)
    this_week = rm.db.get_weekly_group_stats(week_ago, today, chat_id=gid)
    last_week = rm.db.get_weekly_group_stats(two_weeks_ago, week_ago, chat_id=gid)
    
    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception:
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
    
    retention = 0
    if this_week["joined"] > 0:
        retention = max(0, (this_week["joined"] - this_week["left"]) / this_week["joined"] * 100)
    
    # ── 运营指标 ──
    activity_rate = (this_week.get("active_users", 0) / max(total_members, 1)) * 100
    churn_warning = ""
    if this_week["joined"] > 0 and (this_week["left"] / this_week["joined"]) > 0.5:
        churn_warning = " ⚠️"
    
    data_source = "📊 自统计（事件追踪+校准）"

    html = f"""🏠 <b>群数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📊 <b>本周群动态</b>
├ 入群：{this_week['joined']} {trend(this_week['joined'], last_week['joined'])}
├ 离群：{this_week['left']} {trend(this_week['left'], last_week['left'])}
├ 净增：{this_week['net']:+d} {trend(this_week['net'], last_week['net'])}
└ 当前成员：{total_members}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
├ 活跃度：{activity_rate:.1f}%
├ 留存率：{retention:.0f}%
├ 流失预警：离群/入群={this_week['left']}/{this_week['joined']}{churn_warning}
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
<i>{data_source} · Mory小助理</i>"""
    
    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 群周报已发送")


def _send_weekly_channel_report(rm, admin_id: int, today: str, week_ago: str, week_ago_ts: int, now_ts: int):
    """【v4.9.7重构】频道数据周报 — 成员变化 + 发帖浏览 + 运营指标"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return

    token = rm.config.get("TOKEN", "")
    channel_lines = []
    stats_lines = []
    ops_lines = []
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
                api_ch = get_channel_daily_stats(token, cid)
                if api_ch:
                    any_api = True
            except Exception:
                pass

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

        # ── 运营指标 ──
        reach_rate = (views / max(ch_count, 1)) * 100
        interact_rate = (forwards / max(views, 1)) * 100
        ops_lines.append(f"├ {cname}：触达{reach_rate:.0f}% 互动{interact_rate:.1f}%")

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"

    html = f"""📢 <b>频道数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道周数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
{chr(10).join(ops_lines)}

━━━━━━━━━━━━━━━━━━
<i>{data_source} · Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info(f"✅ 频道周报已发送 API={'是' if any_api else '否'}")


def _job_monthly_report(rm):
    """【v4.9.6新增】每月数据报告 - 群月报+频道月报
    每月1号 9:00 执行
    """
    if not _try_claim_and_lock("monthly_report", rm.db, 86400 * 28):
        return
    try:
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not admin_id:
            _release_task("monthly_report", rm.db)
            return

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

        _confirm_task_done("monthly_report", rm.db, 86400 * 28)
        logger.info("✅ 每月数据报告已发送（群+频道）")
    except Exception as e:
        logger.error(f"每月数据报告失败：{e}")
        _release_task("monthly_report", rm.db)
        _retry_task(rm, _job_monthly_report, "monthly_report")


def _send_monthly_group_report(rm, admin_id: int, today: str, month_start: str, prev_month_start: str):
    """【v4.9.7重构】群数据月报 — 移除浏览/回复，新增运营洞察"""
    gid = rm.config.get("GROUP_ID", 0)
    this_month = rm.db.get_weekly_group_stats(month_start, today, chat_id=gid)
    last_month = rm.db.get_weekly_group_stats(prev_month_start, month_start, chat_id=gid)

    total_members = 0
    if gid:
        try:
            with rm.locked('bot'):
                total_members = rm.bot.get_chat_member_count(gid)
        except Exception:
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

    retention = 0
    if this_month["joined"] > 0:
        retention = max(0, (this_month["joined"] - this_month["left"]) / this_month["joined"] * 100)

    # ── 运营指标 ──
    activity_rate = (this_month.get("active_users", 0) / max(total_members, 1)) * 100
    churn_warning = ""
    if this_month["joined"] > 0 and (this_month["left"] / this_month["joined"]) > 0.5:
        churn_warning = " ⚠️"

    data_source = "📊 自统计（事件追踪+校准）"
    month_display = month_start[:7]

    html = f"""🏠 <b>群数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📊 <b>本月群动态</b>
├ 入群：{this_month['joined']} {trend(this_month['joined'], last_month['joined'])}
├ 离群：{this_month['left']} {trend(this_month['left'], last_month['left'])}
├ 净增：{this_month['net']:+d} {trend(this_month['net'], last_month['net'])}
└ 当前成员：{total_members}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
├ 月活跃度：{activity_rate:.1f}%
├ 留存率：{retention:.0f}%
├ 流失预警：离群/入群={this_month['left']}/{this_month['joined']}{churn_warning}

━━━━━━━━━━━━━━━━━━

📈 <b>月环比</b>
├ 入群变化：{pct(this_month['joined'], last_month['joined'])}
├ 离群变化：{pct(this_month['left'], last_month['left'])}
└ 净增变化：{pct(this_month['net'], last_month['net'])}

━━━━━━━━━━━━━━━━━━

📉 <b>上月同期</b>
├ 入群{last_month['joined']}/离群{last_month['left']}/净增{last_month['net']:+d}

━━━━━━━━━━━━━━━━━━
<i>{data_source} · Mory小助理</i>"""

    with rm.locked('bot'):
        rm.bot.send_message(admin_id, html, parse_mode="HTML")
    logger.info("✅ 群月报已发送")


def _send_monthly_channel_report(rm, admin_id: int, today: str, month_start: str, prev_month_start: str):
    """【v4.9.7重构】频道数据月报 — 成员变化 + 发帖浏览 + 运营指标"""
    channel_ids = rm.config.get("CHANNEL_IDS", [])
    if not channel_ids:
        return

    token = rm.config.get("TOKEN", "")
    channel_lines = []
    stats_lines = []
    ops_lines = []
    any_api = False
    month_display = month_start[:7]

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
                api_ch = get_channel_daily_stats(token, cid)
                if api_ch:
                    any_api = True
            except Exception:
                pass

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

        # ── 运营指标 ──
        reach_rate = (views / max(ch_count, 1)) * 100
        interact_rate = (forwards / max(views, 1)) * 100
        ops_lines.append(f"├ {cname}：触达{reach_rate:.0f}% 互动{interact_rate:.1f}%")

    if channel_lines:
        channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
    if stats_lines:
        stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
    if ops_lines:
        ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

    data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"

    html = f"""📢 <b>频道数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道月数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

💡 <b>运营洞察</b>
{chr(10).join(ops_lines)}

━━━━━━━━━━━━━━━━━━
<i>{data_source} · Mory小助理</i>"""

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
    """撩人转化文案 - 绿茶口吻，隐晦引导（AI失败时的备用）"""
    hooks = [
        f"这牌还有更深层的意思呢，想知道吗",
        f"其实这张牌背面藏着另一段故事哦",
        f"有些话这里说不完，你懂的",
        f"今天这牌其实还有后半段没揭晓呢",
        f"你今天的运势其实还有隐藏玩法",
        f"有些惊喜光看这几行字可不够呢",
        f"这运势只是冰山一角，水面下才精彩",
        f"老粉都知道，这牌还有另一面",
        f"其实今天的好事不止这些，还有呢",
        f"这牌暗示的东西，可比表面深多了",
        f"想知道这张牌真正想告诉你的事吗",
        f"有些缘分，只有慢慢聊才能懂呢",
        f"今天这运势后面还跟着个彩蛋哦",
        f"这牌的解读嘛，三言两语可说不清",
        f"有些话得悄悄说才更有味道呢",
    ]
    return random.choice(hooks)


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
    
    prompt = f"""你是Mory老板，一个撩人的塔罗师，像闺蜜一样亲切。

根据以下信息生成塔罗运势，全部要浓缩在一屏能看完的长度：

【运势类型】：{tarot['theme']}
【塔罗牌】：{tarot['card']} {tarot['position']}

请按以下格式生成：

1. 牌面描述（一句话，15-25字，有画面感，带一个emoji）
2. 今日解读（1-2句话，30-40字，有故事感，带emoji）
3. 今日建议（一句话，15字以内，带emoji）
4. 幸运色（只写颜色，2-4字）
5. 幸运方位（只写方位，2-4字）
6. 幸运数字（3个数字，如：7,23,45）
7. 贵人星座（只写星座名）
8. 幸运时段（如：上午9-11点）

seed={seed_for_ai}
要求：
- 语气温柔亲切，像闺蜜聊天
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
    """【v4.9.0】每日塔罗搭讪（30%概率，针对群里活跃用户）
    
    新流程：_try_claim_and_lock(原子抢占) → 执行 → 失败时_release_task(释放锁)
    
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

    if not _try_claim_and_lock("tarot_flirt", rm.db, 7200):
        return
    
    if random.random() > 0.30:
        _release_task("tarot_flirt", rm.db)
        return
    
    try:
        gid = rm.config.get("GROUP_ID", 0)
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not gid or not admin_id:
            return
        
        logger.info("🎴 触发每日塔罗搭讪任务")
        
        # 获取群成员
        try:
            members = rm.bot.get_chat_member_count(gid)
            if members < 5:
                return
        except Exception:
            pass
        
        # 获取最近活跃用户（替代不存在的get_chat_history）
        recent_users = {}
        try:
            ts_1h_ago = int(time.time()) - 3600
            active_users = rm.db.get_active_users(ts_1h_ago)
            for uid, uname, keywords in active_users[:20]:
                if uid != admin_id:
                    recent_users[uid] = (uname or "哥哥", keywords or "")
        except Exception as e:
            logger.debug(f"获取活跃用户失败：{e}")
            return
        
        if not recent_users:
            return
        
        # 随机选一个用户和消息
        uid, (uname, user_msg) = random.choice(list(recent_users.items()))
        
        logger.info(f"🎴 塔罗搭讪目标: {uname} 说: {user_msg[:30]}")
        
        # 获取该用户今日运势（北京时间缓存）
        tarot_base = _get_tarot_cache(uid, datetime.now())
        
        # 调用AI生成完整运势内容
        tarot = _generate_tarot_ai_content(tarot_base, uid, rm)
        
        # 开场白
        opener_text = random.choice(['哥哥～', '嘿～', '在吗～', '哎～', '诶～'])
        opener_action = random.choice(['看到你说的', '刷到你这句', '你刚才说'])
        
        # AI生成隐晦撩人转化结尾（绝不能提会员/付费/订阅）
        convert_seed = random.randint(10000, 99999)
        convert_prompt = f"""你是Mory老板，一个撩人的塔罗师。

给刚测完「{tarot['theme']}」的「{uname}」写一句撩人引导语。

要求：
1. 20-30字，像闺蜜私聊一样自然
2. 暗示有更深度的解读等着他，勾起好奇心
3. 禁止：会员、付费、订阅、解锁、钱、开通、VIP、专属版、赞助、免费、完整版、私聊
4. 撩人但隐晦，让人心痒痒想追问
5. 每次seed不同，内容必须不重复
6. 不要emoji

seed={convert_seed}"""
        
        try:
            with rm.locked('ai'):
                convert_hint = rm.ai.ask(convert_prompt, mode="convert_hook", seed=convert_seed)
            if not convert_hint or len(convert_hint) < 10:
                convert_hint = _get_fallback_hook(tarot['theme'], uname)
        except Exception:
            convert_hint = _get_fallback_hook(tarot['theme'], uname)
        
        # 构建HTML卡片消息（高度随机：40%短版 / 60%长版）
        short_mode = random.random() < 0.4
        
        # 【v4.5.35修复】所有动态内容统一HTML转义，防止XSS/格式错乱
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
            # ══ 短版：约70字，手机一屏看完
            html_reply = f"""🎴 <b>{safe_card} {safe_position}</b>

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

🌈 {safe_color} · 📍 {safe_dir}

{safe_convert}"""
        else:
            # ══ 长版：约110字（控制在一屏内）
            html_reply = f"""🎴 <b>{safe_theme}</b> · {safe_card} {safe_position}

@{safe_uname} {safe_opener} {safe_action}「{safe_user_msg}」~

📖 {safe_meaning}

💡 {safe_advice}

🌈 {safe_color} · 📍 {safe_dir} · 🔢 {safe_nums} · ⭐ {safe_star} · ⏰ {safe_time}

{safe_convert}"""
        
        # 发送HTML格式消息
        try:
            with rm.locked('bot'):
                rm.bot.send_message(gid, html_reply, parse_mode="HTML")
            _confirm_task_done("tarot_flirt", rm.db, 7200)
            logger.info(f" 塔罗搭讪成功: @{uname}")
        except Exception as e:
            logger.error(f"塔罗搭讪发送失败：{e}")
            _release_task("tarot_flirt", rm.db)
    except Exception as e:
        logger.error(f"塔罗搭讪任务失败：{e}")
        _release_task("tarot_flirt", rm.db)


def _do_backup(db_file: str):
    """执行数据库备份，保留最近7天（168份）"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backup_dir = os.path.join(base_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts_str = datetime.now(_CST).strftime("%Y%m%d_%H00")
    dest = os.path.join(backup_dir, f"mory_backup_{ts_str}.db")
    try:
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_file)
        dst_conn = _sqlite3.connect(dest)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        backups = sorted(glob.glob(os.path.join(backup_dir, "mory_backup_*.db")))
        for old in backups[:-168]:
            os.remove(old)
        logger.info(f"💾 备份完成：{dest}")
    except Exception as e:
        logger.error(f"备份失败：{e}")


_CRITICAL_TASKS = [
    ("greeting_morning", "早安问候", 10),
    ("greeting_afternoon", "午安问候", 13),
    ("greeting_evening", "晚安问候", 23),
    ("news_morning", "早间新闻", 10),
    ("news_afternoon", "午间新闻", 14),
    ("news_evening", "晚间新闻", 21),
    ("daily_report", "每日日报", 10),
]


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
        for task_key, task_desc, expected_hour in _CRITICAL_TASKS:
            if current_hour < expected_hour:
                logger.debug(f"🏥 [health_check] {task_desc} 未到预期时间({expected_hour}:00)，跳过")
                continue
            if not rm.db.is_task_executed_today(task_key):
                missed.append(f"• {task_desc}（应在{expected_hour}:00前执行）")
                logger.info(f"🏥 [health_check] ❌ {task_desc} 今日未执行")
            else:
                logger.debug(f"🏥 [health_check] ✅ {task_desc} 今日已执行")
        
        anomalies = _task_guard.audit_task_log(rm.db)
        
        parts = []
        if missed:
            parts.append(f"⚠️ <b>任务未执行</b>\n" + "\n".join(missed))
        if anomalies:
            parts.append(f"🚨 <b>数据库锁异常</b>\n" + "\n".join(anomalies))
        
        if parts:
            msg = f"🏥 <b>任务健康检查</b> · {today}\n\n" + "\n\n".join(parts)
            try:
                with rm.locked('bot'):
                    rm.bot.send_message(admin_id, msg, parse_mode="HTML")
                logger.warning(f"⚠️ [health_check] 发现异常，已通知管理员")
            except Exception as e:
                logger.error(f"⚠️ [health_check] 通知发送失败：{e}")
        else:
            logger.info(f"✅ [health_check] 所有关键任务已正常执行，数据库无异常")
    except Exception as e:
        logger.error(f"❌ [health_check] 健康检查失败：{e}")


def start_background(bot, config: Dict[str, Any], db, ai, save_config_fn):
    """启动后台任务引擎"""
    # 【v4.9.3】防重入保护：避免重复启动导致多个scheduler实例并发调度
    global _scheduler_instance
    if _scheduler_instance is not None and getattr(_scheduler_instance, 'running', False):
        logger.warning("⚠️ 后台任务引擎已在运行，跳过重复启动")
        return

    rm = ResourceManager(bot=bot, ai=ai, db=db, config=config, save_config_fn=save_config_fn)
    _task_guard.bind(rm)
    _fault_reporter.bind(rm)

    if HAS_APSCHEDULER:
        _start_with_apscheduler(rm)
    else:
        _start_with_legacy_loop(rm)


def _start_with_apscheduler(rm):
    """APScheduler 版本：独立 Job"""
    global _scheduler_instance
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler_instance = scheduler
    
    # 新闻播报（misfire_grace_time=60：1分钟内错过可补发，coalesce防堆积连发）
    scheduler.add_job(_job_news_morning, "cron", hour=9, minute=5, args=[rm], id="news_morning", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_news_afternoon, "cron", hour=13, minute=5, args=[rm], id="news_afternoon", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_news_evening, "cron", hour=20, minute=35, args=[rm], id="news_evening", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 每日数据报告（v4.2.4）- 私聊发送
    scheduler.add_job(_job_daily_report, "cron", hour=9, minute=10, args=[rm], id="daily_report", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_weekly_report, "cron", day_of_week="mon", hour=9, minute=30, args=[rm], id="weekly_report", max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(_job_monthly_report, "cron", day=1, hour=9, minute=30, args=[rm], id="monthly_report", max_instances=1, coalesce=True, misfire_grace_time=3600)
    scheduler.add_job(_refresh_channel_post_views, "cron", hour="*/1", minute=40, args=[rm], id="refresh_channel_views", max_instances=1, coalesce=True, misfire_grace_time=3600)
    
    # 每日塔罗搭讪（v4.2.5）- 随机30%概率
    scheduler.add_job(_job_tarot_flirt, "cron", hour=15, minute=0, args=[rm], id="tarot_flirt", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 问候
    scheduler.add_job(_job_greeting_morning, "cron", hour=8, minute=5, args=[rm], id="greeting_morning", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_greeting_afternoon, "cron", hour=12, minute=35, args=[rm], id="greeting_afternoon", max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(_job_greeting_evening, "cron", hour=23, minute=5, args=[rm], id="greeting_evening", max_instances=1, coalesce=True, misfire_grace_time=60)
    
    # 叫醒服务（每分钟）
    scheduler.add_job(_job_wakeup_check, "cron", minute="*", args=[rm], id="wakeup_check", max_instances=1, misfire_grace_time=60)
    
    # 阅后即焚探测已废弃（v4.5.35），不再调度_job_burn_probe

    # 【v4.9.3】每小时任务统一补coalesce=True，防止misfire堆积补发导致record_call误报
    scheduler.add_job(_job_burn_orphan, "cron", minute="5", args=[rm], id="burn_orphan", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_reactivate, "cron", minute=5, args=[rm], id="reactivate", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_cart_recovery, "cron", minute=10, args=[rm], id="cart_recovery", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_backup, "cron", minute=15, args=[rm], id="backup", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_ttl_cleanup, "cron", minute=20, args=[rm], id="ttl_cleanup", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_save_config, "cron", minute=30, args=[rm], id="save_config", max_instances=1, coalesce=True, misfire_grace_time=300)
    scheduler.add_job(_job_channel_views, "cron", minute=25, args=[rm], id="channel_views", max_instances=1, coalesce=True, misfire_grace_time=300)
    
    # 背刺泄密（每周三0点）
    scheduler.add_job(_job_leak, "cron", day_of_week="wed", hour=0, minute=0, args=[rm], id="leak", max_instances=1, misfire_grace_time=3600)
    
    # 任务健康检查（每6小时，检查关键任务是否按时执行）
    scheduler.add_job(_job_health_check, "cron", hour="10,16,22", minute=0, args=[rm], id="health_check", max_instances=1, coalesce=True, misfire_grace_time=300)
    
    scheduler.start()
    logger.info("🚀 后台任务引擎启动（APScheduler版，各任务独立运行）")


def _start_with_legacy_loop(rm):
    """旧版 while True 循环（APScheduler 未安装时回退）"""
    t = threading.Thread(target=_legacy_task_loop, args=(rm,), daemon=True, name="AutoTasks-Legacy")
    t.start()
    logger.info("🚀 后台任务引擎启动（旧版循环，APScheduler未安装）")


def _legacy_task_loop(rm):
    """旧版 while True 循环（兼容备用）- 已迁移至 _can_run/_mark_done 节流"""
    global _last_saved_model_idx
    while True:
        try:
            now = datetime.now(_CST)

            _job_wakeup_check(rm)

            if _can_run("burn_probe", 180):
                try:
                    _job_burn_probe(rm)
                except Exception as e:
                    logger.error(f"burn_probe异常: {e}")
                _mark_done("burn_probe")

            if _can_run("burn_orphan", 600):
                try:
                    _job_burn_orphan(rm)
                except Exception as e:
                    logger.error(f"burn_orphan超时或异常: {e}")
                _mark_done("burn_orphan")

            if _can_run("backup", 3600):
                try:
                    _job_backup(rm)
                except Exception as e:
                    logger.error(f"backup异常: {e}")
                _mark_done("backup")

            if _can_run("ttl_cleanup", 3600):
                try:
                    _job_ttl_cleanup(rm)
                except Exception as e:
                    logger.error(f"ttl_cleanup异常: {e}")
                _mark_done("ttl_cleanup")

            try:
                _job_reactivate(rm)
            except Exception as e:
                logger.error(f"reactivate异常: {e}")
            try:
                _job_cart_recovery(rm)
            except Exception as e:
                logger.error(f"cart_recovery异常: {e}")
            try:
                _job_save_config(rm)
            except Exception as e:
                logger.error(f"save_config异常: {e}")

            if now.weekday() == 2 and now.hour == 0 and now.minute == 0:
                _job_leak(rm)

            if now.hour == 9 and now.minute < 5:
                _job_news_morning(rm)
            if now.hour == 13 and now.minute < 5:
                _job_news_afternoon(rm)
            if now.hour == 20 and 28 <= now.minute < 35:
                _job_news_evening(rm)
            if now.hour == 8 and now.minute < 5:
                _job_greeting_morning(rm)
            if now.hour == 12 and 28 <= now.minute < 35:
                _job_greeting_afternoon(rm)
            if now.hour == 23 and now.minute < 5:
                _job_greeting_evening(rm)

        except Exception as e:
            logger.error(f"❌ 后台任务异常：{e}")

        time.sleep(60)
