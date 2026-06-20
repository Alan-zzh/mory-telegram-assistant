# -*- coding: utf-8 -*-
"""[Codex] 后台设置接口必须至少能正常打开，避免面板页静默腐烂。"""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def test_all_settings_get_endpoints_open():
    from dashboard.api.settings_api import settings_bp

    app = Flask(__name__)
    app.secret_key = "settings-smoke"
    app.register_blueprint(settings_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    failed = []
    checked = 0
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        if not rule.rule.startswith("/api/settings/"):
            continue
        if "GET" not in rule.methods or "<" in rule.rule:
            continue
        checked += 1
        response = client.get(rule.rule)
        if response.status_code != 200:
            failed.append((rule.rule, response.status_code))

    assert checked >= 60
    assert failed == []
