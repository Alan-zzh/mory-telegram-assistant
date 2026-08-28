"""启动两相化与 A/B 数据链的回归测试。"""

import inspect
import sqlite3
from types import SimpleNamespace

from flask import Flask


def test_main_runs_fatal_preflight_before_background_activation():
    """fatal preflight 失败时，main 不得先启动任何后台副作用。"""
    import main

    source = inspect.getsource(main.main)
    construct = source.index("initialize_bot(activate_background=False)")
    preflight = source.index("preflight_check(CONFIG")
    activate = source.index("activate_bot(ctx)")

    assert construct < preflight < activate


def test_activate_bot_starts_deferred_work_once(monkeypatch):
    """构造阶段可安全返回；激活阶段才启动 scheduler 和维护线程。"""
    from core import bot_initializer
    from tasks import task_scheduler

    events = []

    class _Thread:
        def __init__(self, *, target, args=(), name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def start(self):
            events.append(f"thread:{self.name}")

    monkeypatch.setattr(
        task_scheduler,
        "start_background",
        lambda *args, **kwargs: (
            events.append("scheduler") or kwargs["resource_manager"]
        ),
    )
    monkeypatch.setattr(bot_initializer.threading, "Thread", _Thread)
    ad_detector = SimpleNamespace(
        process_pending_bans=lambda bot, cfg: events.append("pending_bans")
    )
    ctx = SimpleNamespace(
        bot=object(),
        config={"RETROACTIVE_SCAN_ENABLED": False},
        db=SimpleNamespace(),
        ai=object(),
        ad_detector=ad_detector,
        save_config=lambda: None,
        resource_manager=object(),
    )

    bot_initializer.activate_bot(ctx)
    bot_initializer.activate_bot(ctx)

    assert events == ["scheduler", "pending_bans", "thread:startup_cleanup"]
    assert ctx._background_activated is True


def test_ab_flush_keeps_buffer_until_commit_succeeds(monkeypatch):
    """无 DB 或事务失败时指标必须留在内存缓冲，不能先删再写。"""
    from core import ab_test_router as router

    monkeypatch.setattr(router, "_metrics_buffer", [])
    monkeypatch.setattr(router, "_last_flush_ts", 0.0)
    monkeypatch.setattr(router, "_bound_db", None)

    router.record_ab_metric(10, "A", "model-a", 12.5)
    assert len(router._metrics_buffer) == 1

    class _BrokenConnection:
        def executemany(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("write failed")

        def rollback(self):
            return None

    assert router.flush_metrics(_BrokenConnection()) is False
    assert len(router._metrics_buffer) == 1

    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE ab_test_metrics (
            uid INTEGER, group_name TEXT, model TEXT, latency_ms REAL,
            cost REAL, converted INTEGER, ts INTEGER
        )
        """
    )
    try:
        router.bind_db(connection)
        assert router.flush_metrics() is True
        row = connection.execute(
            "SELECT COUNT(*) FROM ab_test_metrics"
        ).fetchone()
        assert row[0] == 1
        assert router._metrics_buffer == []
    finally:
        router.bind_db(None)
        connection.close()


def test_dashboard_ab_button_and_profile_apis_use_request_database(
    monkeypatch,
):
    """Dashboard 不依赖不存在的 main/dashboard.app 全局变量。"""
    from dashboard.api import ab_test_api

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE ab_test_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, group_name TEXT,
            format_version TEXT, sent_count INTEGER,
            conversion_count INTEGER DEFAULT 0, ts INTEGER
        );
        CREATE TABLE button_click_stats (
            button_id TEXT, style TEXT, impressions INTEGER, clicks INTEGER,
            last_updated TEXT, PRIMARY KEY (button_id, style)
        );
        CREATE TABLE ab_test_metrics (
            uid INTEGER, group_name TEXT, model TEXT, latency_ms REAL,
            cost REAL, converted INTEGER, ts INTEGER
        );
        CREATE TABLE user_profiles (
            user_id INTEGER PRIMARY KEY, tags TEXT, level INTEGER, interests TEXT,
            last_interaction TEXT, conversation_rounds INTEGER,
            activity_score REAL, flirt_affinity REAL, spend_tendency REAL,
            resistance_idx REAL, peak_hours TEXT, persona_tags TEXT,
            memory_summary TEXT, updated_at TEXT
        );
        INSERT INTO ab_test_stats
            (group_name, format_version, sent_count, conversion_count, ts)
        VALUES ('default', 'html', 3, 1, 1);
        INSERT INTO button_click_stats VALUES ('buy', 'primary', 10, 2, NULL);
        INSERT INTO ab_test_metrics VALUES
            (10, 'A', 'model-a', 100.0, 0.1, 1, 1),
            (11, 'B', 'model-b', 90.0, 0.2, 0, 1);
        INSERT INTO user_profiles VALUES
            (7, '["vip"]', 2, '["tarot"]', '2026-08-24', 3,
             0.2, 0.1, 0.4, 0.5, '[22]', '["night_owl"]', '', NULL);
        """
    )
    monkeypatch.setattr(ab_test_api, "get_db", lambda: connection)
    monkeypatch.setattr(
        ab_test_api,
        "read_config",
        lambda: {"USER_PROFILE_ENABLED": False},
    )

    app = Flask(__name__)
    app.secret_key = "test-secret-at-least-16"
    app.register_blueprint(ab_test_api.ab_test_bp)
    app.register_blueprint(ab_test_api.button_stats_bp)
    app.register_blueprint(ab_test_api.profile_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    ab_stats = client.get("/api/ab-test/stats").get_json()["data"]
    assert ab_stats["html_sent"] == 3
    assert client.post(
        "/api/ab-test/record-sent",
        json={"group_name": "default", "format_version": "html", "count": 2},
    ).status_code == 200
    ab_stats = client.get("/api/ab-test/stats").get_json()["data"]
    assert ab_stats["html_sent"] == 5
    button_stats = client.get("/api/button-stats/stats").get_json()["data"]
    assert button_stats["stats"][0]["button_id"] == "buy"
    profile = client.get("/api/profile/7").get_json()["data"]
    assert profile["tags"] == ["vip"]
    profile_list = client.get("/api/profile/list?tag=vip").get_json()["data"]
    assert profile_list["count"] == 1

    from core.ab_test_router import get_significance_report

    report = get_significance_report(days=90_000, db=connection)
    assert set(report["groups"]) == {"A", "B"}

    source = inspect.getsource(ab_test_api)
    assert "from main import" not in source
    assert "from dashboard.app import" not in source
    assert "from core.config import" not in source
    connection.close()
