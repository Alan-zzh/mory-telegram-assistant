"""
tasks/maintenance/points_decay_task.py - 积分衰减任务

每日凌晨执行积分衰减。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.points_enhanced import run_points_decay
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.points_decay")

_CST = timezone(timedelta(hours=8))


class PointsDecayTask(BaseTask):
    """积分衰减任务（每日 0:05）。"""

    @property
    def task_id(self) -> str:
        return "points_decay"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "points_decay",
            "trigger": "cron",
            "hour": 0,
            "minute": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            run_points_decay(self.rm.bot, self.rm.config, self.rm.db)
        except Exception as e:
            logger.error(f"积分衰减异常：{e}")
