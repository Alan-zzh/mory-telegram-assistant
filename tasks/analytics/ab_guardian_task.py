"""
tasks/analytics/ab_guardian_task.py - A/B 测试守护巡检任务

每 5 分钟运行一次 A/B 测试守护检查。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.ab_guardian")

_CST = timezone(timedelta(hours=8))


class AbGuardianTask(BaseTask):
    """A/B 测试守护巡检任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "ab_guardian"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "ab_guardian",
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
            from modules.ab_guardian import run_ab_guardian_job
            ab_db = ctx.db.ab_test if hasattr(ctx.db, "ab_test") else ctx.db
            run_ab_guardian_job(ctx.bot, ab_db, ctx.config)
        except Exception as e:
            logger.error(f"A/B 守护巡检异常：{e}")
            raise
