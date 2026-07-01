# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/scheduler_monitor.py  ·  APScheduler 任务监控（v5.23.0 P2-6）       ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 监听 APScheduler 事件（成功/失败/延误）                              ║
║    2. 内存指标统计 + scheduler_metrics 表持久化                            ║
║    3. 提供 get_scheduler_stats() 供 Dashboard /api/scheduler/stats 调用    ║
║                                                                            ║
║  使用：                                                                    ║
║    from core.scheduler_monitor import attach_to_scheduler                  ║
║    attach_to_scheduler(scheduler)                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("scheduler_monitor")

_CST = timezone(timedelta(hours=8))

# 全局指标存储（线程安全）
_metrics_lock = threading.Lock()
_metrics = {
    "jobs": defaultdict(dict),  # {job_id: {last_run, last_duration, last_status, success_count, fail_count, miss_count}}
    "total_success": 0,
    "total_fail": 0,
    "total_miss": 0,
    "started_at": 0,
}


def attach_to_scheduler(scheduler):
    """附加事件监听器到 APScheduler 实例"""
    try:
        from apscheduler.events import (
            EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
        )
    except ImportError:
        logger.warning("APScheduler 未安装，调度监控无法启动")
        return

    with _metrics_lock:
        _metrics["started_at"] = int(time.time())

    def _on_job_event(event):
        """任务事件回调"""
        job_id = event.job_id
        now_ts = int(time.time())

        with _metrics_lock:
            job_info = _metrics["jobs"][job_id]

            if event.code == EVENT_JOB_EXECUTED:
                # 成功执行
                job_info["last_status"] = "success"
                job_info["success_count"] = job_info.get("success_count", 0) + 1
                _metrics["total_success"] += 1
                # 计算执行耗时（如果有 scheduled_time）
                if hasattr(event, "scheduled_time") and event.scheduled_time:
                    try:
                        scheduled_ts = event.scheduled_time.timestamp()
                        duration = now_ts - int(scheduled_ts)
                        job_info["last_duration"] = duration
                    except Exception as e:
                        logger.debug(f"计算 last_duration 失败: {e}")
                job_info["last_run"] = now_ts
                logger.debug(f"[Scheduler] 任务成功: {job_id}")

            elif event.code == EVENT_JOB_ERROR:
                # 执行出错
                job_info["last_status"] = "error"
                job_info["fail_count"] = job_info.get("fail_count", 0) + 1
                job_info["last_error"] = str(event.exception)[:200] if event.exception else "unknown"
                job_info["last_run"] = now_ts
                _metrics["total_fail"] += 1
                logger.warning(f"[Scheduler] 任务失败: {job_id} | 错误: {job_info['last_error']}")

            elif event.code == EVENT_JOB_MISSED:
                # 任务延误被丢弃
                job_info["last_status"] = "missed"
                job_info["miss_count"] = job_info.get("miss_count", 0) + 1
                job_info["last_miss"] = now_ts
                _metrics["total_miss"] += 1
                logger.warning(f"[Scheduler] 任务延误丢弃: {job_id}")

    # 注册监听器
    scheduler.add_listener(_on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    logger.info("✅ 调度监控已附加（监听 EXECUTED/ERROR/MISSED 事件）")


def get_scheduler_stats() -> dict:
    """获取调度器统计指标"""
    with _metrics_lock:
        jobs = {}
        for job_id, info in _metrics["jobs"].items():
            jobs[job_id] = dict(info)

        return {
            "started_at": _metrics["started_at"],
            "uptime_seconds": int(time.time()) - _metrics["started_at"] if _metrics["started_at"] else 0,
            "total_success": _metrics["total_success"],
            "total_fail": _metrics["total_fail"],
            "total_miss": _metrics["total_miss"],
            "job_count": len(jobs),
            "jobs": jobs,
        }


def get_job_list(scheduler) -> list:
    """获取调度器当前所有任务列表"""
    jobs = []
    try:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name or job.id,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "未调度",
                "trigger": str(job.trigger),
                "max_instances": getattr(job, "max_instances", 1),
                "coalesce": getattr(job, "coalesce", True),
            })
    except Exception as e:
        logger.debug(f"获取任务列表失败: {e}")
    return jobs


def sync_metrics_to_db(db) -> int:
    """[v5.24.0 阶段3-D] 将内存指标批量刷盘到 scheduler_metrics 表

    采用 REPLACE INTO 单次批量更新，避免高频实时写入给 DB 增加负担。
    由定时任务每 5 分钟调用一次，服务异常重启最多丢失 5 分钟统计数据。

    Args:
        db: DB 实例

    Returns:
        写入的 job 记录数
    """
    try:
        with _metrics_lock:
            jobs_snapshot = {jid: dict(info) for jid, info in _metrics["jobs"].items()}
            totals = {
                "total_success": _metrics["total_success"],
                "total_fail": _metrics["total_fail"],
                "total_miss": _metrics["total_miss"],
            }

        if not jobs_snapshot:
            return 0

        with db.lock:
            c = db.conn.cursor()
            # 幂等建表
            c.execute("""
                CREATE TABLE IF NOT EXISTS scheduler_metrics (
                    job_id TEXT PRIMARY KEY,
                    last_status TEXT,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    miss_count INTEGER DEFAULT 0,
                    last_run INTEGER,
                    last_duration INTEGER,
                    last_error TEXT,
                    synced_at INTEGER NOT NULL
                )
            """)
            now_ts = int(time.time())
            for job_id, info in jobs_snapshot.items():
                c.execute("""
                    REPLACE INTO scheduler_metrics
                    (job_id, last_status, success_count, fail_count, miss_count,
                     last_run, last_duration, last_error, synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    job_id,
                    info.get("last_status", ""),
                    info.get("success_count", 0),
                    info.get("fail_count", 0),
                    info.get("miss_count", 0),
                    info.get("last_run", 0),
                    info.get("last_duration", 0),
                    info.get("last_error", "")[:500],
                    now_ts,
                ))
            db.conn.commit()
        logger.debug(f"[Scheduler] 指标落盘完成: {len(jobs_snapshot)} 个任务")
        return len(jobs_snapshot)
    except Exception as e:
        logger.debug(f"调度指标落盘失败: {e}")
        return 0


# 【v5.31.1 第四层防御】关键用户可感知任务的预期执行时间表
# 格式：job_id 前缀 → {latest_hour, latest_minute, description}
# 监控逻辑：如果当前时间 > (latest_hour:latest_minute + 30min 宽限)，且该 job 今天未成功执行 → CRITICAL 告警
# 注：broadcast_* 和 greeting_* 的具体时间由 config.json 决定，这里只设一个保守的"当日必须执行"截止时间
_CRITICAL_JOBS = {
    # 问候：早安 8:05 / 午安 12:35 / 晚安 23:05 — 所有问候最晚 23:35 前应执行至少一次（如果开启）
    "greeting_morning": {"deadline_hour": 9, "deadline_minute": 0, "desc": "早安问候(8:05)"},
    "greeting_afternoon": {"deadline_hour": 13, "deadline_minute": 30, "desc": "午安问候(12:35)"},
    "greeting_evening": {"deadline_hour": 23, "deadline_minute": 40, "desc": "晚安问候(23:05)"},
    # 播报：早 10:00 / 午 14:30 / 晚 19:00 / 夜 22:30 — 所有播报最晚 23:00 前应执行
    "broadcast_morning_nudge": {"deadline_hour": 11, "deadline_minute": 0, "desc": "晨间播报(10:00)"},
    "broadcast_afternoon_tea": {"deadline_hour": 15, "deadline_minute": 30, "desc": "下午茶播报(14:30)"},
    "broadcast_evening_wind": {"deadline_hour": 20, "deadline_minute": 0, "desc": "傍晚播报(19:00)"},
    "broadcast_night_whisper": {"deadline_hour": 23, "deadline_minute": 30, "desc": "夜间播报(22:30)"},
}

# 已告警的 job（避免每 30 分钟重复告警，每天重置一次）
_alerted_jobs = set()
_alerted_date = None


def check_critical_jobs_health(scheduler=None, config=None):
    """【v5.31.1 第四层防御】检查关键用户可感知任务是否按时执行

    监控逻辑：
    1. 遍历 _CRITICAL_JOBS 中定义的关键任务
    2. 如果当前时间已超过该任务的截止时间（含宽限），检查今天是否成功执行过
    3. 如果今天未成功执行 → CRITICAL 日志告警（触发告警 bot 通知，如果已配置）
    4. 用 _alerted_jobs 防重复告警（每天重置）

    Args:
        scheduler: APScheduler 实例（可选，用于获取 job 的 next_run_time）
        config: 配置 dict（可选，用于检查开关状态）
    """
    global _alerted_jobs, _alerted_date
    now = datetime.now(_CST)
    today_str = now.strftime("%Y-%m-%d")

    # 每天重置告警状态
    if _alerted_date != today_str:
        _alerted_jobs = set()
        _alerted_date = today_str

    with _metrics_lock:
        jobs_snapshot = {jid: dict(info) for jid, info in _metrics["jobs"].items()}

    alerts = []
    all_ok = True

    for job_id, spec in _CRITICAL_JOBS.items():
        if job_id in _alerted_jobs:
            continue

        deadline = now.replace(hour=spec["deadline_hour"], minute=spec["deadline_minute"], second=0, microsecond=0)
        if now < deadline:
            continue  # 还没到截止时间，不检查

        # 检查该 job 今天是否成功执行过
        job_info = jobs_snapshot.get(job_id, {})
        last_run = job_info.get("last_run", 0)
        last_status = job_info.get("last_status", "")

        if last_run > 0:
            last_run_dt = datetime.fromtimestamp(last_run, tz=_CST)
            if last_run_dt.strftime("%Y-%m-%d") == today_str and last_status == "success":
                continue  # 今天已成功执行，正常

        # 没执行过或执行失败 → 告警
        alerts.append(f"🚨 关键任务未执行: {spec['desc']} (job_id={job_id}, 截止={spec['deadline_hour']:02d}:{spec['deadline_minute']:02d}, last_status={last_status})")
        _alerted_jobs.add(job_id)
        all_ok = False

    if alerts:
        for a in alerts:
            logger.critical(a)
    elif now.hour >= 0 and now.minute >= 0:  # 每次检查都记录正常状态（debug 级别）
        logger.debug("✅ 关键任务健康检查通过：所有到点任务均已执行")

    return all_ok
