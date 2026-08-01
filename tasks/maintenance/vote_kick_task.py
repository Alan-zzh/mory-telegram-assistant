"""
tasks/maintenance/vote_kick_task.py - 投票踢人过期检查任务

每 5 分钟检查并清理过期投票。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.vote_kick import check_expired_votes
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.vote_kick")

_CST = timezone(timedelta(hours=8))


class VoteKickTask(BaseTask):
    """投票踢人过期检查任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "vote_kick"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "vote_kick_check",
            "trigger": "cron",
            "minute": "*/5",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            check_expired_votes(self.rm.bot, self.rm.config, self.rm.db)
        except Exception as e:
            logger.error(f"投票踢人过期检查异常：{e}")
            raise
