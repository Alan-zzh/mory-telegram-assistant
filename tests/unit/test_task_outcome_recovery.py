# -*- coding: utf-8 -*-
"""任务三态与进程重启恢复回归测试。"""

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from core.db_repos.task_exec_history_repo import TaskExecHistoryRepo
from tasks.analytics.faq_distill_task import FaqDistillTask


class _FaqDb:
    def __init__(self, result=0, error=None):
        self.result = result
        self.error = error
        self.history = []

    def claim_task(self, key):
        return True

    def release_task(self, key):
        self.history.append(("release", key))
        return True

    def record_task_start(self, key):
        self.history.append(("start", key))
        return 7

    def record_task_success(self, task_id, duration_ms):
        self.history.append(("success", task_id))

    def record_task_failure(self, task_id, message, duration_ms):
        self.history.append(("failed", str(message)))

    def record_task_abort(self, task_id, reason):
        self.history.append(("aborted", str(reason)))

    def distill_candidates(self, **_kwargs):
        if self.error:
            raise self.error
        return self.result


def _faq_task(db):
    rm = SimpleNamespace(
        config={"FAQ_TRACKING_ENABLED": True, "FAQ_MIN_FREQUENCY": 3},
        db=db,
        bot=SimpleNamespace(),
    )
    return FaqDistillTask(rm)


def test_faq_empty_candidates_is_expected_abort():
    db = _FaqDb(result=0)

    _faq_task(db).run()

    assert ("aborted", "无新高频问题候选") in db.history
    assert not any(item[0] == "failed" for item in db.history)
    assert ("release", "faq_distill") in db.history


def test_faq_unexpected_failure_reaches_scheduler(monkeypatch):
    db = _FaqDb(error=RuntimeError("distill broken"))
    reports = []
    monkeypatch.setattr(
        "tasks.analytics.faq_distill_task.get_fault_reporter",
        lambda: SimpleNamespace(report=lambda *args: reports.append(args)),
    )

    with pytest.raises(RuntimeError, match="distill broken"):
        _faq_task(db).run()

    assert any(item[0] == "failed" and "distill broken" in item[1] for item in db.history)
    assert reports


def test_startup_recovery_finishes_all_old_running_and_releases_locks(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE task_execution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT NOT NULL,
            exec_date TEXT NOT NULL, start_ts INTEGER NOT NULL, end_ts INTEGER,
            status TEXT NOT NULL, error_msg TEXT, duration_ms INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE task_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT,
            exec_date TEXT, exec_ts REAL
        )
    """)
    now = 2_000_000_000
    rows = [
        ("startup_member_scan_18", "2033-05-18", now - 31 * 60),
        ("startup_member_scan_19", "2033-05-18", now - 18 * 60),
    ]
    conn.executemany(
        "INSERT INTO task_execution_history(task_key,exec_date,start_ts,status) VALUES (?,?,?,'running')",
        rows,
    )
    conn.executemany(
        "INSERT INTO task_log(task_key,exec_date,exec_ts) VALUES (?,?,?)",
        [(key, date, start) for key, date, start in rows],
    )
    conn.commit()
    repo = TaskExecHistoryRepo(SimpleNamespace(conn=conn, lock=threading.RLock()))
    monkeypatch.setattr("core.db_repos.task_exec_history_repo.time.time", lambda: now)

    assert repo.cleanup_zombie_running(timeout_seconds=0) == 2
    results = conn.execute(
        "SELECT status,error_msg,duration_ms FROM task_execution_history ORDER BY id"
    ).fetchall()
    assert results == [
        ("failed", "process_restarted_before_completion", 31 * 60 * 1000),
        ("failed", "process_restarted_before_completion", 18 * 60 * 1000),
    ]
    assert conn.execute("SELECT COUNT(*) FROM task_log").fetchone()[0] == 0


def _zombie_tables():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE task_execution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_key TEXT NOT NULL,
            exec_date TEXT NOT NULL, start_ts INTEGER NOT NULL, end_ts INTEGER,
            status TEXT NOT NULL, error_msg TEXT, duration_ms INTEGER
        )
    """)
    conn.execute("CREATE TABLE task_log (task_key TEXT, exec_date TEXT, exec_ts REAL)")
    conn.execute(
        "INSERT INTO task_execution_history(task_key,exec_date,start_ts,status) "
        "VALUES ('stale','2026-08-01',1,'running')"
    )
    conn.execute("INSERT INTO task_log VALUES ('stale','2026-08-01',1)")
    conn.commit()
    return conn


def test_startup_recovery_execute_failure_rolls_back_and_propagates():
    conn = _zombie_tables()
    conn.execute("""
        CREATE TRIGGER fail_task_log_delete BEFORE DELETE ON task_log
        BEGIN SELECT RAISE(ABORT, 'delete failed'); END
    """)
    repo = TaskExecHistoryRepo(SimpleNamespace(conn=conn, lock=threading.RLock()))

    with pytest.raises(sqlite3.IntegrityError, match="delete failed"):
        repo.cleanup_zombie_running(timeout_seconds=0)

    assert conn.execute("SELECT status FROM task_execution_history").fetchone()[0] == "running"
    assert conn.execute("SELECT COUNT(*) FROM task_log").fetchone()[0] == 1


def test_startup_recovery_commit_failure_rolls_back_and_propagates():
    raw = _zombie_tables()

    class _CommitFailConnection:
        def execute(self, *args, **kwargs):
            return raw.execute(*args, **kwargs)

        def commit(self):
            raise sqlite3.OperationalError("commit failed")

        def rollback(self):
            raw.rollback()

    repo = TaskExecHistoryRepo(SimpleNamespace(
        conn=_CommitFailConnection(), lock=threading.RLock()
    ))

    with pytest.raises(sqlite3.OperationalError, match="commit failed"):
        repo.cleanup_zombie_running(timeout_seconds=0)

    assert raw.execute("SELECT status FROM task_execution_history").fetchone()[0] == "running"
    assert raw.execute("SELECT COUNT(*) FROM task_log").fetchone()[0] == 1


def test_initializer_retries_then_fails_closed(monkeypatch):
    from core.bot_initializer import _recover_zombie_tasks_or_raise

    calls = []
    db = SimpleNamespace(
        cleanup_zombie_running=lambda **_kwargs: (
            calls.append(1),
            (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
        )[1]
    )

    with pytest.raises(RuntimeError, match="拒绝启动调度器") as exc_info:
        _recover_zombie_tasks_or_raise(db, attempts=3, sleep_fn=lambda _seconds: None)

    assert len(calls) == 3
    assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)


@pytest.mark.parametrize(
    ("module_name", "class_name", "task_name"),
    [
        ("tasks.analytics.daily_report_task", "DailyReportTask", "daily_report"),
        ("tasks.analytics.weekly_report_task", "WeeklyReportTask", "weekly_report"),
        ("tasks.analytics.monthly_report_task", "MonthlyReportTask", "monthly_report"),
    ],
)
def test_report_database_failure_retries_and_reaches_scheduler(
    monkeypatch, module_name, class_name, task_name
):
    import importlib

    module = importlib.import_module(module_name)
    task_class = getattr(module, class_name)
    retries = []
    monkeypatch.setattr(module, "retry_task", lambda *args: retries.append(args))

    class _LockedDb:
        def claim_task(self, _key):
            raise sqlite3.OperationalError("database is locked")

    rm = SimpleNamespace(config={}, db=_LockedDb(), bot=SimpleNamespace())

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        task_class(rm).run()

    assert len(retries) == 1
    assert retries[0][2] == task_name


def test_scheduled_broadcast_group_failure_reaches_scheduler(monkeypatch):
    import tasks.maintenance.scheduled_broadcast_task as broadcast_module

    monkeypatch.setattr(
        broadcast_module,
        "execute_scheduled_broadcast",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("database is locked")
        ),
    )
    rm = SimpleNamespace(
        config={"GROUP_ID": -100123},
        db=SimpleNamespace(),
        bot=SimpleNamespace(),
        ai=None,
    )

    with pytest.raises(RuntimeError, match="有 1 个群失败") as exc_info:
        broadcast_module.ScheduledBroadcastTask(rm).run(
            {"broadcast_id": "morning_nudge", "chat_id": -100123}
        )

    assert isinstance(exc_info.value.__cause__, sqlite3.OperationalError)


def test_scheduled_broadcast_enabled_without_group_fails(monkeypatch):
    import tasks.maintenance.scheduled_broadcast_task as broadcast_module

    monkeypatch.setattr(broadcast_module, "get_all_group_ids", lambda _config: [])
    rm = SimpleNamespace(config={}, db=SimpleNamespace(), bot=SimpleNamespace(), ai=None)

    with pytest.raises(ValueError, match="已启用但无管理群"):
        broadcast_module.ScheduledBroadcastTask(rm).run({"broadcast_id": "enabled_job"})


def test_greeting_partial_group_failure_keeps_day_lock_without_bulk_retry(monkeypatch):
    """部分群成功：正常返回保留日锁，禁止整批重试导致成功群双发。"""
    import tasks.broadcast.greeting_task as greeting_module

    class _ClaimedTx:
        def __init__(self, *_args, **_kwargs):
            self.claimed = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, *_args):
            # 部分成功路径不应抛异常，事务走成功确认
            assert exc_type is None
            return False

    retries = []
    monkeypatch.setattr(greeting_module, "TaskTransactionManager", _ClaimedTx)
    monkeypatch.setattr(
        greeting_module,
        "send_greeting",
        lambda _rm, gid, *_args, **_kwargs: gid == -1001,
    )
    monkeypatch.setattr(greeting_module, "retry_task", lambda *args: retries.append(args))
    rm = SimpleNamespace(
        config={"AUTO_GREETING": True, "GROUP_ID": -1001, "MANAGED_GROUPS": [-1002]},
        db=SimpleNamespace(),
        bot=SimpleNamespace(),
        ai=SimpleNamespace(
            ask=lambda *_args, **_kwargs: "早安呀，今天来群里跟大家问声好，照顾好自己，按自己的节奏过就行。"
        ),
    )

    # 不抛异常 = 日锁保留；无整批重试
    greeting_module.GreetingTask(rm).run({"period": "morning"})
    assert retries == []


def test_greeting_unusable_model_output_skips_instead_of_sending_fixed_copy(monkeypatch):
    """模型失败或僵硬输出时宁可跳过，也不能每天重复固定早安。"""
    import tasks.broadcast.greeting_task as greeting_module

    class _ClaimedTx:
        claimed = True

        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    sends = []
    retries = []
    monkeypatch.setattr(greeting_module, "TaskTransactionManager", _ClaimedTx)
    monkeypatch.setattr(greeting_module, "send_greeting", lambda *args, **kwargs: sends.append(args))
    monkeypatch.setattr(greeting_module, "retry_task", lambda *args: retries.append(args))
    rm = SimpleNamespace(
        config={"AUTO_GREETING": True, "GROUP_ID": -1001},
        db=SimpleNamespace(),
        bot=SimpleNamespace(),
        ai=SimpleNamespace(ask=lambda *_args, **_kwargs: ""),
    )

    greeting_module.GreetingTask(rm).run({"period": "morning"})

    assert sends == []
    assert retries == []
