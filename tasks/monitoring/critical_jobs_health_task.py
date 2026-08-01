"""
tasks/monitoring/critical_jobs_health_task.py - 关键任务健康检查任务

每 30 分钟检查早安/午安/晚安/播报等关键任务是否在预期窗口内成功执行。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.monitoring.critical_jobs_health")

_CST = timezone(timedelta(hours=8))


class CriticalJobsHealthTask(BaseTask):
    """关键任务健康检查任务（每 30 分钟）。"""

    @property
    def task_id(self) -> str:
        return "critical_jobs_health_check"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "critical_jobs_health_check",
            "trigger": "interval",
            "minutes": 30,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from core.scheduler_monitor import check_critical_jobs_health
            check_critical_jobs_health(scheduler=None, config=ctx.config, db=ctx.db)
        except Exception as e:
            logger.error(f"关键任务健康检查异常：{e}")
            raise
