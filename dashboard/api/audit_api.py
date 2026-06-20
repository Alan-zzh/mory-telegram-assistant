# -*- coding: utf-8 -*-
"""审计日志 API（v5.23.0 P1-3）"""
from flask import Blueprint, jsonify, request
from dashboard.helpers import login_required, admin_required
from dashboard.audit import get_audit_logs, get_audit_stats, cleanup_old_audit_logs

audit_bp = Blueprint("audit", __name__)


@audit_bp.route("/api/audit/logs", methods=["GET"])
@admin_required
def api_audit_logs():
    """查询审计日志（仅 admin）"""
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))
    allowed_only = request.args.get("allowed_only", "").lower() in ("1", "true", "yes")
    denied_only = request.args.get("denied_only", "").lower() in ("1", "true", "yes")
    operator_id = int(request.args.get("operator_id", 0))

    logs = get_audit_logs(
        limit=limit, offset=offset,
        allowed_only=allowed_only, denied_only=denied_only,
        operator_id=operator_id,
    )
    return jsonify({"ok": True, "data": logs, "count": len(logs)})


@audit_bp.route("/api/audit/stats", methods=["GET"])
@admin_required
def api_audit_stats():
    """审计日志统计（仅 admin）"""
    stats = get_audit_stats()
    return jsonify({"ok": True, "data": stats})


@audit_bp.route("/api/audit/cleanup", methods=["POST"])
@admin_required
def api_audit_cleanup():
    """手动清理旧审计日志（仅 admin，默认清理 90 天前）"""
    days = int(request.json.get("days", 90)) if request.is_json else 90
    days = max(days, 7)  # 至少保留 7 天
    deleted = cleanup_old_audit_logs(days=days)
    return jsonify({"ok": True, "deleted": deleted, "days_threshold": days})
