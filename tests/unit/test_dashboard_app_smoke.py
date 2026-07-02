# -*- coding: utf-8 -*-
"""Dashboard 应用级 smoke test，覆盖蓝图注册与关键只读端点。"""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _build_app():
    os.environ.setdefault("TG_TOKEN", "123456:test-token")
    os.environ.setdefault("DASHSCOPE_KEY", "test-dashscope-key")
    os.environ.setdefault("DASHBOARD_SECRET", "test-dashboard-secret")
    os.environ.setdefault("DASHBOARD_PASSWORD", "password123")
    from dashboard.app import create_app

    app = create_app()
    assert app is not None
    app.config["TESTING"] = True
    return app


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
    assert auth.status_code == 200
    assert b"python_info" in auth.data or b"mory_" in auth.data


def test_scheduler_api_falls_back_to_scheduler_metrics(monkeypatch, tmp_path):
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
            last_duration INTEGER,
            last_error TEXT,
            synced_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO scheduler_metrics VALUES (?,?,?,?,?,?,?,?,?)",
        ("cart_recovery", "success", 2, 0, 0, 1782930000, 0, "", 1782930300),
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
    assert jobs_json["source"] == "scheduler_metrics"
    assert jobs_json["count"] == 1

    stats = client.get("/api/scheduler/stats")
    assert stats.status_code == 200
    stats_json = stats.get_json()
    assert stats_json["data"]["source"] == "scheduler_metrics"
    assert stats_json["data"]["job_count"] == 1
