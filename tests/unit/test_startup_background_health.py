# -*- coding: utf-8 -*-
"""启动维护不能阻塞 heartbeat、scheduler 或 Telegram polling。"""

import threading
import time
from types import SimpleNamespace

import pytest


def test_persist_startup_heartbeat_writes_cross_process_state():
    from tasks.task_scheduler import _persist_startup_heartbeat

    writes = []
    rm = SimpleNamespace(db=SimpleNamespace(set_system_state=lambda key, value: writes.append((key, value))))
    before = int(time.time())

    _persist_startup_heartbeat(rm)

    assert writes[0][0] == "last_heartbeat"
    assert before <= int(writes[0][1]) <= int(time.time())


def test_startup_member_scan_runs_in_background(monkeypatch):
    from tasks import task_scheduler
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
    monkeypatch.setattr(task_scheduler, "_startup_maintenance_thread", None)

    begin = time.monotonic()
    thread = task_scheduler._start_startup_maintenance(SimpleNamespace())
    elapsed = time.monotonic() - begin

    assert elapsed < 0.5
    assert started.wait(timeout=1)
    assert thread.is_alive()
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert history_ran.is_set()


def test_scheduler_starts_before_startup_maintenance(monkeypatch):
    from tasks import task_scheduler
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
    monkeypatch.setattr(task_scheduler, "_persist_startup_heartbeat", lambda rm: events.append("heartbeat_persisted"))
    monkeypatch.setattr(task_scheduler, "_start_startup_maintenance", lambda rm: events.append("maintenance_started"))

    task_scheduler._start_with_task_scheduler(SimpleNamespace(db=SimpleNamespace()))

    assert task_scheduler._scheduler_instance is fake
    assert events.index("scheduler_started") < events.index("heartbeat_persisted")
    assert events.index("heartbeat_persisted") < events.index("watchdog_started")
    assert events.index("watchdog_started") < events.index("maintenance_started")


def test_scheduler_monitor_attach_failure_prevents_start(monkeypatch):
    from tasks import task_scheduler
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
        task_scheduler._start_with_task_scheduler(SimpleNamespace(db=SimpleNamespace()))

    assert fake.started is False


def test_clean_checkout_discovers_all_task_classes():
    from tasks.task_scheduler import TaskScheduler

    scheduler = TaskScheduler.__new__(TaskScheduler)
    # 空 config：默认关闭的任务 schedule() 返回 []，避免僵尸 job
    scheduler.rm = SimpleNamespace(config={})
    scheduler.tasks = {}

    scheduler._discover_and_load_tasks()

    assert len(scheduler.tasks) == 46
    assert "check_db_migration" in scheduler.tasks
    assert "check_expired_redpackets" in scheduler.tasks
    empty_cfg_jobs = sum(len(task.schedule()) for task in scheduler.tasks.values())
    assert empty_cfg_jobs < 46  # 关闭态不应注册满量 job
    assert empty_cfg_jobs >= 20  # 仍有一批始终在线的维护/监控 job

    # 开启关键播报/互动开关后，应恢复到满量调度项
    enabled = {
        "AUTO_GREETING": True,
        "GREETING_CONFIG": {
            "morning_enabled": True,
            "afternoon_enabled": True,
            "evening_enabled": True,
            "night_enabled": False,
        },
        "MYSTIC_BROADCAST_CONFIG": {"enabled": True},
        "CART_RECOVERY_CONFIG": {"enabled": True},
        "LEAK_CONFIG": {"enabled": True},
        "FAQ_TRACKING_ENABLED": True,
        "DAILY_BACKUP_ENABLED": True,
    }
    for task in scheduler.tasks.values():
        task.rm = SimpleNamespace(config=enabled)
    enabled_jobs = sum(len(task.schedule()) for task in scheduler.tasks.values())
    assert enabled_jobs >= 40


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


def test_task_refresh_adds_and_removes_config_gated_jobs_without_touching_dynamic_jobs():
    """热重载必须真实增删 schedule() job，且不得误删运行时动态 job。"""
    from tasks import task_scheduler

    class _Task:
        def __init__(self, rm):
            self.rm = rm

        def schedule(self):
            if not self.rm.config.get("enabled", False):
                return []
            return [{"job_id": "toggle_job", "trigger": "cron", "minute": 5}]

        def create_context(self, params):
            return params

        def execute(self, _ctx):
            return None

    class _Scheduler:
        def __init__(self):
            self.jobs = {"retry_dynamic": {"external": True}}

        def add_job(self, _func, **kwargs):
            job_id = kwargs["id"]
            if job_id in self.jobs and not kwargs.get("replace_existing"):
                raise ValueError("duplicate")
            self.jobs[job_id] = kwargs

        def remove_job(self, job_id):
            self.jobs.pop(job_id)

    rm = SimpleNamespace(config={"enabled": False})
    controller = task_scheduler.TaskScheduler.__new__(task_scheduler.TaskScheduler)
    controller.rm = rm
    controller.tasks = {"toggle": _Task(rm)}
    controller.scheduler = _Scheduler()
    controller._registered_job_ids = set()

    controller._register_tasks()
    assert set(controller.scheduler.jobs) == {"retry_dynamic"}

    rm.config["enabled"] = True
    controller.refresh_tasks()
    assert set(controller.scheduler.jobs) == {"retry_dynamic", "toggle_job"}
    assert controller.scheduler.jobs["toggle_job"]["replace_existing"] is True

    rm.config["enabled"] = False
    controller.refresh_tasks()
    assert set(controller.scheduler.jobs) == {"retry_dynamic"}


def test_apply_reloaded_config_rolls_back_when_scheduler_refresh_fails(monkeypatch):
    """调度刷新失败时配置不能单独生效，避免 UI 与运行任务再次分裂。"""
    from core import bot_initializer

    cfg = {"enabled": False, "CURRENT_MODEL_INDEX": 3}
    calls = []

    def _refresh():
        calls.append(dict(cfg))
        if len(calls) == 1:
            raise RuntimeError("refresh failed")

    monkeypatch.setattr(bot_initializer, "_refresh_scheduled_tasks", _refresh)

    with pytest.raises(RuntimeError, match="refresh failed"):
        bot_initializer._apply_reloaded_config(cfg, {"enabled": True})

    assert cfg == {"enabled": False, "CURRENT_MODEL_INDEX": 3}
    assert calls[0]["enabled"] is True
    assert calls[0]["CURRENT_MODEL_INDEX"] == 3
    assert calls[1]["enabled"] is False
