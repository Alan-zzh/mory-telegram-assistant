"""
tasks/base_task.py - 任务基类与执行上下文

提供统一的任务接口和上下文对象，所有定时任务模块必须继承 BaseTask。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Set

from core.logging_util import get_logger
from core.resource_manager import ResourceManager

logger = get_logger("tasks.base_task")

# 时区：VPS 默认 UTC，强制用北京时间（UTC+8）
_CST = timezone(timedelta(hours=8))


@dataclass
class TaskContext:
    """
    任务执行上下文。

    通过 ResourceManager 统一访问共享资源，避免任务直接依赖具体实现。
    同时携带本次执行的额外参数（如 period）和运行状态。
    """

    rm: ResourceManager
    params: Dict[str, Any] = field(default_factory=dict)
    task_name: str = ""

    # 便捷属性
    @property
    def bot(self):
        return self.rm.bot

    @property
    def ai(self):
        return self.rm.ai

    @property
    def db(self):
        return self.rm.db

    @property
    def config(self):
        return self.rm.config

    @property
    def save_config_fn(self) -> Optional[Callable]:
        return self.rm.save_config_fn

    @property
    def now(self) -> datetime:
        return datetime.now(_CST)

    def now_str(self, fmt: str = "%Y-%m-%d") -> str:
        return self.now.strftime(fmt)


class BaseTask(ABC):
    """
    定时任务基类。

    子类必须实现：
      - task_id: 任务唯一标识（用于日志、告警、task_log）
      - execute(ctx): 任务执行逻辑
      - schedule(): 返回调度配置列表，供 TaskScheduler 注册

    调度配置格式示例：
        [
            {
                "job_id": "mystic_morning",
                "trigger": "cron",
                "hour": 9,
                "minute": 0,
                "params": {"period": "morning"},
                "options": {"max_instances": 1, "coalesce": True, "misfire_grace_time": 60},
            },
            ...
        ]
    """

    def __init__(self, rm: ResourceManager):
        self.rm = rm

    @property
    @abstractmethod
    def task_id(self) -> str:
        """任务唯一标识（通常与模块名一致）。"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, ctx: TaskContext) -> None:
        """执行任务。"""
        raise NotImplementedError

    def schedule(self) -> List[Dict[str, Any]]:
        """
        返回本任务的所有调度配置。

        默认空列表表示不由调度器自动注册（例如被其他任务内联调用）。
        """
        return []

    def create_context(self, params: Optional[Dict[str, Any]] = None) -> TaskContext:
        """创建带默认任务名的上下文。"""
        return TaskContext(
            rm=self.rm,
            params=params or {},
            task_name=self.task_id,
        )

    def run(self, params: Optional[Dict[str, Any]] = None) -> None:
        """外部直接调用入口（便于测试和手动触发）。"""
        ctx = self.create_context(params)
        self.execute(ctx)

    def __call__(self, ctx: Optional[TaskContext] = None) -> None:
        """兼容 APScheduler 直接传入 None 的调用方式。"""
        if ctx is None:
            ctx = self.create_context()
        self.execute(ctx)
