# -*- coding: utf-8 -*-
"""Dashboard 任务健康接口不得把锁表或缺失数据包装成 100%。"""

import sqlite3
import time

import pytest
from flask import Flask

from dashboard.api import health_api


def _history_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE task_execution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            exec_date TEXT NOT NULL,
            start_ts INTEGER NOT NULL,
            end_ts INTEGER,
            status TEXT NOT NULL,
            error_msg TEXT,
            duration_ms INTEGER
        )
        """
    )
    return conn


def test_root_health_fails_closed_without_bot_heartbeat(monkeypatch):
    from dashboard.api import health_api

    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(health_api, "get_db", lambda: conn)
    app = Flask(__name__)
    with app.app_context():
        response = health_api.api_health_check()
    assert response[1] == 503
    assert response[0].get_json()["msg"] == "bot heartbeat unavailable"


def test_root_health_requires_fresh_bot_heartbeat(monkeypatch):
    from dashboard.api import health_api

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE system_states (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO system_states(key,value) VALUES ('last_heartbeat', ?)",
        (str(int(time.time())),),
    )
    monkeypatch.setattr(health_api, "get_db", lambda: conn)
    app = Flask(__name__)
    with app.app_context():
        response = health_api.api_health_check()
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_task_history_stats_preserve_failures_and_aborts():
    conn = _history_conn()
    now = int(time.time())
    rows = [
        ("mystic", "success", None),
        ("mystic", "failed", "provider timeout"),
        ("faq_distill", "aborted", "no candidates"),
        ("daily_report", "running", None),
    ]
    conn.executemany(
        "INSERT INTO task_execution_history "
        "(task_key,exec_date,start_ts,status,error_msg) VALUES (?,date('now'),?,?,?)",
        [(task, now, status, error) for task, status, error in rows],
    )

    stats = health_api._get_task_history_stats(conn, now - 60)

    assert stats == {
        "total": 4,
        "success": 1,
        "failed": 1,
        "aborted": 1,
        "running": 1,
        "rate": pytest.approx(33.33),
    }


def test_task_history_stats_empty_is_unknown_not_success():
    stats = health_api._get_task_history_stats(_history_conn(), int(time.time()) - 60)

    assert stats["total"] == 0
    assert stats["rate"] is None


def test_recent_task_outcomes_include_real_failed_and_aborted_rows():
    conn = _history_conn()
    now = int(time.time())
    conn.executemany(
        "INSERT INTO task_execution_history "
        "(task_key,exec_date,start_ts,status,error_msg) VALUES (?,date('now'),?,?,?)",
        [
            ("mystic", now, "failed", "provider timeout"),
            ("faq_distill", now - 1, "aborted", "no candidates"),
            ("mystic", now - 2, "success", None),
        ],
    )

    result = health_api._get_recent_task_outcomes(conn, {"failed", "aborted"}, limit=10)

    assert result["total"] == 2
    assert result["by_task"] == {"faq_distill": 1, "mystic": 1}
    assert [item["status"] for item in result["recent"]] == ["failed", "aborted"]
    assert all(len(item["error_msg"]) <= 160 for item in result["recent"])


def test_health_score_is_unknown_when_ai_was_not_probed(monkeypatch):
    conn = _history_conn()
    now = int(time.time())
    conn.execute(
        "INSERT INTO task_execution_history "
        "(task_key,exec_date,start_ts,status) VALUES ('mystic',date('now'),?,'success')",
        (now,),
    )
    monkeypatch.setattr(health_api, "get_db", lambda: conn)
    monkeypatch.setattr(health_api, "read_config", lambda: {})
    monkeypatch.setattr(health_api.shutil, "disk_usage", lambda _path: (100, 50, 50))
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(health_api.health_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True

    response = client.get("/api/health/score")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["score"] is None
    assert payload["partial_score"] is not None
    assert payload["level"] == "⚪ 未知"
    assert payload["dimensions"]["ai"]["score"] is None
