#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory Assistant - 私域可视化面板
v6.0 - 全新设计（深色主题/数据可视化/实时监控/专业级UI）
Build: 2026-04-26
"""
import os
import sys
from functools import wraps
from flask import Flask, session, jsonify
try:
    from flasgger import Swagger
except ImportError:
    Swagger = None
from dashboard.auth import init_auth
from dashboard.templates.html_page import HTML_PAGE, LOGIN_PAGE
from dashboard.api.stats_api import stats_bp
from dashboard.api.config_api import config_bp
from dashboard.api.group_api import group_bp
from dashboard.api.features_api import features_bp
from dashboard.api.models_api import models_bp
from dashboard.api.settings_api import settings_bp
from dashboard.api.health_api import health_bp
from dashboard.api.orphan_api import orphan_bp  # [Trae CN v5.12.0] 孤儿清理监控
from dashboard.api.engage_api import bp as engage_bp  # [v5.14.0] 商业搭讪 API
from dashboard.api.faq_api import faq_bp  # FAQ 统计与管理 API
from dashboard.api.ab_test_api import ab_test_bp, button_stats_bp, profile_bp  # [v5.18.0] A/B 测试+按钮统计+用户画像
from dashboard.api.audit_api import audit_bp  # [v5.23.0] 审计日志 API
from dashboard.api.attribution_api import attribution_bp  # [v5.23.0] 转化归因 API
from dashboard.api.scheduler_api import scheduler_bp  # [v5.23.0] 调度监控 API
from dashboard.api.monitor_api import monitor_bp  # [v5.24.0 阶段3-B] DB 迁移监控 API
from dashboard.api.bot_routing_api import bot_routing_bp  # [v5.24.0 阶段3-C] 多 Bot 路由管理 API
from dashboard.api.rbac_approval_api import rbac_approval_bp  # [阶段3-E] RBAC 权限审批流 API
from dashboard.api.user_lifecycle_api import user_lifecycle_bp  # [v5.26.0] 用户生命周期分布 API
from dashboard.api.funnel_api import funnel_bp  # [v5.26.0] 转化漏斗可视化 API
from dashboard.api.metrics_api import metrics_bp  # [Prometheus] 指标监控 API
from dashboard.api.quality_api import quality_bp  # [v5.26.0] 内容质量评估 API


def create_app():
    """创建Flask应用"""
    app = Flask(__name__)
    secret = os.environ.get('DASHBOARD_SECRET', '')
    if not secret or len(secret) < 16:
        print("[ERROR] 致命错误：DASHBOARD_SECRET 环境变量未设置或太短（至少16位）！")
        return None
    app.secret_key = secret

    # 注册认证和安全中间件
    init_auth(app)

    # 挂载API蓝图
    app.register_blueprint(stats_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(group_bp)
    app.register_blueprint(features_bp)
    app.register_blueprint(models_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(orphan_bp)  # [Trae CN v5.12.0] 孤儿清理监控
    app.register_blueprint(engage_bp)  # [v5.14.0] 商业搭讪 API
    app.register_blueprint(faq_bp)  # FAQ 统计与管理 API
    app.register_blueprint(ab_test_bp)  # [v5.18.0] A/B 测试
    app.register_blueprint(button_stats_bp)  # [v5.18.0] 按钮统计
    app.register_blueprint(profile_bp)  # [v5.18.0] 用户画像
    app.register_blueprint(audit_bp)  # [v5.23.0] 审计日志
    app.register_blueprint(attribution_bp)  # [v5.23.0] 转化归因
    app.register_blueprint(scheduler_bp)  # [v5.23.0] 调度监控
    app.register_blueprint(monitor_bp)  # [v5.24.0 阶段3-B] DB 迁移监控
    app.register_blueprint(rbac_approval_bp)  # [阶段3-E] RBAC 权限审批流
    app.register_blueprint(bot_routing_bp)  # [v5.24.0 阶段3-C] 多 Bot 路由管理
    app.register_blueprint(user_lifecycle_bp)  # [v5.26.0] 用户生命周期分布
    app.register_blueprint(funnel_bp)  # [v5.26.0] 转化漏斗可视化
    app.register_blueprint(metrics_bp)  # [Prometheus] 指标监控
    app.register_blueprint(quality_bp)  # [v5.26.0] 内容质量评估

    # [v5.24.0 阶段2-A] RBAC 请求级守卫：所有写操作自动校验权限
    from dashboard.rbac_guard import enforce_rbac
    app.before_request(enforce_rbac)

    # [Trae CN] Swagger API 文档初始化（仅 admin 可访问）
    def _require_admin_for_swagger(f):
        """Swagger UI 访问权限装饰器：仅 admin 角色可查看 API 文档"""
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("logged_in"):
                return jsonify({"ok": False, "msg": "未登录，请先登录 Dashboard"}), 401
            if session.get("role", "viewer") != "admin":
                return jsonify({"ok": False, "msg": "需要管理员权限才能查看 API 文档"}), 403
            return f(*args, **kwargs)
        return wrapper

    if Swagger is not None:
        Swagger(
            app,
            decorators=[_require_admin_for_swagger],
            config={
                "headers": [],
                "specs": [
                    {
                        "endpoint": "apispec",
                        "route": "/apispec.json",
                        "rule_filter": lambda rule: True,
                        "model_filter": lambda tag: True,
                    }
                ],
                "info": {
                    "title": "Mory Assistant API",
                    "version": "6.0",
                    "description": "Mory 小助理 Dashboard API 文档\n\n访问前请先登录 Dashboard。仅 admin 角色可查看本文档。",
                },
                "static_url_path": "/apidocs/static",
                "swagger_ui": True,
                "specs_route": "/apidocs/",
            },
            template={
                "swagger": "2.0",
                "info": {
                    "title": "Mory Assistant API",
                    "version": "6.0",
                    "description": "Mory 小助理 Dashboard API 文档",
                },
                "securityDefinitions": {
                    "session": {
                        "type": "apiKey",
                        "name": "Cookie",
                        "in": "header",
                        "description": "通过 Dashboard 登录接口获取 session cookie",
                    }
                },
            },
        )
    else:
        @app.route("/apidocs/")
        def _apidocs_unavailable():
            return jsonify({"ok": False, "msg": "flasgger 未安装，API 文档暂不可用"}), 503

    # 结构化日志：每个请求自动注入 request_id
    @app.before_request
    def _bind_request_id():
        import uuid
        try:
            from core.structured_logger import bind_context
            bind_context(request_id=uuid.uuid4().hex[:12])
        except Exception:
            pass  # structlog 未初始化时静默跳过

    # [阶段3-F] DB 驱动权限映射：启动时幂等初始化 role_permissions 表
    # 表为空时用 ROLE_PERMISSIONS 字典 bootstrap，保证向后兼容
    try:
        import sqlite3
        from dashboard.audit import ensure_role_permissions_table
        _mory_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _mode = os.environ.get("DASHBOARD_MODE", "main")
        _db_name = "mory_media.db" if _mode == "media" else "mory.db"
        _db_path = os.path.join(_mory_root, _db_name)
        if os.path.exists(_db_path):
            _init_conn = sqlite3.connect(_db_path, timeout=30.0)
            _init_conn.row_factory = sqlite3.Row
            ensure_role_permissions_table(_init_conn)
            _init_conn.close()
    except Exception as _e:
        # 初始化失败不阻断启动，运行时回退到硬编码字典
        print(f"[Dashboard] role_permissions 表初始化失败（非致命）：{_e}")

    # 首页
    @app.route("/")
    def index():
        if not session.get("logged_in"):
            return LOGIN_PAGE
        return HTML_PAGE

    return app


# 兼容直接运行和外部导入
app = create_app()
if app is None:
    sys.exit(1)

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 6616))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
