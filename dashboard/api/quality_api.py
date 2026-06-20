# -*- coding: utf-8 -*-
"""
dashboard/api/quality_api.py · 内容质量评估 API

[v5.26.0] 提供 2 个端点：
  GET /api/quality/scores  - 获取平均评分（最近 N 天）
  GET /api/quality/trend   - 获取评分趋势（按天聚合）

数据来源：interaction_quality_scores 表（由 modules/auto_tasks.py 每日凌晨写入）
"""
from flask import Blueprint, request, jsonify
from dashboard.helpers import login_required, get_db
from core.logging_util import get_logger

logger = get_logger("quality_api")

quality_bp = Blueprint("quality", __name__, url_prefix="/api")


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
