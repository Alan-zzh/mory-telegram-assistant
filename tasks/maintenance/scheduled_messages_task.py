"""
tasks/maintenance/scheduled_messages_task.py - 定时消息发送任务

每分钟检查并发送已到时间的定时消息。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.scheduled_msg import run_scheduled_messages
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.scheduled_messages")

_CST = timezone(timedelta(hours=8))


class ScheduledMessagesTask(BaseTask):
    """定时消息发送任务（每分钟检查）。"""

    @property
    def task_id(self) -> str:
        return "scheduled_messages"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "scheduled_messages",
            "trigger": "cron",
            "minute": "*",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            run_scheduled_messages(self.rm.bot, self.rm.config, self.rm.db)
        except Exception as e:
            logger.error(f"定时消息发送异常：{e}")
