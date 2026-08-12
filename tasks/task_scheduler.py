"""
tasks/task_scheduler.py - 统一任务调度器

自动发现并注册 tasks/ 下所有 BaseTask 子类，替代原 auto_tasks.py 中的调度逻辑。
"""

import importlib
import inspect
import pkgutil
import threading
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
