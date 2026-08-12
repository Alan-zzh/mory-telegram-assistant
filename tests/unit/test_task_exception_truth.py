# -*- coding: utf-8 -*-
"""定时任务必须向调度器暴露真实失败的回归测试。"""

import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tasks.interaction.wakeup_task import WakeupTask
from tasks.maintenance.auto_inactive_clean_task import AutoInactiveCleanTask
from tasks.monitoring.heartbeat_task import HeartbeatTask
from tasks.maintenance.startup_member_scan_task import StartupMemberScanTask


class _ResourceManager(SimpleNamespace):
    @contextmanager
    def locked(self, _resource):
        yield


def _locked_error(*_args, **_kwargs):
    raise sqlite3.OperationalError("database is locked")


class _ClaimedTransaction:
    def __init__(self, *_args, **_kwargs):
        self.claimed = True

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class _StartupBot:
    def get_chat_administrators(self, _chat_id):
        return [SimpleNamespace(user=SimpleNamespace(id=999))]

    def get_me(self):
        return SimpleNamespace(id=998)

    def send_message(self, *_args, **_kwargs):
        return SimpleNamespace(message_id=1)


@pytest.mark.parametrize(
    ("task_factory", "patch_target"),
    [
        (
            lambda: AutoInactiveCleanTask(
                _ResourceManager(bot=SimpleNamespace(), config={}, db=SimpleNamespace())
            ),
            "tasks.maintenance.auto_inactive_clean_task.run_auto_inactive_clean",
        ),
        (
            lambda: WakeupTask(
                _ResourceManager(
                    bot=SimpleNamespace(),
                    config={},
                    db=SimpleNamespace(get_all_wake_ups=_locked_error),
                )
            ),
            None,
        ),
    ],
)
def test_sqlite_lock_reaches_task_run(monkeypatch, task_factory, patch_target):
    """SQLite 锁不能被记录后吞掉并让 APScheduler 标记 EXECUTED。"""
    if patch_target:
        monkeypatch.setattr(patch_target, _locked_error)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        task_factory().run()


def test_heartbeat_sqlite_lock_reaches_task_run():
    task = HeartbeatTask(
        _ResourceManager(
            bot=SimpleNamespace(),
            config={},
            db=SimpleNamespace(set_system_state=_locked_error),
        )
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        task.run()


def test_wakeup_empty_set_is_a_normal_success():
    task = WakeupTask(
        _ResourceManager(
            bot=SimpleNamespace(),
            config={},
            db=SimpleNamespace(get_all_wake_ups=lambda: []),
        )
    )

    task.run()


def test_wakeup_per_user_failures_continue_then_aggregate(monkeypatch):
    """逐用户发送失败仍继续后续用户，最终向调度器报告真实失败。"""
    monkeypatch.setattr("tasks.interaction.wakeup_task._generate_wakeup_message", lambda *_args: "早安")
    sent_to = []

    def fail_send(user_id, _message):
        sent_to.append(user_id)
        raise ConnectionError(f"network down: {user_id}")

    task = WakeupTask(
        _ResourceManager(
            bot=SimpleNamespace(send_message=fail_send),
            config={},
            db=SimpleNamespace(get_all_wake_ups=lambda: [(1, "00:00"), (2, "00:00")]),
        )
    )
    monkeypatch.setattr("tasks.interaction.wakeup_task.datetime", SimpleNamespace(now=lambda _tz: SimpleNamespace(strftime=lambda _fmt: "00:00")))

    with pytest.raises(ExceptionGroup) as exc_info:
        task.run()

    assert sent_to == [1, 2]
    assert len(exc_info.value.exceptions) == 2


def test_startup_member_scan_db_lock_is_not_zero_user_success(monkeypatch):
    monkeypatch.setattr(
        "tasks.maintenance.startup_member_scan_task.TaskTransactionManager",
        _ClaimedTransaction,
    )
    task = StartupMemberScanTask(SimpleNamespace(
        config={"GROUP_ID": -1001, "STARTUP_MEMBER_SCAN_ENABLED": True},
        bot=_StartupBot(),
        db=SimpleNamespace(conn=SimpleNamespace(execute=_locked_error)),
    ))

    with pytest.raises(ExceptionGroup) as exc_info:
        task.run()

    assert any("database is locked" in str(exc) for exc in exc_info.value.exceptions)


def test_startup_member_scan_enforcement_failure_reaches_scheduler(monkeypatch):
    monkeypatch.setattr(
        "tasks.maintenance.startup_member_scan_task.TaskTransactionManager",
        _ClaimedTransaction,
    )
    monkeypatch.setattr(
        "modules.ad_profile_signals.detect_profile_ad_signal",
        lambda *_args, **_kwargs: {
            "is_ad": True,
            "score": 3,
            "reason": "资料文字命中广告规则",
            "source": "profile",
        },
    )
    monkeypatch.setattr(
        "modules.ad_enforcement.enforce_ad_user",
        lambda **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    class _Conn:
        def execute(self, query, *_params):
            rows = [(101,)] if query == "SELECT uid FROM users" else []
            return SimpleNamespace(fetchall=lambda: rows)

    class _Bot(_StartupBot):
        def get_chat_member(self, _chat_id, uid, **kwargs):
            user = SimpleNamespace(
                id=uid, first_name="spam", last_name="", username="spam101", is_bot=False
            )
            return SimpleNamespace(status="member", user=user)

        def get_chat(self, _uid, **kwargs):
            return SimpleNamespace(bio="广告")

    task = StartupMemberScanTask(SimpleNamespace(
        config={
            "GROUP_ID": -1001,
            "ADMIN_ID": 1,
            "STARTUP_MEMBER_SCAN_ENABLED": True,
            "STARTUP_MEMBER_SCAN_ENFORCE": True,
        },
        bot=_Bot(),
        db=SimpleNamespace(conn=_Conn()),
    ))

    with pytest.raises(ExceptionGroup) as exc_info:
        task.run()

    assert any("database is locked" in str(exc) for exc in exc_info.value.exceptions)
