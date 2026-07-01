"""
tasks/maintenance/night_mode_task.py - 夜间模式定时任务

按配置时间开启/关闭夜间模式，task_key 带日期后缀避免 UNIQUE 索引拦截当日重试。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from modules.night_mode import start_night_mode, end_night_mode
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort

logger = get_logger("tasks.maintenance.night_mode")

_CST = timezone(timedelta(hours=8))


class NightModeTask(BaseTask):
    """夜间模式开启/关闭任务。"""

    @property
    def task_id(self) -> str:
        return "night_mode"

    def schedule(self) -> List[Dict[str, Any]]:
        night_cfg = self.rm.config.get("NIGHT_MODE_CONFIG", {})
        if not night_cfg.get("enable", False):
            return []

        start_hour = night_cfg.get("start_hour", 23)
        end_hour = night_cfg.get("end_hour", 7)

        return [
            {
                "job_id": "night_mode_start",
                "trigger": "cron",
                "hour": start_hour,
                "minute": 0,
                "params": {"action": "start"},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 300,
                },
            },
            {
                "job_id": "night_mode_end",
                "trigger": "cron",
                "hour": end_hour,
                "minute": 0,
                "params": {"action": "end"},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 300,
                },
            },
        ]

    def execute(self, ctx: TaskContext) -> None:
        action = ctx.params.get("action", "start")
        today = ctx.now_str("%Y-%m-%d")
        task_key = f"night_mode_{action}_{today}"

        try:
            with TaskTransactionManager(task_key, self.rm.db, resources=None, min_interval_sec=3600) as tx:
                if not tx.claimed:
                    return

                gid = self.rm.config.get("GROUP_ID", 0)
                if not gid:
                    raise TaskAbort("GROUP_ID为0")

                if action == "start":
                    start_night_mode(self.rm.bot, gid, self.rm.config)
                    logger.info(f"🌙 夜间模式已开启：群 {gid}")
                else:
                    end_night_mode(self.rm.bot, gid, self.rm.config)
                    logger.info(f"☀️ 夜间模式已关闭：群 {gid}")
        except TaskAbort:
            pass
        except Exception as e:
            emoji = "🌙" if action == "start" else "☀️"
            logger.error(f"{emoji} 夜间模式{action}失败：{e}")
