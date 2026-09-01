# -*- coding: utf-8 -*-
"""调度监控 API（v5.23.0 P2-6）"""
from flask import Blueprint, jsonify
from dashboard.helpers import login_required, admin_required
from dashboard.helpers import get_db
from core.logging_util import get_logger

logger = get_logger(__name__)

scheduler_bp = Blueprint("scheduler_monitor", __name__)


def _normalize_job_metric(info: dict) -> dict:
    """区分当前错误和已恢复任务的历史失败，避免 Dashboard 把旧错当现错。"""
    normalized = dict(info)
    status = str(normalized.get("last_status") or "").lower()
    last_failure_error = str(normalized.get("last_error") or "")
    current_error = last_failure_error if status == "error" else ""

    normalized["last_failure_error"] = last_failure_error
    normalized["last_error"] = current_error
    if status == "error":
        normalized["error_scope"] = "current"
    elif last_failure_error:
        normalized["error_scope"] = "historical"
    else:
        normalized["error_scope"] = "none"
    return normalized


def _normalize_stats_payload(stats: dict) -> dict:
    normalized = dict(stats)
    jobs = normalized.get("jobs") or {}
    normalized["jobs"] = {
        job_id: _normalize_job_metric(info)
        for job_id, info in jobs.items()
    }
    return normalized


def _scheduler_stats_from_db() -> dict:
    """读取持久历史指标；scheduler_metrics 不是当前注册任务表。"""
    db = get_db()
    rows = db.execute(
        """
        SELECT job_id, last_status, success_count, fail_count, miss_count,
               last_run, last_status_at, last_duration, last_error, synced_at
        FROM scheduler_metrics
        ORDER BY COALESCE(last_status_at, last_run, 0) DESC
        """
    ).fetchall()
    jobs = {}
    total_success = 0
    total_fail = 0
    total_miss = 0
    started_at = 0
    for row in rows:
        info = dict(row)
        job_id = info.pop("job_id")
        total_success += int(info.get("success_count") or 0)
        total_fail += int(info.get("fail_count") or 0)
        total_miss += int(info.get("miss_count") or 0)
        last_run = int(info.get("last_run") or 0)
        if started_at == 0 or (last_run and last_run < started_at):
            started_at = last_run
        jobs[job_id] = _normalize_job_metric(info)
    return {
        "started_at": started_at,
        "uptime_seconds": 0,
        "total_success": total_success,
        "total_fail": total_fail,
        "total_miss": total_miss,
        "job_count": None,
        "historical_job_count": len(jobs),
        "jobs": jobs,
        "source": "scheduler_metrics_history",
        "registry_available": False,
    }


def _scheduler_jobs_from_db() -> list:
    db = get_db()
    rows = db.execute(
        """
        SELECT job_id, last_status, success_count, fail_count, miss_count,
               last_run, last_status_at, last_duration, last_error, synced_at
        FROM scheduler_metrics
        ORDER BY COALESCE(last_status_at, last_run, 0) DESC
        """
    ).fetchall()
    jobs = []
    for row in rows:
        info = _normalize_job_metric(dict(row))
        jobs.append({
            "id": info.get("job_id"),
            "name": info.get("job_id"),
            "next_run": "Bot进程内调度，Dashboard读取落盘指标",
            "trigger": "scheduler_metrics",
            "max_instances": 1,
            "coalesce": True,
            "last_status": info.get("last_status"),
            "success_count": info.get("success_count") or 0,
            "fail_count": info.get("fail_count") or 0,
            "miss_count": info.get("miss_count") or 0,
            "last_run": info.get("last_run") or 0,
            "last_status_at": info.get("last_status_at") or 0,
            "last_error": info.get("last_error") or "",
            "last_failure_error": info.get("last_failure_error") or "",
            "error_scope": info.get("error_scope") or "none",
        })
    return jobs


@scheduler_bp.route("/api/scheduler/stats", methods=["GET"])
@login_required
def api_scheduler_stats():
    """获取调度指标；分进程时明确返回历史覆盖而非当前注册数。"""
    try:
        from core.scheduler_monitor import get_scheduler_stats
        stats = get_scheduler_stats()
        if not stats.get("job_count"):
            stats = _scheduler_stats_from_db()
        else:
            stats = _normalize_stats_payload(stats)
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        logger.exception(f"[scheduler_api] api_scheduler_stats 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@scheduler_bp.route("/api/scheduler/jobs", methods=["GET"])
@admin_required
def api_scheduler_jobs():
    """获取调度器当前所有任务列表（仅 admin）"""
    try:
        from core.scheduler_monitor import get_job_list
        from tasks.task_scheduler import get_scheduler_instance
        _scheduler_instance = get_scheduler_instance()
        jobs = get_job_list(_scheduler_instance) if _scheduler_instance else []
        source = "memory"
        if not jobs:
            historical = _scheduler_jobs_from_db()
            return jsonify({
                "ok": True,
                "data": [],
                "count": 0,
                "source": "unavailable",
                "registry_available": False,
                "historical_metrics_count": len(historical),
                "note": "Dashboard与Bot分进程，scheduler_metrics仅为历史，不能冒充当前注册任务",
            })
        return jsonify({
            "ok": True,
            "data": jobs,
            "count": len(jobs),
            "source": source,
            "registry_available": True,
        })
    except Exception as e:
        logger.exception(f"[scheduler_api] api_scheduler_jobs 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500
