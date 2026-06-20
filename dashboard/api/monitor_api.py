# -*- coding: utf-8 -*-
"""
dashboard/api/monitor_api.py · 监控 API（v5.24.0 阶段3-B DB 迁移时机指标监控）

端点：
  GET /api/db-migration/status  - 返回 5 项 DB 迁移指标的实时值和阈值
"""
from flask import Blueprint, jsonify
from dashboard.helpers import login_required

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api")


@monitor_bp.route("/db-migration/status", methods=["GET"])
@login_required
def api_db_migration_status():
    """获取 DB 迁移时机指标实时状态（登录用户可看）

    返回 5 项指标的当前值、阈值、是否超阈值：
    - max_write_qps_last_24h: 最近 24h 最大写入 QPS（阈值 80）
    - sqlite_file_size_gb: mory.db 文件大小 GB（阈值 8.0）
    - average_write_queue_delay_seconds: 平均写入队列延迟秒数（阈值 2.0）
    - write_queue_pending_often_gt_200: 队列积压频率（阈值 200，占比 >30% 视为经常性）
    - read_connection_count: 当前持有 db 文件的进程数（阈值 50）

    注意：Dashboard 进程与 Bot 进程独立，write_queue 相关指标在 Dashboard 端
    可能显示 0（Dashboard 进程不执行写入）。主要监控由 Bot 进程的每小时定时任务完成。
    """
    try:
        from core.db_migration_monitor import get_migration_status
        from dashboard.helpers import get_db
        db = get_db()
        status = get_migration_status(db)
        return jsonify(status)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
