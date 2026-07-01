"""
tasks/task_scheduler.py - 统一任务调度器

自动发现并注册 tasks/ 下所有 BaseTask 子类，替代原 auto_tasks.py 中的调度逻辑。
"""

import importlib
import inspect
import pkgutil
from typing import Any, Dict, List, Optional

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
    """返回当前调度器的 BackgroundScheduler 实例（无则返回 None）。"""
    if _scheduler_instance is None:
        return None
    return _scheduler_instance.scheduler


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
        self._discover_and_load_tasks()

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
        for package_name in _TASK_PACKAGES:
            try:
                package = importlib.import_module(package_name)
            except Exception as e:
                logger.warning(f"加载任务包 {package_name} 失败: {e}")
                continue

            for _, module_name, _ in pkgutil.iter_modules(getattr(package, "__path__", [])):
                full_name = f"{package_name}.{module_name}"
                try:
                    module = importlib.import_module(full_name)
                except Exception as e:
                    logger.warning(f"加载任务模块 {full_name} 失败: {e}")
                    continue

                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if obj is BaseTask:
                        continue
                    if not issubclass(obj, BaseTask):
                        continue
                    try:
                        task = obj(self.rm)
                    except Exception as e:
                        logger.warning(f"实例化任务 {obj.__name__} 失败: {e}")
                        continue

                    if task.task_id in self.tasks:
                        logger.warning(f"任务 {task.task_id} 重复注册，跳过 {full_name}")
                        continue
                    self.tasks[task.task_id] = task
                    logger.debug(f"加载任务: {task.task_id} ({obj.__name__})")

    def _register_tasks(self):
        """将所有任务的 schedule() 配置注册到 APScheduler。"""
        registered = 0
        for task_id, task in self.tasks.items():
            for cfg in task.schedule():
                if not cfg:
                    continue
                trigger = cfg.get("trigger", "cron")
                job_id = cfg.get("job_id")
                if not job_id:
                    logger.warning(f"任务 {task_id} 的调度配置缺少 job_id，跳过")
                    continue

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
                        task.execute,
                        trigger=trigger,
                        args=[ctx],
                        id=job_id,
                        **trigger_kwargs,
                        **options,
                    )
                    registered += 1
                    logger.info(f"注册任务: {job_id} ({trigger} {trigger_kwargs})")
                except Exception as e:
                    logger.error(f"注册任务 {job_id} 失败: {e}")

        logger.info(f"✅ 任务调度器准备就绪，共注册 {registered} 个调度任务")

    def start(self):
        """注册并启动调度器。"""
        self._register_tasks()
        self.scheduler.start()
        logger.info("✅ 任务调度器已启动")

    def shutdown(self, wait: bool = True):
        """关闭调度器。"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=wait)
            logger.info("任务调度器已关闭")


def create_scheduler(rm: ResourceManager, max_workers: int = 30) -> TaskScheduler:
    """创建并返回 TaskScheduler 全局单例。"""
    global _scheduler_instance
    _scheduler_instance = TaskScheduler(rm, max_workers=max_workers)
    return _scheduler_instance
