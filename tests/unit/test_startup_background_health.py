# -*- coding: utf-8 -*-
"""启动维护不能阻塞 heartbeat、scheduler 或 Telegram polling。"""

import threading
import time
from types import SimpleNamespace


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
    monkeypatch.setattr(scheduler_monitor, "attach_to_scheduler", lambda scheduler: None)
    monkeypatch.setattr(auto_tasks, "_persist_startup_heartbeat", lambda rm: events.append("heartbeat_persisted"))
    monkeypatch.setattr(auto_tasks, "_start_startup_maintenance", lambda rm: events.append("maintenance_started"))

    auto_tasks._start_with_task_scheduler(SimpleNamespace())

    assert events.index("heartbeat_persisted") < events.index("scheduler_started")
    assert events.index("scheduler_started") < events.index("maintenance_started")
