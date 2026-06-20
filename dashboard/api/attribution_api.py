# -*- coding: utf-8 -*-
"""转化归因 API（v5.23.0 P1-4 / v5.24.0 阶段3-C 归因报表聚合）"""
import time
from flask import Blueprint, jsonify, request
from dashboard.helpers import login_required, admin_required, read_config

attribution_bp = Blueprint("attribution", __name__)


def _check_enabled():
    """归因报表功能开关检查（默认关闭）"""
    return bool(read_config().get("ATTRIBUTION_REPORT_ENABLED", False))


@attribution_bp.route("/api/attribution/report", methods=["GET"])
@admin_required
def api_attribution_report():
    """获取转化归因报表（仅 admin）

    查询参数：
        days: 回溯天数（默认 7）
    """
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from core.funnel_state_machine import FunnelStateMachine
        from dashboard.helpers import get_db
        db = get_db()
        fsm = FunnelStateMachine(db)
        report = fsm.get_attribution_report(days=days)
        return jsonify({"ok": True, "data": report, "count": len(report), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/user/<int:uid>", methods=["GET"])
@admin_required
def api_attribution_user(uid: int):
    """查询单用户归因详情（仅 admin）"""
    try:
        from core.funnel_state_machine import FunnelStateMachine
        from dashboard.helpers import get_db
        db = get_db()
        fsm = FunnelStateMachine(db)
        attr = fsm.attribute_conversion(uid, window_hours=48)
        return jsonify({"ok": True, "data": attr})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/by-campaign", methods=["GET"])
@admin_required
def api_attribution_by_campaign():
    """按 Campaign(播报任务) 维度聚合归因（仅 admin）

    返回: [{campaign_id, campaign_name, clicks, carts, conversions, cr}, ...]
    """
    if not _check_enabled():
        return jsonify({"ok": True, "data": [], "count": 0, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from dashboard.helpers import get_db
        db = get_db()
        cutoff = int(time.time()) - days * 86400
        rows = db.execute(
            "SELECT campaign_id, "
            "SUM(CASE WHEN event='interested' THEN 1 ELSE 0 END) AS clicks, "
            "SUM(CASE WHEN event='carted' THEN 1 ELSE 0 END) AS carts, "
            "SUM(CASE WHEN event='converted' THEN 1 ELSE 0 END) AS conversions "
            "FROM conversion_events WHERE ts > ? AND campaign_id != '' "
            "GROUP BY campaign_id ORDER BY conversions DESC",
            (cutoff,)
        ).fetchall()
        data = []
        for r in rows:
            clicks = r[1] or 0
            conv = r[3] or 0
            cr = round(conv / clicks * 100, 2) if clicks > 0 else 0.0
            data.append({
                "campaign_id": r[0], "campaign_name": r[0],
                "clicks": clicks, "carts": r[2] or 0,
                "conversions": conv, "cr": cr,
            })
        return jsonify({"ok": True, "data": data, "count": len(data), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/by-hour", methods=["GET"])
@admin_required
def api_attribution_by_hour():
    """按时段维度聚合归因（仅 admin）

    返回: [{hour(0-23), conversions, total_events}, ...]
    """
    if not _check_enabled():
        return jsonify({"ok": True, "data": [], "count": 0, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from dashboard.helpers import get_db
        db = get_db()
        cutoff = int(time.time()) - days * 86400
        # 按 +8 时区提取小时（0-23）
        rows = db.execute(
            "SELECT CAST(strftime('%H', datetime(ts, 'unixepoch', '+8 hours')) AS INTEGER) AS hour, "
            "SUM(CASE WHEN event='converted' THEN 1 ELSE 0 END) AS conversions, "
            "COUNT(*) AS total_events "
            "FROM conversion_events WHERE ts > ? GROUP BY hour ORDER BY hour",
            (cutoff,)
        ).fetchall()
        data = [{"hour": r[0], "conversions": r[1] or 0, "total_events": r[2] or 0} for r in rows]
        return jsonify({"ok": True, "data": data, "count": len(data), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/by-persona", methods=["GET"])
@admin_required
def api_attribution_by_persona():
    """按人设桶维度聚合归因（仅 admin）

    persona_bucket 取自 conversion_events.mode 字段，空值归为 common。
    返回: [{persona_bucket, interested_count, total_count, conversion_rate}, ...]
    """
    if not _check_enabled():
        return jsonify({"ok": True, "data": [], "count": 0, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from dashboard.helpers import get_db
        db = get_db()
        cutoff = int(time.time()) - days * 86400
        rows = db.execute(
            "SELECT CASE WHEN mode='' OR mode IS NULL THEN 'common' ELSE mode END AS persona_bucket, "
            "SUM(CASE WHEN event='interested' THEN 1 ELSE 0 END) AS interested_count, "
            "COUNT(*) AS total_count, "
            "SUM(CASE WHEN event='converted' THEN 1 ELSE 0 END) AS converted_count "
            "FROM conversion_events WHERE ts > ? GROUP BY persona_bucket ORDER BY total_count DESC",
            (cutoff,)
        ).fetchall()
        data = []
        for r in rows:
            total = r[2] or 0
            conv = r[3] or 0
            cr = round(conv / total * 100, 2) if total > 0 else 0.0
            data.append({
                "persona_bucket": r[0], "interested_count": r[1] or 0,
                "total_count": total, "conversion_rate": cr,
            })
        return jsonify({"ok": True, "data": data, "count": len(data), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/ab-test/report", methods=["GET"])
@admin_required
def api_ab_test_report():
    """多模型路由 A/B 测试报表（阶段2-C，仅 admin）

    返回各组的：平均延迟 / P95延迟 / 平均成本 / 转化率 / 样本数
    数据从 ab_test_metrics 表聚合。

    查询参数：
        days: 回溯天数（默认 7）
    """
    # A/B 测试开关检查（默认关闭）
    cfg = read_config()
    if not cfg.get("AB_TEST_ENABLED", False):
        return jsonify({"ok": True, "data": [], "count": 0, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from core.ab_test_router import get_report
        report = get_report(days=days)
        return jsonify({"ok": True, "data": report, "count": len(report), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/memory-impact", methods=["GET"])
@admin_required
def api_attribution_memory_impact():
    """【阶段3-A】记忆系统对转化率的提升归因（仅 admin）

    对比有记忆辅助 vs 无记忆辅助的会话转化率，量化记忆系统 ROI。
    查询参数：
        days: 回溯天数（默认 7）
    返回: {memory_assisted: {carted_rate, converted_rate, count}, non_assisted: {...}, lift_ratio: {...}}
    """
    if not _check_enabled():
        return jsonify({"ok": True, "data": None, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from core.funnel_state_machine import FunnelStateMachine
        from dashboard.helpers import get_db
        db = get_db()
        fsm = FunnelStateMachine(db)
        report = fsm.get_memory_attribution_report(days=days)
        return jsonify({"ok": True, "data": report, "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@attribution_bp.route("/api/attribution/growth-summary", methods=["GET"])
@admin_required
def api_attribution_growth_summary():
    """10 项增长优化汇总（仅 admin）

    数据来自 conversion_events / telemetry_events，按增长实验维度聚合。
    """
    if not _check_enabled():
        return jsonify({"ok": True, "data": [], "count": 0, "disabled": True})
    try:
        days = min(int(request.args.get("days", 7)), 90)
        from dashboard.helpers import get_db
        from core.growth_optimizer import summarize_growth
        db = get_db()
        data = summarize_growth(db, days=days)
        return jsonify({"ok": True, "data": data, "count": len(data), "days": days})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
