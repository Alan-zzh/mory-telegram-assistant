"""
tasks/analytics/ab_weekly_task.py - A/B 测试周度分析任务

每周一凌晨 2:00 生成 A/B 测试周度报告。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.ab_weekly")

_CST = timezone(timedelta(hours=8))


class AbWeeklyTask(BaseTask):
    """A/B 测试周度分析任务（每周一凌晨 2:00）。"""

    @property
    def task_id(self) -> str:
        return "ab_weekly_report"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "ab_weekly_report",
            "trigger": "cron",
            "day_of_week": "mon",
            "hour": 2,
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from modules.ab_insights import run_weekly_ab_report_job
            ab_db = ctx.db.ab_test if hasattr(ctx.db, "ab_test") else ctx.db
            run_weekly_ab_report_job(ab_db, ctx.config)
        except Exception as e:
            logger.error(f"A/B 周度分析异常：{e}")
