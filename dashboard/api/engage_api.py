# -*- coding: utf-8 -*-
"""
dashboard/api/engage_api.py  ·  商业搭讪事件 API（v5.14.0）

端点：
- GET  /api/engage/stats            - 搭讪统计（今日/累计/转化率）
- GET  /api/engage/recent?limit=50  - 最近 N 条搭讪记录
- GET  /api/engage/config           - 读取 PROACTIVE_ENGAGE_CONFIG
- POST /api/engage/config           - 更新 PROACTIVE_ENGAGE_CONFIG（触发 reload_flag）
"""
from flask import Blueprint, jsonify, request
from dashboard.helpers import login_required, admin_required, read_config, write_config, get_db

bp = Blueprint("engage_api", __name__, url_prefix="/api/engage")


@bp.route("/stats", methods=["GET"])
@login_required
def get_stats():
    """搭讪统计一站式查询"""
    try:
        db = get_db()
        if not db:
            return jsonify({"ok": False, "error": "db_not_ready"}), 503

        if hasattr(db, "get_engaged_stats"):
            stats = db.get_engaged_stats()
        else:
            return jsonify({"ok": False, "error": "method_not_registered"}), 501

        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/recent", methods=["GET"])
@login_required
def get_recent():
    """获取最近 N 条搭讪记录"""
    try:
        limit = int(request.args.get("limit", 50))
        limit = min(max(1, limit), 200)  # 限制 1-200
        uid_filter = int(request.args.get("uid", 0))

        db = get_db()
        if not db:
            return jsonify({"ok": False, "error": "db_not_ready"}), 503

        if hasattr(db, "get_recent_engages"):
            rows = db.get_recent_engages(limit=limit, uid=uid_filter)
        else:
            return jsonify({"ok": False, "error": "method_not_registered"}), 501

        return jsonify({"ok": True, "data": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/config", methods=["GET"])
@login_required
def get_config():
    """读取 PROACTIVE_ENGAGE_CONFIG"""
    try:
        cfg = read_config()
        engage_cfg = cfg.get("PROACTIVE_ENGAGE_CONFIG", {})
        # 默认值
        defaults = {
            "enabled": False,
            "cooldown_minutes": 30,
            "max_per_user_per_day": 3,
            "only_in_group_id": True,
        }
        for k, v in defaults.items():
            engage_cfg.setdefault(k, v)
        return jsonify({"ok": True, "data": engage_cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/config", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def update_config():
    """更新 PROACTIVE_ENGAGE_CONFIG（自动触发 reload_flag）"""
    try:
        payload = request.get_json(silent=True) or {}
        cfg = read_config()

        # 允许的字段白名单
        allowed_keys = {"enabled", "cooldown_minutes", "max_per_user_per_day", "only_in_group_id"}
        updates = {k: v for k, v in payload.items() if k in allowed_keys}

        if "enabled" in updates:
            updates["enabled"] = bool(updates["enabled"])
        if "cooldown_minutes" in updates:
            updates["cooldown_minutes"] = max(1, int(updates["cooldown_minutes"]))
        if "max_per_user_per_day" in updates:
            updates["max_per_user_per_day"] = max(0, int(updates["max_per_user_per_day"]))
        if "only_in_group_id" in updates:
            updates["only_in_group_id"] = bool(updates["only_in_group_id"])

        # 合并更新
        existing = cfg.get("PROACTIVE_ENGAGE_CONFIG", {})
        existing.update(updates)
        cfg["PROACTIVE_ENGAGE_CONFIG"] = existing

        # 写入（write_config 内部触发 reload_flag）
        write_config(cfg)

        return jsonify({"ok": True, "data": existing, "updated_keys": list(updates.keys())})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
