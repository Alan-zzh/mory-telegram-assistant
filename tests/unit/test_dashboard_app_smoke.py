# -*- coding: utf-8 -*-
"""Dashboard 应用级 smoke test，覆盖蓝图注册与关键只读端点。"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _build_app():
    """构建 Dashboard 测试 app，自动保存/恢复环境变量，避免污染其它测试。"""
    _saved = {
        "TG_TOKEN": os.environ.get("TG_TOKEN"),
        "DASHSCOPE_KEY": os.environ.get("DASHSCOPE_KEY"),
        "DASHBOARD_SECRET": os.environ.get("DASHBOARD_SECRET"),
        "DASHBOARD_PASSWORD": os.environ.get("DASHBOARD_PASSWORD"),
    }
    # 【v5.38.9 修复】setdefault 不会覆盖已存在的短值/空值，导致测试隔离失败；
    # 改为强制赋值，确保 DASHBOARD_SECRET 至少 16 位。
    os.environ["TG_TOKEN"] = "123456:test-token"
    os.environ["DASHSCOPE_KEY"] = "test-dashscope-key"
    os.environ["DASHBOARD_SECRET"] = "test-dashboard-secret-1234567890"
    os.environ["DASHBOARD_PASSWORD"] = "password123"
    try:
        from dashboard.app import create_app

        app = create_app()
        assert app is not None
        app.config["TESTING"] = True
        return app
    finally:
        # 恢复原值，避免环境变量污染后续测试
        for k, v in _saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


def test_dashboard_app_creates_with_expected_routes():
    app = _build_app()
    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert len(rules) >= 150
    assert "/apidocs/" in rules
    assert "/api/v1/metrics" in rules
    assert "/api/analytics/funnel" in rules
    assert "/api/analytics/funnel/trend" in rules
    assert "/api/user-lifecycle/distribution" in rules
    assert "/api/quality/scores" in rules


def test_metrics_endpoint_requires_login_and_allows_admin():
    app = _build_app()
    client = app.test_client()

    unauth = client.get("/api/v1/metrics")
    assert unauth.status_code == 401

    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    auth = client.get("/api/v1/metrics")
    # 【v5.38.9 修复】prometheus-client 是可选依赖；未安装时端点返回 501，
    # 这是合法行为，不应让测试失败。安装时才断言 200 + 指标内容。
    try:
        import prometheus_client  # noqa: F401
        has_prom = True
    except ImportError:
        has_prom = False

    if has_prom:
        assert auth.status_code == 200
        assert b"python_info" in auth.data or b"mory_" in auth.data
    else:
        # 未安装 prometheus-client 时返回 501 NOT IMPLEMENTED
        assert auth.status_code == 501


def test_scheduler_api_does_not_present_scheduler_metrics_as_registry(monkeypatch, tmp_path):
    db_path = tmp_path / "mory.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE scheduler_metrics (
            job_id TEXT PRIMARY KEY,
            last_status TEXT,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            miss_count INTEGER DEFAULT 0,
            last_run INTEGER,
            last_status_at INTEGER,
            last_duration INTEGER,
            last_error TEXT,
            synced_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO scheduler_metrics VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "cart_recovery", "success", 2, 1, 0, 1782930000,
            1782930000, 0, "historical timeout", 1782930300,
        ),
    )
    conn.execute(
        "INSERT INTO scheduler_metrics VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "heartbeat", "error", 3, 1, 0, 1782930200,
            1782930250, 0, "current failure", 1782930300,
        ),
    )
    conn.commit()

    import dashboard.api.scheduler_api as scheduler_api
    monkeypatch.setattr(scheduler_api, "get_db", lambda: conn)

    app = _build_app()
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    jobs = client.get("/api/scheduler/jobs")
    assert jobs.status_code == 200
    jobs_json = jobs.get_json()
    assert jobs_json["source"] == "unavailable"
    assert jobs_json["registry_available"] is False
    assert jobs_json["count"] == 0
    assert jobs_json["historical_metrics_count"] == 2

    stats = client.get("/api/scheduler/stats")
    assert stats.status_code == 200
    stats_json = stats.get_json()
    assert stats_json["data"]["source"] == "scheduler_metrics_history"
    assert stats_json["data"]["registry_available"] is False
    assert stats_json["data"]["job_count"] is None
    assert stats_json["data"]["historical_job_count"] == 2

    recovered = stats_json["data"]["jobs"]["cart_recovery"]
    assert recovered["last_status"] == "success"
    assert recovered["last_status_at"] == 1782930000
    assert recovered["last_error"] == ""
    assert recovered["last_failure_error"] == "historical timeout"
    assert recovered["error_scope"] == "historical"

    failing = stats_json["data"]["jobs"]["heartbeat"]
    assert failing["last_status"] == "error"
    assert failing["last_status_at"] == 1782930250
    assert failing["last_error"] == "current failure"
    assert failing["last_failure_error"] == "current failure"
    assert failing["error_scope"] == "current"


def test_scheduler_api_normalizes_in_memory_error_scopes(monkeypatch):
    import core.scheduler_monitor as scheduler_monitor

    monkeypatch.setattr(scheduler_monitor, "get_scheduler_stats", lambda: {
        "job_count": 3,
        "jobs": {
            "heartbeat": {
                "last_status": "success",
                "last_error": "old database error",
                "success_count": 10,
                "fail_count": 1,
                "last_status_at": 1782930400,
            },
            "ttl_cleanup": {
                "last_status": "error",
                "last_error": "current database error",
                "success_count": 9,
                "fail_count": 2,
                "last_status_at": 1782930500,
            },
            "daily_report": {
                "last_status": "missed",
                "last_error": "older task failure",
                "success_count": 8,
                "fail_count": 1,
                "miss_count": 1,
                "last_status_at": 1782930600,
            },
        },
    })

    app = _build_app()
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    response = client.get("/api/scheduler/stats")
    assert response.status_code == 200
    info = response.get_json()["data"]["jobs"]["heartbeat"]
    assert info["last_error"] == ""
    assert info["last_status_at"] == 1782930400
    assert info["last_failure_error"] == "old database error"
    assert info["error_scope"] == "historical"

    failing = response.get_json()["data"]["jobs"]["ttl_cleanup"]
    assert failing["last_status"] == "error"
    assert failing["last_error"] == "current database error"
    assert failing["error_scope"] == "current"

    missed = response.get_json()["data"]["jobs"]["daily_report"]
    assert missed["last_status"] == "missed"
    assert missed["miss_count"] == 1
    assert missed["last_error"] == ""
    assert missed["last_failure_error"] == "older task failure"
    assert missed["error_scope"] == "historical"
