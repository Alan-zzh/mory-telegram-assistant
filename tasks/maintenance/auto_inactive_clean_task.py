"""
tasks/maintenance/auto_inactive_clean_task.py - 自动清理不活跃用户任务

每日凌晨 3 点自动清理不活跃用户。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.inactive_clean import run_auto_inactive_clean
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.auto_inactive_clean")

_CST = timezone(timedelta(hours=8))


class AutoInactiveCleanTask(BaseTask):
    """自动清理不活跃用户任务（每日 3:00）。"""

    @property
    def task_id(self) -> str:
        return "auto_inactive_clean"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "auto_inactive_clean",
            "trigger": "cron",
            "hour": 3,
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            run_auto_inactive_clean(self.rm.bot, self.rm.config, self.rm.db)
        except Exception as e:
            logger.error(f"自动清理不活跃用户异常：{e}")
