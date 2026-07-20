# -*- coding: utf-8 -*-
"""A/B 测试与按钮统计 API（v5.18.0）"""
from flask import Blueprint, jsonify, request

# 【TRAE SOLO CN v5.18.3审计修复】从 helpers 导入 admin_required（auth.py 版本已删除，因实现失效）
from dashboard.helpers import login_required, admin_required
from core.profile_learner import ProfileLearner
from core.logging_util import get_logger

logger = get_logger(__name__)

ab_test_bp = Blueprint("ab_test", __name__)
button_stats_bp = Blueprint("button_stats", __name__)


def _get_db():
    """从主模块获取 db 实例（兼容部署场景）。"""
    try:
        from main import db
        return db
    except Exception:
        try:
            from dashboard.app import db
            return db
        except Exception:
            return None


def _get_config():
    """获取当前配置。"""
    try:
        from core.config import get_config
        return get_config()
    except Exception:
        try:
            from main import config
            return config
        except Exception:
            return {}


# ── A/B 测试 API ────────────────────────────────────────────

@ab_test_bp.route("/api/ab-test/stats", methods=["GET"])
@login_required
def get_ab_test_stats():
    """获取 A/B 测试统计。"""
    db = _get_db()
    if not db or not hasattr(db, "get_ab_test_stats"):
        return jsonify({"ok": True, "data": {
            "html_sent": 0, "html_conversions": 0,
            "rich_sent": 0, "rich_conversions": 0
        }})
    try:
        stats = db.get_ab_test_stats()
        return jsonify({"ok": True, "data": stats})
    except Exception as e:
        logger.warning(f"获取 A/B 测试统计失败: {e}")
        return jsonify({"ok": True, "data": {
            "html_sent": 0, "html_conversions": 0,
            "rich_sent": 0, "rich_conversions": 0
        }})


@ab_test_bp.route("/api/ab-test/record-sent", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def record_ab_test_sent():
    """记录 A/B 测试发送数（内部调用）。"""
    db = _get_db()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    data = request.get_json() or {}
    group_name = data.get("group_name", "default")
    format_version = data.get("format_version", "html")
    count = int(data.get("count", 1))
    try:
        db.record_ab_test_sent(group_name, format_version, count)
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"[ab_test_api] record_ab_test_sent 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@ab_test_bp.route("/api/ab-test/significance", methods=["GET"])
@login_required
def get_ab_test_significance():
    """获取 A/B 测试统计显著性检验结果

    Query 参数:
        days: 回溯天数（默认 7）
        alpha: 显著性水平阈值（默认 0.05，即 95% 置信度）

    返回:
        统计显著性结果，包含卡方检验（转化率）和 Z 检验（延迟），
        p-value < alpha 表示差异显著，并给出胜出组推荐。
    """
    try:
        from core.ab_test_router import get_significance_report
    except ImportError:
        return jsonify({"ok": False, "msg": "ab_test_router 模块不可用"}), 500

    days = min(90, max(1, int(request.args.get("days", 7))))
    alpha = float(request.args.get("alpha", 0.05))
    if alpha <= 0 or alpha >= 1:
        alpha = 0.05

    try:
        report = get_significance_report(days=days, alpha=alpha)
        return jsonify({"ok": True, "data": report})
    except Exception as e:
        logger.exception(f"[ab_test_api] get_ab_test_significance 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


# ── 按钮统计 API ────────────────────────────────────────────

@button_stats_bp.route("/api/button-stats/stats", methods=["GET"])
@login_required
def get_button_stats():
    """获取按钮点击统计。"""
    db = _get_db()
    if not db or not hasattr(db, "get_button_stats"):
        return jsonify({"ok": True, "data": {"stats": []}})
    try:
        stats = db.get_button_stats()
        return jsonify({"ok": True, "data": {"stats": stats}})
    except Exception as e:
        logger.warning(f"获取按钮统计失败: {e}")
        return jsonify({"ok": True, "data": {"stats": []}})


@button_stats_bp.route("/api/button-stats/record", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def record_button_event():
    """记录按钮事件（impression/click）。"""
    db = _get_db()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    data = request.get_json() or {}
    button_id = str(data.get("button_id", "")).strip()
    style = str(data.get("style", "default")).strip()
    event = str(data.get("event", "")).strip()  # "impression" or "click"
    if not button_id or event not in ("impression", "click"):
        return jsonify({"ok": False, "msg": "参数错误"}), 400
    try:
        if event == "impression":
            db.record_button_impression(button_id, style)
        else:
            db.record_button_click(button_id, style)
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception(f"[ab_test_api] record_button_event 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


# ── 用户画像 API（v5.18.0） ────────────────────────────────────────────

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/api/profile/learn", methods=["POST"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】写操作需管理员权限
def learn_profile():
    """从消息学习用户画像（内部调用）。"""
    db = _get_db()
    config = _get_config()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    data = request.get_json() or {}
    user_id = data.get("user_id")
    text = data.get("text", "")
    if not user_id or not text:
        return jsonify({"ok": False, "msg": "参数错误"}), 400
    try:
        learner = ProfileLearner(db, config)
        profile = learner.learn_from_message(int(user_id), text)
        return jsonify({"ok": True, "data": profile})
    except Exception as e:
        logger.exception(f"[ab_test_api] learn_profile 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@profile_bp.route("/api/profile/list", methods=["GET"])
@login_required
@admin_required
def list_profiles():
    """列出用户画像。"""
    db = _get_db()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    min_level = int(request.args.get("min_level", 0))
    tag = request.args.get("tag", "").strip()
    limit = min(500, int(request.args.get("limit", 100)))
    try:
        profiles = db.list_user_profiles(min_level, tag, limit)
        return jsonify({"ok": True, "data": {"profiles": profiles, "count": len(profiles)}})
    except Exception as e:
        logger.exception(f"[ab_test_api] list_profiles 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500


@profile_bp.route("/api/profile/<int:user_id>", methods=["GET"])
@login_required
@admin_required  # 【TRAE SOLO CN v5.18.3审计修复】查看任意用户画像需管理员权限
def get_profile(user_id: int):
    """获取单个用户画像。"""
    db = _get_db()
    if not db:
        return jsonify({"ok": False, "msg": "数据库不可用"}), 500
    try:
        profile = db.get_user_persona_profile(user_id)
        return jsonify({"ok": True, "data": profile})
    except Exception as e:
        logger.exception(f"[ab_test_api] get_profile 失败: {e}")
        return jsonify({"ok": False, "msg": "internal_error"}), 500
