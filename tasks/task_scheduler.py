"""
tasks/task_scheduler.py - 统一任务调度器

自动发现并注册 tasks/ 下所有 BaseTask 子类，替代原 auto_tasks.py 中的调度逻辑。
"""

import importlib
import inspect
import pkgutil
import threading
import time
from typing import Any, Dict, Optional

from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from tasks.base_task import BaseTask

logger = get_logger("tasks.task_scheduler")

# 需要自动扫描的任务子包
_TASK_PACKAGES = [
    "tasks.broadcast",
    "tasks.interaction",
    "tasks.maintenance",
    "tasks.monitoring",
    "tasks.analytics",
]

# 调度器全局单例（供 tasks.support.common.schedule_auto_delete/retry_task 使用）
_scheduler_instance: Optional["TaskScheduler"] = None


def get_scheduler_instance() -> Optional[Any]:
    """返回受生命周期闸门保护的调度控制器（无则返回 None）。"""
    return _scheduler_instance


def get_task_scheduler() -> Optional["TaskScheduler"]:
    """返回调度控制器，供配置热重载按最新开关重编排任务。"""
    return _scheduler_instance


class TaskScheduler:
    """
    统一任务调度器。

    职责：
      1. 自动扫描 tasks/ 下所有 BaseTask 子类
      2. 按 schedule() 配置注册到 APScheduler
      3. 启动/关闭调度器
    """

    def __init__(self, rm: ResourceManager, max_workers: int = 30):
        self.rm = rm
        self.tasks: Dict[str, BaseTask] = {}
        self.scheduler = self._create_scheduler(max_workers)
        self._registered_job_ids: set[str] = set()
        self._init_lifecycle_state()
        self._discover_and_load_tasks()

    def __getattr__(self, name: str) -> Any:
        """保留 BackgroundScheduler 的只读/监听兼容面；add_job 由本类接管。"""
        scheduler = self.__dict__.get("scheduler")
        if scheduler is None:
            raise AttributeError(name)
        return getattr(scheduler, name)

    def _init_lifecycle_state(self):
        """建立 job 入口闸门与运行计数，保障关库前可以安全 drain。"""
        self._lifecycle_lock = threading.Condition(threading.RLock())
        self._accepting_tasks = True
        self._active_task_count = 0

    def _execute_callable(
        self,
        func: Any,
        args: tuple[Any, ...],
        kwargs: Dict[str, Any],
        label: str,
    ):
        """所有 APScheduler job 的唯一入口；关停后拒绝尚未开始的任务。"""
        with self._lifecycle_lock:
            if not self._accepting_tasks:
                logger.info("调度器正在关闭，跳过未开始任务: %s", label)
                return
            self._active_task_count += 1
        try:
            return func(*args, **kwargs)
        finally:
            with self._lifecycle_lock:
                self._active_task_count -= 1
                self._lifecycle_lock.notify_all()

    def _execute_task(self, task: BaseTask, ctx: Any):
        return self._execute_callable(
            task.execute,
            (ctx,),
            {},
            getattr(task, "task_id", task.__class__.__name__),
        )

    def add_job(self, func: Any, *positional_args: Any, **job_kwargs: Any):
        """兼容动态 job 注册，同时使其接受关停闸门与 drain 统计。"""
        args = tuple(job_kwargs.pop("args", ()) or ())
        kwargs = dict(job_kwargs.pop("kwargs", {}) or {})
        label = getattr(func, "__name__", func.__class__.__name__)
        return self.scheduler.add_job(
            self._execute_callable,
            *positional_args,
            args=[func, args, kwargs, label],
            **job_kwargs,
        )

    def drain(self, timeout: float = 20.0) -> bool:
        """等待已开始任务完成；超时则让调用方保持数据库连接。"""
        timeout = max(0.0, timeout)
        with self._lifecycle_lock:
            if self._active_task_count == 0:
                return True
            return self._lifecycle_lock.wait_for(
                lambda: self._active_task_count == 0,
                timeout=timeout,
            )

    @staticmethod
    def _create_scheduler(max_workers: int):
        """创建 BackgroundScheduler，配置与原 auto_tasks.py 保持一致。"""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.executors.pool import ThreadPoolExecutor
        except ImportError as e:
            logger.error(f"APScheduler 未安装: {e}")
            raise

        return BackgroundScheduler(
            timezone="Asia/Shanghai",
            executors={"default": ThreadPoolExecutor(max_workers=max_workers)},
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
        )

    def _discover_and_load_tasks(self):
        """自动发现并实例化所有任务类。"""
        errors: list[Exception] = []
        for package_name in _TASK_PACKAGES:
            try:
                package = importlib.import_module(package_name)
            except Exception as e:
                logger.error(f"加载任务包 {package_name} 失败: {e}")
                errors.append(RuntimeError(f"加载任务包 {package_name} 失败: {e}"))
                continue

            try:
                modules = list(pkgutil.iter_modules(getattr(package, "__path__", [])))
            except Exception as e:
                logger.error(f"扫描任务包 {package_name} 失败: {e}")
                errors.append(RuntimeError(f"扫描任务包 {package_name} 失败: {e}"))
                continue

            for _, module_name, _ in modules:
                full_name = f"{package_name}.{module_name}"
                try:
                    module = importlib.import_module(full_name)
                except Exception as e:
                    logger.error(f"加载任务模块 {full_name} 失败: {e}")
                    errors.append(RuntimeError(f"加载任务模块 {full_name} 失败: {e}"))
                    continue

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if obj is BaseTask:
                        continue
                    if not issubclass(obj, BaseTask):
                        continue
                    try:
                        task = obj(self.rm)
                    except Exception as e:
                        logger.error(f"实例化任务 {obj.__name__} 失败: {e}")
                        errors.append(RuntimeError(f"实例化任务 {obj.__name__} 失败: {e}"))
                        continue

                    if task.task_id in self.tasks:
                        error = RuntimeError(f"任务 {task.task_id} 重复注册: {full_name}")
                        logger.error(str(error))
                        errors.append(error)
                        continue
                    self.tasks[task.task_id] = task
                    logger.debug(f"加载任务: {task.task_id} ({obj.__name__})")

        if errors:
            summary = "; ".join(str(error) for error in errors[:10])
            raise RuntimeError(f"任务发现失败，共 {len(errors)} 项: {summary}") from ExceptionGroup(
                "任务发现失败明细", errors
            )

    def _register_tasks(self, *, replace_existing: bool = False, remove_stale: bool = False):
        """按当前配置同步任务。

        首次启动只注册；配置热重载时替换仍启用的 job，并删除本控制器此前
        注册但当前已关闭的 job。动态 retry/auto-delete 等外部 job 不在
        ``_registered_job_ids`` 中，不会被误删。
        """
        registered = 0
        errors: list[Exception] = []
        desired_job_ids: set[str] = set()
        previous_job_ids = set(getattr(self, "_registered_job_ids", set()))
        for task_id, task in self.tasks.items():
            try:
                schedule_items = task.schedule()
            except Exception as e:
                logger.error(f"读取任务 {task_id} 调度配置失败: {e}")
                errors.append(RuntimeError(f"读取任务 {task_id} 调度配置失败: {e}"))
                continue
            for cfg in schedule_items:
                if not cfg:
                    continue
                trigger = cfg.get("trigger", "cron")
                job_id = cfg.get("job_id")
                if not job_id:
                    missing_job_error = ValueError(f"任务 {task_id} 的调度配置缺少 job_id")
                    logger.error(str(missing_job_error))
                    errors.append(missing_job_error)
                    continue
                if job_id in desired_job_ids:
                    duplicate_job_error = RuntimeError(f"任务 job_id 重复: {job_id}")
                    logger.error(str(duplicate_job_error))
                    errors.append(duplicate_job_error)
                    continue
                desired_job_ids.add(job_id)

                params = cfg.get("params", {})
                options = cfg.get("options", {})

                # 收集触发器参数
                trigger_kwargs: Dict[str, Any] = {}
                for key in [
                    "year", "month", "day", "week", "day_of_week",
                    "hour", "minute", "second",
                    "start_date", "end_date", "timezone", "jitter",
                ]:
                    if key in cfg:
                        trigger_kwargs[key] = cfg[key]

                # interval 触发器参数
                for key in ["weeks", "days", "hours", "minutes", "seconds"]:
                    if key in cfg:
                        trigger_kwargs[key] = cfg[key]

                # date 触发器参数
                for key in ["run_date"]:
                    if key in cfg:
                        trigger_kwargs[key] = cfg[key]

                ctx = task.create_context(params)
                try:
                    self.scheduler.add_job(
                        self._execute_task,
                        trigger=trigger,
                        args=[task, ctx],
                        id=job_id,
                        replace_existing=replace_existing,
                        **trigger_kwargs,
                        **options,
                    )
                    registered += 1
                    logger.info(f"注册任务: {job_id} ({trigger} {trigger_kwargs})")
                except Exception as e:
                    logger.error(f"注册任务 {job_id} 失败: {e}")
                    errors.append(RuntimeError(f"注册任务 {job_id} 失败: {e}"))

        if not errors and remove_stale:
            for stale_job_id in sorted(previous_job_ids - desired_job_ids):
                try:
                    self.scheduler.remove_job(stale_job_id)
                    logger.info(f"移除已关闭任务: {stale_job_id}")
                except Exception as e:
                    logger.error(f"移除已关闭任务 {stale_job_id} 失败: {e}")
                    errors.append(RuntimeError(f"移除已关闭任务 {stale_job_id} 失败: {e}"))

        if errors:
            summary = "; ".join(str(error) for error in errors[:10])
            raise RuntimeError(f"任务注册失败，共 {len(errors)} 项: {summary}") from ExceptionGroup(
                "任务注册失败明细", errors
            )

        self._registered_job_ids = desired_job_ids
        logger.info(f"✅ 任务调度器准备就绪，共注册 {registered} 个调度任务")

    def refresh_tasks(self):
        """配置热重载后重编排本控制器管理的 job。"""
        self._register_tasks(replace_existing=True, remove_stale=True)
        logger.info("✅ 调度任务已按热重载配置刷新")

    def start(self):
        """注册并启动调度器。"""
        self._register_tasks()
        self.scheduler.start()
        logger.info("✅ 任务调度器已启动")

    def shutdown(self, wait: bool = True):
        """关闭调度器。"""
        with self._lifecycle_lock:
            self._accepting_tasks = False
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("任务调度器已关闭")


def create_scheduler(rm: ResourceManager, max_workers: int = 30) -> TaskScheduler:
    """创建并返回 TaskScheduler 全局单例。"""
    global _scheduler_instance
    # 【P0-NEW-05 修复】防止重复创建导致任务双实例：先关闭旧调度器
    if _scheduler_instance is not None and getattr(_scheduler_instance, 'scheduler', None) is not None:
        try:
            if _scheduler_instance.scheduler.running:
                logger.warning("⚠️ create_scheduler 被重复调用，先关闭旧实例")
                _scheduler_instance.scheduler.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"关闭旧调度器失败: {e}")
    _scheduler_instance = TaskScheduler(rm, max_workers=max_workers)
    return _scheduler_instance


# ══════════════════════════════════════════════════════════════════════════
#  后台任务引擎启动（自 modules/auto_tasks.py v5.38.69 收敛迁移；
#  原文件已拆除，本节是 start_background 唯一真相源）
# ══════════════════════════════════════════════════════════════════════════

_resource_manager_instance: Optional[ResourceManager] = None
_startup_maintenance_thread: Optional[threading.Thread] = None
_startup_maintenance_lock = threading.Lock()
_startup_maintenance_stop_event: Optional[threading.Event] = None
_startup_maintenance_done_event: Optional[threading.Event] = None
_WATCHDOG_TIMEOUT_SEC = 900  # 15 分钟


def start_background(
    bot,
    config: Dict[str, Any],
    db,
    ai,
    save_config_fn,
    resource_manager: Optional[ResourceManager] = None,
):
    """启动后台任务引擎并返回全局唯一的 ResourceManager。

    调度器任务与消息分发必须共享同一把资源锁。调用方可以传入初始化阶段
    已创建的实例；重复启动则返回正在服务的实例，绝不另建锁域。
    """
    from core.task_transaction import TaskTransactionManager
    from tasks.support.fault_reporter import get_fault_reporter
    from tasks.support.task_guard import get_task_guard

    global _resource_manager_instance, _scheduler_instance
    if _scheduler_instance is not None and getattr(_scheduler_instance, 'running', False):
        logger.warning("⚠️ 后台任务引擎已在运行，跳过重复启动")
        if _resource_manager_instance is None:
            raise RuntimeError("后台调度器运行中但缺少共享 ResourceManager")
        return _resource_manager_instance

    rm = resource_manager or ResourceManager(
        bot=bot,
        ai=ai,
        db=db,
        config=config,
        save_config_fn=save_config_fn,
    )
    _resource_manager_instance = rm
    TaskTransactionManager.bind(rm)
    get_task_guard().bind(rm)
    get_fault_reporter().bind(rm)

    try:
        _start_with_task_scheduler(rm)
    except Exception:
        # 启动未完成时不保留半初始化锁域；下一次启动可重新创建。
        if _scheduler_instance is None or not getattr(_scheduler_instance, 'running', False):
            _resource_manager_instance = None
        raise
    return rm


def _start_with_task_scheduler(rm):
    """新调度器入口：自动发现并注册 tasks/ 下所有任务。"""
    global _scheduler_instance

    scheduler = create_scheduler(rm)
    # 对外统一暴露带生命周期闸门的控制器；抽奖、签到、场景触发器与动态
    # auto-delete/retry 不得绕过 active-job 计数后在关库阶段继续访问 SQLite。
    _scheduler_instance = scheduler

    # 场景化触发器注册（与热重载共用同一幂等入口）
    from modules.triggers.base import refresh_trigger_jobs
    from modules.triggers.cold_group import ColdGroupTrigger
    from modules.triggers.night_hint import NightHintTrigger
    refresh_trigger_jobs(
        _scheduler_instance,
        rm,
        (ColdGroupTrigger, NightHintTrigger),
    )

    # 附加调度监控（监听 EXECUTED/ERROR/MISSED 事件）
    from core.scheduler_monitor import attach_to_scheduler
    attach_to_scheduler(scheduler.scheduler, db=rm.db)

    # 注册/监控均成功后才启动并落跨进程心跳，再异步执行耗时的全员扫描。
    # 否则数千人的 Telegram API 调用会在 scheduler.start() 前阻塞数分钟，
    # Dashboard 将旧心跳判为 503，外部 watchdog 还会形成误重启循环。
    scheduler.start()
    _persist_startup_heartbeat(rm)

    # 看门狗必须在 scheduler 与首个持久心跳成功后启动，失败则阻止残缺服务继续。
    from tasks.monitoring.watchdog_task import WatchdogTask
    WatchdogTask(rm).start(timeout_sec=_WATCHDOG_TIMEOUT_SEC)
    _start_startup_maintenance(rm)


def _persist_startup_heartbeat(rm):
    """启动扫描前立即写入内存与数据库心跳。"""
    now = int(time.time())
    from tasks.monitoring.heartbeat_task import update_heartbeat
    update_heartbeat()
    rm.db.set_system_state("last_heartbeat", str(now))


def _run_startup_maintenance(
    rm,
    stop_event: Optional[threading.Event] = None,
    done_event: Optional[threading.Event] = None,
):
    """后台串行执行启动扫描和历史清理，不阻塞 scheduler/polling。

    ``stop_event`` 只在两个维护阶段之间检查：正在进行的 Telegram/DB
    调用无法被安全强杀，关停方必须通过 ``done_event`` + ``join`` 确认它
    已经返回后才允许关闭共享数据库。
    """
    try:
        if stop_event is not None and stop_event.is_set():
            logger.info("[启动维护] 收到停机请求，跳过尚未开始的启动扫描")
            return

        try:
            from tasks.maintenance.startup_member_scan_task import StartupMemberScanTask
            StartupMemberScanTask(rm).run()
        except Exception as e:
            logger.warning(f"启动成员扫描失败: {e}")

        if stop_event is not None and stop_event.is_set():
            logger.info("[启动维护] 收到停机请求，跳过尚未开始的历史清理")
            return

        try:
            from tasks.maintenance.startup_history_cleanup_task import StartupHistoryCleanupTask
            StartupHistoryCleanupTask(rm).run()
        except Exception as e:
            logger.warning(f"启动历史清理失败: {e}")
    finally:
        if done_event is not None:
            done_event.set()


def _start_startup_maintenance(rm):
    """启动唯一的后台维护线程；返回线程供测试与诊断。"""
    global _startup_maintenance_thread, _startup_maintenance_stop_event, _startup_maintenance_done_event
    with _startup_maintenance_lock:
        if _startup_maintenance_thread is not None and _startup_maintenance_thread.is_alive():
            logger.warning("启动维护线程已在运行，跳过重复启动")
            return _startup_maintenance_thread

        stop_event = threading.Event()
        done_event = threading.Event()
        thread = threading.Thread(
            target=_run_startup_maintenance,
            args=(rm, stop_event, done_event),
            name="mory-startup-maintenance",
            daemon=True,
        )
        _startup_maintenance_thread = thread
        _startup_maintenance_stop_event = stop_event
        _startup_maintenance_done_event = done_event
        thread.start()
        return thread


def stop_startup_maintenance(join_timeout: float = 20.0) -> bool:
    """请求停止启动维护并在有界时间内确认线程已完成。

    返回 ``False`` 表示线程仍可能访问 ResourceManager/SQLite；调用方必须
    保持数据库连接打开，并将该失败状态显式记录给运维面。
    """
    global _startup_maintenance_thread, _startup_maintenance_stop_event, _startup_maintenance_done_event
    timeout = max(0.0, join_timeout)
    deadline = time.monotonic() + timeout
    with _startup_maintenance_lock:
        thread = _startup_maintenance_thread
        stop_event = _startup_maintenance_stop_event
        done_event = _startup_maintenance_done_event
        if thread is None:
            return True
        if stop_event is not None:
            stop_event.set()

    if thread is threading.current_thread():
        logger.error("[启动维护] 停止请求来自维护线程自身，拒绝自 join；数据库必须保持开启")
        return False

    # 完成事件是协作协议；join 仍是最终线程状态确认，避免事件已 set 但
    # 线程尚未真正退出的极窄窗口。
    if thread.is_alive():
        if done_event is not None:
            done_event.wait(timeout=timeout)
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    if thread.is_alive():
        logger.error(
            "[启动维护] 线程未在 %.1fs 内退出，数据库连接必须保持开启",
            timeout,
        )
        return False

    with _startup_maintenance_lock:
        if _startup_maintenance_thread is thread:
            _startup_maintenance_thread = None
            _startup_maintenance_stop_event = None
            _startup_maintenance_done_event = None
    logger.info("[启动维护] 启动维护线程已完成并退出")
    return True
