#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mory Assistant - 私域可视化面板
v6.0 - 全新设计（深色主题/数据可视化/实时监控/专业级UI）
Build: 2026-04-26
"""
import os
import sys
from flask import Flask, session, redirect, url_for
from dashboard.helpers import login_required
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
