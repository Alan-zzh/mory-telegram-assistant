# -*- coding: utf-8 -*-
"""调度监控 API（v5.23.0 P2-6）"""
from flask import Blueprint, jsonify
from dashboard.helpers import login_required, admin_required

scheduler_bp = Blueprint("scheduler_monitor", __name__)


@scheduler_bp.route("/api/scheduler/stats", methods=["GET"])
@login_required
def api_scheduler_stats():
    """获取调度器统计指标（登录用户可看）"""
    try:
        from core.scheduler_monitor import get_scheduler_stats
        stats = get_scheduler_stats()
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@scheduler_bp.route("/api/scheduler/jobs", methods=["GET"])
@admin_required
def api_scheduler_jobs():
    """获取调度器当前所有任务列表（仅 admin）"""
    try:
        from core.scheduler_monitor import get_job_list
        from modules.auto_tasks import _scheduler_instance
        if not _scheduler_instance:
            return jsonify({"ok": False, "msg": "调度器未初始化"}), 503
        jobs = get_job_list(_scheduler_instance)
        return jsonify({"ok": True, "data": jobs, "count": len(jobs)})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
