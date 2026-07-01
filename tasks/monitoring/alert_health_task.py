"""
tasks/monitoring/alert_health_task.py - 告警通道健康巡检任务

每 2 分钟检查一次告警规则通道健康状态。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.monitoring.alert_health")

_CST = timezone(timedelta(hours=8))


class AlertHealthTask(BaseTask):
    """告警通道健康巡检任务（每 2 分钟）。"""

    @property
    def task_id(self) -> str:
        return "alert_health_check"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "alert_health_check",
            "trigger": "interval",
            "minutes": 2,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 120,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from core.alert_rules import run_health_check
            run_health_check()
        except Exception as e:
            logger.error(f"告警健康巡检异常：{e}")
