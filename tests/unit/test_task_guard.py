# -*- coding: utf-8 -*-
"""TaskGuard 单元测试 - 覆盖并发告警/去重/抢占失败告警"""

import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tasks.support.task_guard import TaskGuard


@pytest.fixture
def guard():
    """每个测试重置单例状态，避免交叉污染"""
    g = TaskGuard()
    g._call_history.clear()
    g._claim_fail_count.clear()
    g._alerted.clear()
    return g


# ─────────────────── 1. 5 分钟内 2 次调用触发告警 ───────────────────

def test_record_call_triggers_alert_on_two_calls(guard):
    """同一任务 5 分钟内被调用 ≥2 次 → 触发告警"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_call("task_a")  # 第 1 次：count=1，不告警
    guard.record_call("task_a")  # 第 2 次：count=2，触发告警

    alert_mock.assert_called_once()
    msg = alert_mock.call_args[0][0]
    assert "task_a" in msg
    assert "2" in msg  # 被调用次数


# ─────────────────── 2. 同一分钟内多次调用只告警一次（去重） ───────────────────

def test_record_call_dedup_within_same_minute(guard):
    """同一分钟内多次调用 → 仅告警一次（alert_key 按分钟去重）"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_call("task_b")  # count=1，不告警
    guard.record_call("task_b")  # count=2，告警（alert_key 加入 _alerted）
    guard.record_call("task_b")  # count=3，alert_key 已存在 → 不重复告警

    alert_mock.assert_called_once()


# ─────────────────── 3. 连续 3 次抢占失败触发告警 ───────────────────

def test_record_claim_fail_triggers_alert_on_three(guard):
    """连续 3 次抢占失败 → 触发告警 + 计数重置"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_claim_fail("task_c", "lock_timeout")  # count=1
    guard.record_claim_fail("task_c", "lock_timeout")  # count=2
    guard.record_claim_fail("task_c", "lock_timeout")  # count=3 → 告警 + 重置

    alert_mock.assert_called_once()
    msg = alert_mock.call_args[0][0]
    assert "task_c" in msg
    assert "3" in msg  # 连续失败次数
    # 告警后计数重置为 0
    assert guard._claim_fail_count.get("task_c", 0) == 0


def test_record_claim_fail_dedup_same_hour(guard):
    """同一小时内再次达到阈值 → alert_key 去重，不重复告警"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    # 前 3 次触发第一次告警
    for _ in range(3):
        guard.record_claim_fail("task_d", "fail")

    # 再 3 次（同一小时内，alert_key 相同）→ 不重复告警
    for _ in range(3):
        guard.record_claim_fail("task_d", "fail")

    alert_mock.assert_called_once()


# ─────────────────── 4. record_claim_ok 重置失败计数 ───────────────────

def test_record_claim_ok_resets_count(guard):
    """record_claim_ok 重置计数 → 后续 2 次失败不触发告警（需 3 次）"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_claim_fail("task_e", "fail")  # count=1
    guard.record_claim_fail("task_e", "fail")  # count=2
    guard.record_claim_ok("task_e")            # 重置 → count=0
    guard.record_claim_fail("task_e", "fail")  # count=1

    alert_mock.assert_not_called()


# ───────────────── 5. task_log 只审计防重锁记录 ─────────────────

def _task_log_db(rows):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("CREATE TABLE task_log (task_key TEXT, exec_date TEXT)")
    conn.executemany("INSERT INTO task_log VALUES (?, ?)", rows)
    conn.commit()
    return SimpleNamespace(conn=conn)


def test_audit_task_log_does_not_treat_discovered_tasks_as_due(monkeypatch, guard):
    """任务类被发现不等于今日到点应执行。

    task_log 的动态键也可能带日期后缀，不能与静态 task_id 直接做集合差。
    缺失执行由调度器事件/关键任务截止时间链负责，不属于数据库锁异常。
    """
    from datetime import datetime, timedelta, timezone
    from tasks import task_scheduler

    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    db = _task_log_db([(f"health_check_{today}", today)])
    fake_tasks = {
        name: SimpleNamespace(task_id=name, enabled=True)
        for name in ("health_check", "weekly_report", "startup_member_scan")
    }
    monkeypatch.setattr(
        task_scheduler,
        "_scheduler_instance",
        SimpleNamespace(tasks=fake_tasks),
    )

    assert guard.audit_task_log(db) == []


def test_audit_task_log_reports_duplicate_lock_records(guard):
    """task_log 同日同键重复才是该审计器需要返回的异常。"""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    db = _task_log_db([("duplicate_task", today), ("duplicate_task", today)])

    assert guard.audit_task_log(db) == [
        "• duplicate_task：今日2条记录（正常应1条）"
    ]


def test_audit_task_log_database_error_is_not_reported_as_healthy(guard):
    class _BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

    db = SimpleNamespace(conn=_BrokenConn())

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        guard.audit_task_log(db)


def test_is_task_executed_today_database_error_propagates():
    from core.db_repos.config_repo import ConfigRepo

    class _BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

    repo = ConfigRepo(SimpleNamespace(conn=_BrokenConn(), lock=nullcontext()))

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        repo.is_task_executed_today("health_check")


def test_health_check_labels_task_log_anomaly_without_claiming_sqlite_lock(monkeypatch):
    """task_log 重复是防重记录异常，不得冒充 SQLite database is locked。"""
    import tasks.support.critical_tasks as critical_tasks
    import tasks.monitoring.health_check_task as health_module
    from tasks.base_task import TaskContext

    monkeypatch.setattr(critical_tasks, "_build_critical_tasks", lambda config, today: [])
    monkeypatch.setattr(
        health_module,
        "get_task_guard",
        lambda: SimpleNamespace(audit_task_log=lambda db: ["• duplicate_task：重复记录"]),
    )
    bot = MagicMock()
    rm = SimpleNamespace(
        config={"ADMIN_ID": 123},
        db=object(),
        bot=bot,
        locked=lambda name: nullcontext(),
    )

    health_module.HealthCheckTask(rm).execute(TaskContext(rm=rm))

    message = bot.send_message.call_args.args[1]
    assert "任务防重记录异常" in message
    assert "数据库锁异常" not in message


def test_health_check_database_error_sends_no_false_missing_alert(monkeypatch):
    import tasks.support.critical_tasks as critical_tasks
    import tasks.monitoring.health_check_task as health_module
    from tasks.base_task import TaskContext

    monkeypatch.setattr(
        critical_tasks,
        "_build_critical_tasks",
        lambda config, today: [{
            "desc": "关键任务",
            "deadline_hour": 0,
            "deadline_minute": 0,
            "keys": ["critical_job"],
        }],
    )
    monkeypatch.setattr(
        critical_tasks,
        "_missing_task_keys_today",
        lambda db, keys: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )
    bot = MagicMock()
    rm = SimpleNamespace(
        config={"ADMIN_ID": 123},
        db=object(),
        bot=bot,
        locked=lambda name: nullcontext(),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        health_module.HealthCheckTask(rm).execute(TaskContext(rm=rm))

    bot.send_message.assert_not_called()


@pytest.mark.parametrize(
    ("frequency", "date_field", "date_value", "today"),
    [
        ("weekly", "day_of_week", 0, "2026-08-01"),  # 周六不检查周一播报
        ("monthly", "day_of_month", 1, "2026-08-02"),
    ],
)
def test_health_check_skips_dynamic_broadcasts_not_scheduled_today(
    frequency, date_field, date_value, today
):
    from tasks.support.critical_tasks import _build_critical_tasks

    broadcast = {
        "id": "not_today",
        "enabled": True,
        "time": "10:00",
        "frequency": frequency,
        date_field: date_value,
    }
    config = {
        "AUTO_GREETING": False,
        "MYSTIC_BROADCAST_CONFIG": {"enabled": False},
        "SCHEDULED_BROADCASTS": [broadcast],
    }

    tasks = _build_critical_tasks(config, today)

    assert all(task["desc"] != "定点播报:not_today" for task in tasks)


def test_health_check_fails_closed_when_due_broadcast_has_no_group():
    from tasks.support.critical_tasks import _build_critical_tasks

    config = {
        "AUTO_GREETING": False,
        "MYSTIC_BROADCAST_CONFIG": {"enabled": False},
        "SCHEDULED_BROADCASTS": [{
            "id": "due_without_target",
            "enabled": True,
            "time": "10:00",
            "frequency": "daily",
        }],
    }

    with pytest.raises(ValueError, match="未配置任何管理群"):
        _build_critical_tasks(config, "2026-08-02")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("day_of_week", "noday", "day_of_week"),
        ("day_of_week", 7, "day_of_week"),
        ("day_of_month", 0, "day_of_month"),
        ("day_of_month", 32, "day_of_month"),
    ],
)
def test_invalid_dynamic_broadcast_calendar_fails_closed(field, value, message):
    from tasks.support.critical_tasks import _is_broadcast_scheduled_for_date

    with pytest.raises(ValueError, match=message):
        _is_broadcast_scheduled_for_date({field: value}, "2026-08-02")
