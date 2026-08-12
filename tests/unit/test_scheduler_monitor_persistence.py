# -*- coding: utf-8 -*-
"""调度指标跨重启恢复回归测试。"""

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

import core.scheduler_monitor as monitor


class _Db:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.lock = threading.RLock()
        self.conn.execute("""
            CREATE TABLE scheduler_metrics (
                job_id TEXT PRIMARY KEY, last_status TEXT,
                success_count INTEGER, fail_count INTEGER, miss_count INTEGER,
                last_run INTEGER, last_duration INTEGER, last_error TEXT,
                synced_at INTEGER NOT NULL
            )
        """)

    def seed(self, job_id, status="success", success=1, fail=0, miss=0, last_run=None):
        self.conn.execute(
            "INSERT INTO scheduler_metrics VALUES (?,?,?,?,?,?,?,?,?)",
            (job_id, status, success, fail, miss, last_run or int(time.time()), 1, "", int(time.time())),
        )
        self.conn.commit()


@pytest.fixture(autouse=True)
def _reset_monitor_state():
    with monitor._metrics_lock:
        monitor._metrics["jobs"].clear()
        monitor._metrics["total_success"] = 0
        monitor._metrics["total_fail"] = 0
        monitor._metrics["total_miss"] = 0
        monitor._metrics["started_at"] = 0
        monitor._metrics_hydrated = False
    monitor._alerted_jobs = set()
    monitor._alerted_date = monitor.datetime.now(monitor._CST).strftime("%Y-%m-%d")
    yield


def test_persisted_success_prevents_false_restart_alert(monkeypatch):
    db = _Db()
    db.seed("critical_interval", last_run=int(time.time()))
    monkeypatch.setattr(
        monitor,
        "_CRITICAL_JOBS",
        {"critical_interval": {"interval_minutes": 5, "desc": "关键周期任务"}},
    )

    assert monitor.check_critical_jobs_health(config={}, db=db) is True
    assert monitor.get_scheduler_stats()["jobs"]["critical_interval"]["last_status"] == "success"


def test_current_process_error_is_not_overwritten_by_old_success(monkeypatch):
    db = _Db()
    db.seed("critical_interval", last_run=int(time.time()))
    monitor.load_scheduler_metrics(db)
    with monitor._metrics_lock:
        monitor._metrics["jobs"]["critical_interval"].update(
            last_status="error", last_run=int(time.time()), last_error="boom"
        )
    monkeypatch.setattr(
        monitor,
        "_CRITICAL_JOBS",
        {"critical_interval": {"interval_minutes": 5, "desc": "关键周期任务"}},
    )

    assert monitor.check_critical_jobs_health(config={}, db=db) is False
    assert monitor.get_scheduler_stats()["jobs"]["critical_interval"]["last_status"] == "error"


def test_hydrated_counts_continue_monotonically_after_restart():
    from apscheduler.events import EVENT_JOB_EXECUTED

    db = _Db()
    db.seed("job_a", success=10)

    class _Scheduler:
        def add_listener(self, callback, _mask):
            self.callback = callback

    scheduler = _Scheduler()
    monitor.attach_to_scheduler(scheduler, db=db)
    scheduler.callback(SimpleNamespace(job_id="job_a", code=EVENT_JOB_EXECUTED, scheduled_time=None))
    assert monitor.sync_metrics_to_db(db) == 1

    row = db.conn.execute(
        "SELECT success_count, last_status FROM scheduler_metrics WHERE job_id='job_a'"
    ).fetchone()
    assert row == (11, "success")


def test_late_hydration_keeps_current_error_and_merges_persisted_counts():
    from apscheduler.events import EVENT_JOB_ERROR

    db = _Db()
    db.seed("job_a", success=10)

    class _Scheduler:
        def add_listener(self, callback, _mask):
            self.callback = callback

    scheduler = _Scheduler()
    # 模拟 attach 时数据库不可用：监听先接到本进程错误，health 阶段再恢复持久指标。
    monitor.attach_to_scheduler(scheduler, db=None)
    scheduler.callback(
        SimpleNamespace(
            job_id="job_a",
            code=EVENT_JOB_ERROR,
            exception=RuntimeError("current failure"),
        )
    )

    assert monitor.load_scheduler_metrics(db) == 1
    current = monitor.get_scheduler_stats()["jobs"]["job_a"]
    assert current["last_status"] == "error"
    assert current["success_count"] == 10
    assert current["fail_count"] == 1
    assert monitor.sync_metrics_to_db(db) == 1
    row = db.conn.execute(
        "SELECT success_count, fail_count, last_status FROM scheduler_metrics WHERE job_id='job_a'"
    ).fetchone()
    assert row == (10, 1, "error")


def test_current_process_sync_is_not_rehydrated_into_itself():
    from apscheduler.events import EVENT_JOB_EXECUTED

    db = _Db()

    class _Scheduler:
        def add_listener(self, callback, _mask):
            self.callback = callback

    scheduler = _Scheduler()
    monitor.attach_to_scheduler(scheduler, db=db)
    scheduler.callback(SimpleNamespace(job_id="new_job", code=EVENT_JOB_EXECUTED, scheduled_time=None))

    assert monitor.sync_metrics_to_db(db) == 1
    assert monitor.load_scheduler_metrics(db) == 0
    assert monitor.get_scheduler_stats()["jobs"]["new_job"]["success_count"] == 1


def test_empty_database_late_recovery_does_not_double_current_event():
    from apscheduler.events import EVENT_JOB_EXECUTED

    db = _Db()

    class _Scheduler:
        def add_listener(self, callback, _mask):
            self.callback = callback

    scheduler = _Scheduler()
    monitor.attach_to_scheduler(scheduler, db=None)
    scheduler.callback(SimpleNamespace(job_id="new_job", code=EVENT_JOB_EXECUTED, scheduled_time=None))

    assert monitor.sync_metrics_to_db(db) == 1
    assert monitor.load_scheduler_metrics(db) == 0
    assert monitor.get_scheduler_stats()["jobs"]["new_job"]["success_count"] == 1


def test_unavailable_metrics_raise_instead_of_emitting_false_missing_alert(monkeypatch):
    class _BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

    db = SimpleNamespace(conn=_BrokenConn(), lock=threading.RLock())
    monkeypatch.setattr(
        monitor,
        "_CRITICAL_JOBS",
        {"critical_interval": {"interval_minutes": 5, "desc": "关键周期任务"}},
    )

    with pytest.raises(RuntimeError, match="无法判定关键任务健康状态"):
        monitor.check_critical_jobs_health(config={}, db=db)

    assert monitor._alerted_jobs == set()


@pytest.mark.parametrize(
    ("job_id", "config"),
    [
        ("cart_recovery", {"CART_RECOVERY_CONFIG": {"enabled": False}}),
        ("daily_backup", {"DAILY_BACKUP_ENABLED": False}),
    ],
)
def test_explicitly_disabled_critical_job_is_not_monitored(job_id, config):
    """任务自己不注册时，关键任务监控也必须尊重同一开关。"""
    assert monitor._is_job_disabled_by_config(job_id, config) is True


@pytest.mark.parametrize(
    ("job_id", "config"),
    [
        ("cart_recovery", {"CART_RECOVERY_CONFIG": {"enabled": True}}),
        ("daily_backup", {"DAILY_BACKUP_ENABLED": True}),
    ],
)
def test_enabled_critical_job_remains_monitored(job_id, config):
    assert monitor._is_job_disabled_by_config(job_id, config) is False
