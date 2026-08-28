# -*- coding: utf-8 -*-
"""Dashboard API 回归：异常降级路径必须可执行，不能因日志变量未定义再次失败。"""

from flask import Flask

import dashboard.api.features_api as features_api
import dashboard.api.models_api as models_api
import dashboard.api.stats_api as stats_api
from dashboard.audit import get_permissions_from_db, get_user_role_from_db


def _app(*blueprints) -> Flask:
    app = Flask(__name__)
    app.secret_key = "dashboard-api-regression-tests"
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app


def _login(client, role="viewer"):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = role


def test_broadcast_put_accepts_extra_fields(monkeypatch):
    """PUT 更新播报时应使用共享字段白名单，不得引用 POST 局部变量。"""
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {"id": "morning", "hour": 8, "minute": 0, "content": "旧内容", "enabled": True}
        ]
    }
    monkeypatch.setattr(features_api, "read_config", lambda: cfg)
    monkeypatch.setattr(features_api, "write_config", lambda value: True)

    app = _app(features_api.features_bp)
    with app.test_client() as client:
        _login(client, role="admin")
        response = client.put(
            "/api/settings/broadcasts/morning",
            json={"content": "新内容", "title": "早安", "media": {"kind": "photo"}},
        )

    assert response.status_code == 200
    assert cfg["SCHEDULED_BROADCASTS"][0]["title"] == "早安"
    assert cfg["SCHEDULED_BROADCASTS"][0]["media"] == {"kind": "photo"}


def test_models_status_invalid_expire_is_reported_without_logger_name_error(monkeypatch):
    """模型日期解析失败时仍返回模型状态，日志异常不能把请求升级成 500。"""
    monkeypatch.setattr(
        models_api,
        "read_config",
        lambda: {"MODEL_POOLS": {"llm_light": [{"name": "bad-date", "expire": "not-a-date"}]}},
    )

    app = _app(models_api.models_bp)
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/models/status")

    assert response.status_code == 200
    model = response.get_json()["data"]["llm_light"][0]
    assert model["name"] == "bad-date"
    assert model["days_left"] == 9999


def test_tasks_status_database_error_is_logged_without_logger_name_error(monkeypatch):
    """真实任务历史不可读时必须 fail closed，不能返回九项假状态。"""
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(models_api, "get_db", lambda: BrokenConnection())

    app = _app(models_api.models_bp)
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/tasks/status")

    assert response.status_code == 503
    assert response.get_json()["msg"] == "task_history_unavailable"


def test_user_analytics_database_errors_are_logged_without_logger_name_error(monkeypatch):
    """用户分析统计的趋势/排行异常路径不能因 logger 未定义而二次失败。"""
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(stats_api, "get_db", lambda: BrokenConnection())
    app = _app(stats_api.stats_bp)
    with app.test_client() as client:
        _login(client)
        response = client.get("/api/user/analytics")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["dau_trend"] == []
    assert data["top_users"] == []


def test_audit_role_lookup_error_falls_back_to_viewer_without_logging_name_error():
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("role table unavailable")

    assert get_user_role_from_db(BrokenConnection(), 123) == "viewer"


def test_audit_permission_lookup_error_returns_unavailable_without_logging_name_error():
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("permission table unavailable")

    assert get_permissions_from_db(BrokenConnection(), "admin") is None
