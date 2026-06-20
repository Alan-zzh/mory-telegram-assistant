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
                    except Exception:
                        pass
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
