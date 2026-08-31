"""启动、热重载与关停不得在生命周期边界丢失资源一致性。"""

import threading
from types import SimpleNamespace

import pytest


def test_background_start_reuses_the_same_resource_manager(monkeypatch):
    """重复启动必须返回同一锁域，不能再创建第二套 ResourceManager。"""
    from tasks import task_scheduler

    monkeypatch.setattr(task_scheduler, "_scheduler_instance", None)
    monkeypatch.setattr(task_scheduler, "_resource_manager_instance", None)

    started_with = []

    def _start(rm):
        started_with.append(rm)
        task_scheduler._scheduler_instance = SimpleNamespace(running=True)

    monkeypatch.setattr(task_scheduler, "_start_with_task_scheduler", _start)

    first = task_scheduler.start_background(object(), {}, object(), object(), lambda: None)
    second = task_scheduler.start_background(object(), {}, object(), object(), lambda: None)

    assert first is second
    assert started_with == [first]


def test_background_start_preserves_injected_resource_manager(monkeypatch):
    """BotContext 与任务调度器必须共同持有初始化器创建的同一实例。"""
    from tasks import task_scheduler

    monkeypatch.setattr(task_scheduler, "_scheduler_instance", None)
    monkeypatch.setattr(task_scheduler, "_resource_manager_instance", None)
    monkeypatch.setattr(task_scheduler, "_start_with_task_scheduler", lambda _rm: None)
    injected = SimpleNamespace()

    assert task_scheduler.start_background(
        object(), {}, object(), object(), lambda: None, resource_manager=injected
    ) is injected


def test_common_retry_never_starts_thread_without_scheduler(monkeypatch):
    """tasks/ 公共重试也必须服从统一调度生命周期。"""
    from tasks import task_scheduler
    from tasks.support import common

    monkeypatch.setattr(task_scheduler, "get_scheduler_instance", lambda: None)
    assert common.retry_task(object(), lambda _rm: None, "closed") is False


def test_reload_flag_is_retained_when_reloading_fails(monkeypatch, tmp_path):
    """损坏配置不可吞掉跨进程信号；修复后下一轮必须还能重试。"""
    from core import bot_initializer

    flag = tmp_path / "reload_flag"
    flag.touch()
    monkeypatch.setattr(bot_initializer, "RELOAD_FLAG", flag)
    monkeypatch.setattr(bot_initializer, "load_config", lambda: (_ for _ in ()).throw(ValueError("broken")))

    assert bot_initializer._reload_config_from_flag({}) is False
    assert flag.exists()


def test_reload_flag_is_consumed_only_after_success(monkeypatch, tmp_path):
    from core import bot_initializer

    flag = tmp_path / "reload_flag"
    flag.touch()
    monkeypatch.setattr(bot_initializer, "RELOAD_FLAG", flag)
    monkeypatch.setattr(bot_initializer, "load_config", lambda: {"feature": True})
    applied = []
    monkeypatch.setattr(
        bot_initializer, "_apply_reloaded_config", lambda cfg, new: applied.append((cfg, new))
    )

    assert bot_initializer._reload_config_from_flag({}) is True
    assert applied
    assert not flag.exists()


def test_reload_watcher_is_singleton_and_stoppable(monkeypatch):
    from core import bot_initializer

    bot_initializer.stop_config_reload_watcher(join_timeout=1)
    first = bot_initializer.start_config_reload_watcher({}, interval=60)
    second = bot_initializer.start_config_reload_watcher({}, interval=60)
    try:
        assert first is second
        assert first.is_alive()
    finally:
        assert bot_initializer.stop_config_reload_watcher(join_timeout=1)
    assert not first.is_alive()


def test_scheduler_shutdown_gates_queued_jobs_and_drains_running_jobs():
    """wait=False 后排队任务不得再触碰 DB；已开始任务需在有界时间内 drain。"""
    from tasks.task_scheduler import TaskScheduler

    class _BackgroundScheduler:
        running = True

        def __init__(self):
            self.shutdown_calls = []

        def shutdown(self, *, wait):
            self.shutdown_calls.append(wait)
            self.running = False

    started = threading.Event()
    release = threading.Event()

    class _Task:
        def execute(self, _ctx):
            started.set()
            assert release.wait(timeout=2)

    controller = TaskScheduler.__new__(TaskScheduler)
    controller.scheduler = _BackgroundScheduler()
    controller._init_lifecycle_state()
    worker = threading.Thread(target=controller._execute_task, args=(_Task(), {}))
    worker.start()
    assert started.wait(timeout=1)

    controller.shutdown(wait=False)
    assert controller.drain(timeout=0.01) is False
    release.set()
    worker.join(timeout=1)
    assert controller.drain(timeout=0.5) is True
    assert controller.scheduler.shutdown_calls == [False]

    executed = []
    controller._execute_task(SimpleNamespace(execute=lambda _ctx: executed.append(True)), {})
    assert executed == []


def test_dynamic_jobs_share_shutdown_gate_and_drain_tracking():
    """定时删除、重试等动态 job 也不能绕开关停保护。"""
    from tasks.task_scheduler import TaskScheduler

    class _BackgroundScheduler:
        running = False

        def __init__(self):
            self.kwargs = None

        def add_job(self, _func, *args, **kwargs):
            self.kwargs = kwargs
            return "scheduled"

    controller = TaskScheduler.__new__(TaskScheduler)
    controller.scheduler = _BackgroundScheduler()
    controller._init_lifecycle_state()

    assert controller.add_job(lambda value: value, trigger="date", args=["ok"]) == "scheduled"
    wrapped = controller.scheduler.kwargs["args"]
    assert wrapped[0]("ok") == "ok"
    assert wrapped[1] == ("ok",)

    controller.shutdown(wait=False)
    assert controller._execute_callable(lambda: (_ for _ in ()).throw(AssertionError()), (), {}, "dynamic") is None


def test_main_shutdown_helper_requires_scheduler_drain(monkeypatch):
    import main
    from tasks import task_scheduler

    calls = []
    controller = SimpleNamespace(
        shutdown=lambda *, wait: calls.append(("shutdown", wait)),
        drain=lambda *, timeout: calls.append(("drain", timeout)) or False,
    )
    monkeypatch.setattr(task_scheduler, "get_task_scheduler", lambda: controller)
    monkeypatch.setattr(
        task_scheduler,
        "stop_startup_maintenance",
        lambda *, join_timeout: calls.append(("maintenance", join_timeout)) or True,
    )

    assert main._shutdown_scheduler_for_db(timeout=0.01) is False
    assert calls[0] == ("shutdown", False)
    assert calls[1][0] == "drain"
    assert calls[1][1] == pytest.approx(0.01, abs=1e-6)
    assert calls[2][0] == "maintenance"
    assert 0 <= calls[2][1] <= calls[1][1] + 1e-6


def test_main_shutdown_shares_one_timeout_budget(monkeypatch):
    import main
    from tasks import task_scheduler

    calls = []
    monotonic_values = iter((100.0, 100.0, 100.007))
    monkeypatch.setattr(main.time, "monotonic", lambda: next(monotonic_values))
    controller = SimpleNamespace(
        shutdown=lambda *, wait: calls.append(("shutdown", wait)),
        drain=lambda *, timeout: calls.append(("drain", timeout)) or True,
    )
    monkeypatch.setattr(task_scheduler, "get_task_scheduler", lambda: controller)
    monkeypatch.setattr(
        task_scheduler,
        "stop_startup_maintenance",
        lambda *, join_timeout: calls.append(("maintenance", join_timeout)) or True,
    )

    assert main._shutdown_scheduler_for_db(timeout=0.01) is True
    assert calls[0] == ("shutdown", False)
    assert calls[1][0] == "drain"
    assert calls[1][1] == pytest.approx(0.01)
    assert calls[2][0] == "maintenance"
    assert calls[2][1] == pytest.approx(0.003)


def test_main_shutdown_refuses_db_close_while_startup_maintenance_is_blocked(monkeypatch):
    """启动维护未退出时，关停必须失败可见并阻止调用方关闭数据库。"""
    import main
    from tasks import task_scheduler

    started = threading.Event()
    release = threading.Event()

    def _blocking_maintenance(_rm, stop_event=None, done_event=None):
        started.set()
        try:
            # 故意不读取 stop_event：模拟无法被强杀的 Telegram/DB 调用。
            release.wait(timeout=2)
        finally:
            if done_event is not None:
                done_event.set()

    monkeypatch.setattr(task_scheduler, "_run_startup_maintenance", _blocking_maintenance)
    monkeypatch.setattr(task_scheduler, "_startup_maintenance_thread", None)
    monkeypatch.setattr(task_scheduler, "_startup_maintenance_stop_event", None)
    monkeypatch.setattr(task_scheduler, "_startup_maintenance_done_event", None)
    thread = task_scheduler._start_startup_maintenance(object())
    assert started.wait(timeout=1)

    controller = SimpleNamespace(
        shutdown=lambda *, wait: None,
        drain=lambda *, timeout: True,
    )
    monkeypatch.setattr(task_scheduler, "get_task_scheduler", lambda: controller)

    try:
        shutdown_ok = main._shutdown_scheduler_for_db(timeout=0.01)
        assert shutdown_ok is False
        assert thread.is_alive()
        # main.py 只有拿到 True 才会调用 ctx.db.close()。
    finally:
        release.set()
        assert task_scheduler.stop_startup_maintenance(join_timeout=1)
    assert not thread.is_alive()
