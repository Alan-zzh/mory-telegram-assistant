# -*- coding: utf-8 -*-
"""
dashboard/api/monitor_api.py · 监控 API（v5.24.0 阶段3-B DB 迁移时机指标监控）

端点：
  GET /api/db-migration/status  - 返回 DB 迁移指标的实时值和阈值
  GET /api/llm-cost/stats        - 返回 LLM 成本熔断器统计（v5.31.2 审计整改）
"""
import time
from flask import Blueprint, jsonify
from dashboard.helpers import login_required, read_config
from core.logging_util import get_logger

logger = get_logger(__name__)

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api")


@monitor_bp.route("/db-migration/status", methods=["GET"])
@login_required
def api_db_migration_status():
    """获取 DB 迁移时机指标实时状态（登录用户可看）

    返回各项指标的当前值、阈值、是否超阈值：
    - sqlite_file_size_gb: mory.db 文件大小 GB（阈值 8.0）
    - read_connection_count: 当前持有 db 文件的进程数（阈值 50）

    历史（v5.41.0）：write_queue 相关三项死指标已随写队列删除而移除。
    主要监控由 Bot 进程的定时任务完成。
    """
    try:
        from core.db_migration_monitor import get_migration_status
        from dashboard.helpers import get_db
        db = get_db()
        status = get_migration_status(db)
        return jsonify(status)
    except Exception as e:
        logger.exception(f"[monitor_api] api_db_migration_status 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@monitor_bp.route("/llm-cost/stats", methods=["GET"])
@login_required
def api_llm_cost_stats():
    """【v5.31.2 审计整改】LLM 成本熔断器统计端点

    兑现 docs/technical/llm-cost-guard.md 中承诺的 /api/llm-cost/stats 端点。

    数据来源：
    1. config.json 的 LLM_COST_* 阈值配置（enabled / 各档限额）
    2. llm_cost_logs 表的历史消费记录（total_calls / total_cost / hourly / daily）
    3. 注：Bot 进程内存中的实时降级状态（_downgraded_users / _global_downgrade_until）
       无法跨进程读取，Dashboard 端仅展示历史数据 + 阈值。

    返回字段：
      - enabled: 熔断器是否启用
      - thresholds: 各档阈值（user_hourly / global_hourly / user_daily / global_daily）
      - total_calls / total_cost: 全量历史统计
      - global_hourly_cost / global_hourly_limit: 最近 1h 消费与阈值
      - global_daily_cost / global_daily_limit: 最近 24h 消费与阈值
      - top_users: 最近 24h 消费 Top 5 用户
      - recent_calls: 最近 20 条调用记录
      - in_memory_state_unavailable: 跨进程不可读标记（True=Dashboard 端无法读取实时降级状态）
    """
    try:
        from dashboard.helpers import get_db
        cfg = read_config() or {}
        enabled = bool(cfg.get("LLM_COST_GUARD_ENABLED", False))
        thresholds = {
            "user_hourly_limit": float(cfg.get("LLM_COST_USER_HOURLY_LIMIT", 1.0)),
            "global_hourly_limit": float(cfg.get("LLM_COST_GLOBAL_HOURLY_LIMIT", 5.0)),
            "user_daily_limit": float(cfg.get("LLM_COST_USER_DAILY_LIMIT", 10.0)),
            "global_daily_limit": float(cfg.get("LLM_COST_GLOBAL_DAILY_LIMIT", 50.0)),
        }
        now = int(time.time())
        cutoff_1h = now - 3600
        cutoff_24h = now - 86400

        db = get_db()

        # 全量统计
        row = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(estimated_cost), 0.0) FROM llm_cost_logs"
        ).fetchone()
        total_calls = row[0] if row else 0
        total_cost = float(row[1]) if row else 0.0

        # 最近 1h / 24h 全局消费
        global_hourly_cost = float(db.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0.0) FROM llm_cost_logs WHERE timestamp >= ?",
            (cutoff_1h,)
        ).fetchone()[0] or 0.0)
        global_daily_cost = float(db.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0.0) FROM llm_cost_logs WHERE timestamp >= ?",
            (cutoff_24h,)
        ).fetchone()[0] or 0.0)

        # 最近 24h Top 5 消费用户
        top_users_rows = db.execute(
            "SELECT uid, COUNT(*) as calls, SUM(estimated_cost) as cost "
            "FROM llm_cost_logs WHERE timestamp >= ? "
            "GROUP BY uid ORDER BY cost DESC LIMIT 5",
            (cutoff_24h,)
        ).fetchall()
        top_users = [
            {"uid": r[0], "calls": r[1], "cost": float(r[2] or 0.0)}
            for r in top_users_rows
        ]

        # 最近 20 条调用记录
        recent_rows = db.execute(
            "SELECT uid, model_name, task_type, input_tokens, output_tokens, "
            "estimated_cost, tier, timestamp FROM llm_cost_logs "
            "ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        recent_calls = [
            {
                "uid": r[0], "model_name": r[1], "task_type": r[2],
                "input_tokens": r[3], "output_tokens": r[4],
                "cost": float(r[5] or 0.0), "tier": r[6], "timestamp": r[7],
            }
            for r in recent_rows
        ]

        return jsonify({
            "ok": True,
            "enabled": enabled,
            "thresholds": thresholds,
            "total_calls": total_calls,
            "total_cost": round(total_cost, 4),
            "global_hourly_cost": round(global_hourly_cost, 4),
            "global_hourly_limit": thresholds["global_hourly_limit"],
            "global_daily_cost": round(global_daily_cost, 4),
            "global_daily_limit": thresholds["global_daily_limit"],
            "top_users": top_users,
            "recent_calls": recent_calls,
            # 跨进程不可读：Bot 进程内存中的实时降级状态无法在 Dashboard 端读取
            "in_memory_state_unavailable": True,
        })
    except Exception as e:
        logger.exception(f"[monitor_api] api_llm_cost_stats 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500
