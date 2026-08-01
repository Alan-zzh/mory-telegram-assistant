# -*- coding: utf-8 -*-
"""启动维护不能阻塞 heartbeat、scheduler 或 Telegram polling。"""

import threading
import time
from types import SimpleNamespace

import pytest


def test_persist_startup_heartbeat_writes_cross_process_state():
    from modules.auto_tasks import _persist_startup_heartbeat

    writes = []
    rm = SimpleNamespace(db=SimpleNamespace(set_system_state=lambda key, value: writes.append((key, value))))
    before = int(time.time())

    _persist_startup_heartbeat(rm)

    assert writes[0][0] == "last_heartbeat"
    assert before <= int(writes[0][1]) <= int(time.time())


def test_startup_member_scan_runs_in_background(monkeypatch):
    from modules import auto_tasks
    from tasks.maintenance.startup_history_cleanup_task import StartupHistoryCleanupTask
    from tasks.maintenance.startup_member_scan_task import StartupMemberScanTask

    started = threading.Event()
    release = threading.Event()
    history_ran = threading.Event()

    def blocking_scan(self):
        started.set()
        assert release.wait(timeout=3)

    monkeypatch.setattr(StartupMemberScanTask, "run", blocking_scan)
    monkeypatch.setattr(StartupHistoryCleanupTask, "run", lambda self: history_ran.set())
    monkeypatch.setattr(auto_tasks, "_startup_maintenance_thread", None)

    begin = time.monotonic()
    thread = auto_tasks._start_startup_maintenance(SimpleNamespace())
    elapsed = time.monotonic() - begin

    assert elapsed < 0.5
    assert started.wait(timeout=1)
    assert thread.is_alive()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert history_ran.is_set()


def test_scheduler_starts_before_startup_maintenance(monkeypatch):
    from modules import auto_tasks
    from tasks import task_scheduler
    from tasks.monitoring.watchdog_task import WatchdogTask
    from modules.triggers.cold_group import ColdGroupTrigger
    from modules.triggers.night_hint import NightHintTrigger
    import core.scheduler_monitor as scheduler_monitor

    events = []

    class FakeBackgroundScheduler:
        running = False

    class FakeTaskScheduler:
        def __init__(self):
            self.scheduler = FakeBackgroundScheduler()

        def start(self):
            events.append("scheduler_started")
            self.scheduler.running = True

    fake = FakeTaskScheduler()
    monkeypatch.setattr(task_scheduler, "create_scheduler", lambda rm: fake)
    monkeypatch.setattr(WatchdogTask, "start", lambda self, timeout_sec: events.append("watchdog_started"))
    monkeypatch.setattr(ColdGroupTrigger, "register", lambda self, scheduler, rm: None)
    monkeypatch.setattr(NightHintTrigger, "register", lambda self, scheduler, rm: None)
    monkeypatch.setattr(scheduler_monitor, "attach_to_scheduler", lambda scheduler, db=None: None)
    monkeypatch.setattr(auto_tasks, "_persist_startup_heartbeat", lambda rm: events.append("heartbeat_persisted"))
    monkeypatch.setattr(auto_tasks, "_start_startup_maintenance", lambda rm: events.append("maintenance_started"))

    auto_tasks._start_with_task_scheduler(SimpleNamespace(db=SimpleNamespace()))

    assert events.index("scheduler_started") < events.index("heartbeat_persisted")
    assert events.index("heartbeat_persisted") < events.index("watchdog_started")
    assert events.index("watchdog_started") < events.index("maintenance_started")


def test_scheduler_monitor_attach_failure_prevents_start(monkeypatch):
    from modules import auto_tasks
    from tasks import task_scheduler
    from modules.triggers.cold_group import ColdGroupTrigger
    from modules.triggers.night_hint import NightHintTrigger
    import core.scheduler_monitor as scheduler_monitor

    class _Background:
        running = False

    class _Scheduler:
        def __init__(self):
            self.scheduler = _Background()
            self.started = False

        def start(self):
            self.started = True

    fake = _Scheduler()
    monkeypatch.setattr(task_scheduler, "create_scheduler", lambda _rm: fake)
    monkeypatch.setattr(ColdGroupTrigger, "register", lambda self, scheduler, rm: None)
    monkeypatch.setattr(NightHintTrigger, "register", lambda self, scheduler, rm: None)
    monkeypatch.setattr(
        scheduler_monitor,
        "attach_to_scheduler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("listener broken")),
    )

    with pytest.raises(RuntimeError, match="listener broken"):
        auto_tasks._start_with_task_scheduler(SimpleNamespace(db=SimpleNamespace()))

    assert fake.started is False


def test_clean_checkout_discovers_all_task_classes():
    from tasks.task_scheduler import TaskScheduler

    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler.rm = SimpleNamespace(config={})
    scheduler.tasks = {}

    scheduler._discover_and_load_tasks()

    assert len(scheduler.tasks) == 45
    assert "check_db_migration" in scheduler.tasks
    assert "check_expired_redpackets" in scheduler.tasks
    assert sum(len(task.schedule()) for task in scheduler.tasks.values()) == 46


def test_task_discovery_import_failure_is_fatal(monkeypatch):
    from tasks import task_scheduler

    scheduler = task_scheduler.TaskScheduler.__new__(task_scheduler.TaskScheduler)
    scheduler.rm = SimpleNamespace(config={})
    scheduler.tasks = {}
    monkeypatch.setattr(task_scheduler, "_TASK_PACKAGES", ["tasks.broken"])
    monkeypatch.setattr(
        task_scheduler.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ImportError(f"cannot import {name}")),
    )

    with pytest.raises(RuntimeError, match="任务发现失败"):
        scheduler._discover_and_load_tasks()


def test_task_discovery_instantiation_failure_is_fatal(monkeypatch):
    from tasks import task_scheduler
    from tasks.base_task import BaseTask

    class BrokenTask(BaseTask):
        def __init__(self, _rm):
            raise RuntimeError("broken init")

        @property
        def task_id(self):
            return "broken"

        def schedule(self):
            return []

        def execute(self, _ctx):
            return None

    package = SimpleNamespace(__path__=["fake"])
    module = SimpleNamespace(BrokenTask=BrokenTask)
    scheduler = task_scheduler.TaskScheduler.__new__(task_scheduler.TaskScheduler)
    scheduler.rm = SimpleNamespace(config={})
    scheduler.tasks = {}
    monkeypatch.setattr(task_scheduler, "_TASK_PACKAGES", ["tasks.fake"])
    monkeypatch.setattr(
        task_scheduler.importlib,
        "import_module",
        lambda name: package if name == "tasks.fake" else module,
    )
    monkeypatch.setattr(
        task_scheduler.pkgutil,
        "iter_modules",
        lambda _paths: [(None, "broken_task", False)],
    )

    with pytest.raises(RuntimeError, match="实例化任务 BrokenTask 失败"):
        scheduler._discover_and_load_tasks()


def test_task_registration_failure_prevents_scheduler_start():
    from tasks import task_scheduler

    class _Task:
        def schedule(self):
            return [{"job_id": "broken_job", "trigger": "cron", "minute": 0}]

        def create_context(self, params):
            return params

        def execute(self, _ctx):
            return None

    class _Scheduler:
        started = False

        def add_job(self, *_args, **_kwargs):
            raise ValueError("invalid cron")

        def start(self):
            self.started = True

    scheduler = task_scheduler.TaskScheduler.__new__(task_scheduler.TaskScheduler)
    scheduler.tasks = {"broken": _Task()}
    scheduler.scheduler = _Scheduler()

    with pytest.raises(RuntimeError, match="任务注册失败"):
        scheduler.start()

    assert scheduler.scheduler.started is False
