"""
tasks/maintenance/check_expired_redpackets_task.py - 红包过期检查任务

每小时检查一次过期红包，退回未领取积分。
"""

from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.check_expired_redpackets")


class CheckExpiredRedpacketsTask(BaseTask):
    """检查过期红包并退回未领取积分（每小时一次）。"""

    @property
    def task_id(self) -> str:
        return "check_expired_redpackets"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "check_expired_redpackets",
            "trigger": "cron",
            "minute": 35,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from modules.redpacket import check_expired_redpackets
            check_expired_redpackets(ctx.bot, ctx.config, ctx.db)
            logger.info("✅ 红包过期检查完成")
        except Exception as e:
            logger.error(f"红包过期检查失败：{e}")
            raise
