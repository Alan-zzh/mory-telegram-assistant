"""
tasks/monitoring/sync_scheduler_metrics_task.py - 调度指标定时落盘任务

每 5 分钟将内存中的调度指标批量刷盘到 scheduler_metrics 表。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.monitoring.sync_scheduler_metrics")

_CST = timezone(timedelta(hours=8))


class SyncSchedulerMetricsTask(BaseTask):
    """调度指标定时落盘任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "sync_scheduler_metrics"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "sync_scheduler_metrics",
            "trigger": "interval",
            "minutes": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from core.scheduler_monitor import sync_metrics_to_db
            count = sync_metrics_to_db(ctx.db)
            if count:
                logger.debug(f"[Scheduler] 指标落盘 {count} 个任务")
        except Exception as e:
            logger.debug(f"调度指标落盘异常：{e}")
