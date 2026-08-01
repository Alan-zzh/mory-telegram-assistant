"""
tasks/maintenance/clean_relay_sessions_task.py - 过期中继会话清理任务

每小时清理超过 24 小时的中继会话记录。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.clean_relay_sessions")

_CST = timezone(timedelta(hours=8))


class CleanRelaySessionsTask(BaseTask):
    """过期中继会话清理任务（每小时）。"""

    @property
    def task_id(self) -> str:
        return "clean_relay_sessions"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "clean_relay_sessions",
            "trigger": "interval",
            "seconds": 3600,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            db = self.rm.db
            deleted = db.clean_expired(max_age=86400)
            if deleted > 0:
                logger.info(f"🧹 中继会话清理：删除{deleted}条过期记录")
        except Exception as e:
            logger.warning(f"中继会话清理失败：{e}")
            raise
