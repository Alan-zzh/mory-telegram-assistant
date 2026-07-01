"""
tasks/analytics/lifecycle_sync_task.py - 用户生命周期阶段同步

每日凌晨 2:00 同步用户生命周期阶段标签到数据库。
"""

from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.lifecycle_sync")


class LifecycleSyncTask(BaseTask):
    """用户生命周期阶段标签同步任务（每日凌晨 2:00）。"""

    @property
    def task_id(self) -> str:
        return "sync_user_lifecycle_buckets"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "sync_user_lifecycle_buckets",
            "trigger": "cron",
            "hour": 2,
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
            from core.user_lifecycle import UserLifecycleManager
            mgr = UserLifecycleManager(ctx.rm.db)
            dist = mgr.sync_lifecycle_buckets()
            logger.info(f"用户生命周期同步完成: {dist}")
        except Exception as e:
            logger.error(f"用户生命周期同步失败：{e}")
