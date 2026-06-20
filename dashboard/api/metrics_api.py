# -*- coding: utf-8 -*-
"""
dashboard/api/metrics_api.py · Prometheus 指标暴露端点

端点：
  GET /api/v1/metrics - 返回 Prometheus 文本格式指标（仅 admin 可访问）
"""

from flask import Blueprint, Response, session, jsonify
from core.logging_util import get_logger

logger = get_logger("metrics_api")

metrics_bp = Blueprint("metrics", __name__, url_prefix="/api/v1")


@metrics_bp.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """
    Prometheus 指标暴露端点

    权限控制：仅 admin 角色可访问
    返回格式：text/plain; version=0.0.4（Prometheus  exposition format）
    """
    # 权限校验：仅 admin 可访问
    if not session.get("logged_in"):
        return jsonify({"ok": False, "msg": "未登录，请先登录 Dashboard"}), 401

    if session.get("role", "viewer") != "admin":
        return jsonify({"ok": False, "msg": "需要管理员权限才能访问指标端点"}), 403

    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        # 生成 Prometheus 格式指标
        metrics_output = generate_latest()

        return Response(
            metrics_output,
            mimetype=CONTENT_TYPE_LATEST,
            headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}
        )

    except ImportError:
        logger.error("❌ prometheus-client 未安装，无法暴露指标端点")
        return jsonify({
            "ok": False,
            "msg": "prometheus-client 未安装，请在 requirements.txt 中启用该依赖"
        }), 501

    except Exception as e:
        logger.error(f"❌ 指标端点生成失败: {e}")
        return jsonify({"ok": False, "msg": f"指标生成失败: {str(e)}"}), 500
