"""
tasks/maintenance/reminders_task.py - 到期提醒检查任务

每分钟检查并触发到期提醒。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.reminder import check_reminders
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.reminders")

_CST = timezone(timedelta(hours=8))


class RemindersTask(BaseTask):
    """到期提醒检查任务（每分钟）。"""

    @property
    def task_id(self) -> str:
        return "reminders"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "check_reminders",
            "trigger": "interval",
            "minutes": 1,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            check_reminders(self.rm.bot, self.rm.config, self.rm.db)
        except Exception as e:
            logger.error(f"检查提醒异常：{e}")
