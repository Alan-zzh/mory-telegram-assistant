# -*- coding: utf-8 -*-
"""
dashboard/api/quality_api.py · 内容质量评估 API

[v5.26.0] 提供 2 个端点：
  GET /api/quality/scores  - 获取平均评分（最近 N 天）
  GET /api/quality/trend   - 获取评分趋势（按天聚合）

数据来源：interaction_quality_scores 表（由 modules/auto_tasks.py 每日凌晨写入）
"""
from threading import RLock

from flask import Blueprint, request, jsonify, session
from dashboard.helpers import login_required, admin_required, get_db
from core.db_repos.reply_evolution_repo import ReplyEvolutionRepo
from core.logging_util import get_logger

logger = get_logger("quality_api")

quality_bp = Blueprint("quality", __name__, url_prefix="/api")
_reply_style_lock = RLock()


class _DashboardRepoAdapter:
    """让 Dashboard 的 sqlite 连接复用 DB Repository 的校验与工作流。"""

    def __init__(self, conn):
        self.conn = conn
        self.lock = _reply_style_lock


def _style_sample_db():
    db = get_db()
    if not db:
        return None, (jsonify({"ok": False, "msg": "数据库未就绪"}), 503)
    # Dashboard 使用 sqlite3.Connection；Bot 主进程使用 core.database.DB。
    # 两种入口均复用同一个 Repository，避免 Dashboard 永远返回 501。
    if hasattr(db, "create_reply_style_sample"):
        return db, None
    if not hasattr(db, "execute"):
        return None, (jsonify({"ok": False, "msg": "回复风格样本库未就绪"}), 501)
    repo = ReplyEvolutionRepo(_DashboardRepoAdapter(db))
    if not repo._ensure_schema():
        return None, (jsonify({"ok": False, "msg": "回复风格样本库未就绪"}), 503)
    return repo, None


@quality_bp.route("/quality/reply-style-samples", methods=["GET"])
@login_required
@admin_required
def list_reply_style_samples():
    """查看人工维护的风格样本；不暴露或采集用户原始聊天内容。"""
    db, error = _style_sample_db()
    if error:
        return error
    status = (request.args.get("status") or "").strip().lower() or None
    limit = min(max(request.args.get("limit", 100, type=int), 1), 200)
    return jsonify({"ok": True, "data": db.list_reply_style_samples(status=status, limit=limit)})


@quality_bp.route("/quality/reply-style-samples", methods=["POST"])
@login_required
@admin_required
def create_reply_style_sample():
    """管理员提交待审风格样本；样本不会自动启用或自动改 Prompt。"""
    db, error = _style_sample_db()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    result = db.create_reply_style_sample(
        payload.get("style_text", ""),
        label=payload.get("label", ""),
        created_by=session.get("username", "dashboard"),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "msg": result.get("error", "创建失败")}), 400
    return jsonify({"ok": True, "data": result}), 201


@quality_bp.route("/quality/reply-style-samples/<int:sample_id>/review", methods=["POST"])
@login_required
@admin_required
def review_reply_style_sample(sample_id: int):
    """显式通过或拒绝样本；批准不等于启用，启用仍需管理员选择。"""
    db, error = _style_sample_db()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    result = db.review_reply_style_sample(
        sample_id,
        payload.get("status", ""),
        reviewed_by=session.get("username", "dashboard"),
        review_note=payload.get("review_note", ""),
        enabled=bool(payload.get("enabled", False)),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "msg": result.get("error", "审核失败")}), 400
    return jsonify({"ok": True, "data": result})


@quality_bp.route("/quality/reply-style-samples/<int:sample_id>/enabled", methods=["POST"])
@login_required
@admin_required
def set_reply_style_sample_enabled(sample_id: int):
    """手动启停已审核样本，始终不修改 config.json 或基础人设。"""
    db, error = _style_sample_db()
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"ok": False, "msg": "enabled 为必填项"}), 400
    result = db.set_reply_style_sample_enabled(
        sample_id,
        bool(payload["enabled"]),
        reviewed_by=session.get("username", "dashboard"),
    )
    if not result.get("ok"):
        return jsonify({"ok": False, "msg": result.get("error", "更新失败")}), 400
    return jsonify({"ok": True, "data": result})


@quality_bp.route("/quality/scores")
@login_required
def api_quality_scores():
    """获取平均评分（最近 N 天）
    ---
    tags:
      - 内容质量
    summary: 获取对话质量平均评分
    description: |
      返回最近 N 天的平均评分（自然度/相关性/人格一致性）。
      数据来源：interaction_quality_scores 表。
    parameters:
      - name: days
        in: query
        type: integer
        default: 7
        description: 统计天数（默认 7 天，最大 90 天）
    responses:
      200:
        description: 成功返回平均评分
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            avg_naturalness:
              type: number
              example: 4.2
            avg_relevance:
              type: number
              example: 4.0
            avg_persona:
              type: number
              example: 4.1
            total_evaluated:
              type: integer
              example: 150
            days:
              type: integer
              example: 7
    """
    try:
        days = min(90, max(1, request.args.get("days", 7, type=int)))
        db = get_db()

        from core.quality_evaluator import get_average_scores
        result = get_average_scores(db, days=days)

        return jsonify({
            "ok": True,
            **result,
        })
    except Exception as e:
        logger.error(f"获取平均评分失败: {e}")
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@quality_bp.route("/quality/trend")
@login_required
def api_quality_trend():
    """获取评分趋势（按天聚合）
    ---
    tags:
      - 内容质量
    summary: 获取对话质量评分趋势
    description: |
      返回最近 N 天的评分趋势（按天聚合）。
      数据来源：interaction_quality_scores 表。
    parameters:
      - name: days
        in: query
        type: integer
        default: 30
        description: 趋势天数（默认 30 天，最大 180 天）
    responses:
      200:
        description: 成功返回趋势数据
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            trend:
              type: array
              items:
                type: object
                properties:
                  date:
                    type: string
                    example: "2026-06-17"
                  avg_naturalness:
                    type: number
                    example: 4.2
                  avg_relevance:
                    type: number
                    example: 4.0
                  avg_persona:
                    type: number
                    example: 4.1
                  count:
                    type: integer
                    example: 20
            days:
              type: integer
              example: 30
    """
    try:
        days = min(180, max(1, request.args.get("days", 30, type=int)))
        db = get_db()

        from core.quality_evaluator import get_score_trend
        trend = get_score_trend(db, days=days)

        return jsonify({
            "ok": True,
            "trend": trend,
            "days": days,
        })
    except Exception as e:
        logger.error(f"获取评分趋势失败: {e}")
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500
