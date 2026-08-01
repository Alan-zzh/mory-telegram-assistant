"""
tasks/maintenance/scheduled_broadcast_task.py - 定点播报任务

根据 config 中的 SCHEDULED_BROADCASTS 动态注册定点播报，支持多群遍历。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.scheduled_broadcast import execute_scheduled_broadcast, get_broadcast_schedule
from tasks.base_task import BaseTask, TaskContext
from tasks.support.task_config import get_all_group_ids

logger = get_logger("tasks.maintenance.scheduled_broadcast")

_CST = timezone(timedelta(hours=8))


class ScheduledBroadcastTask(BaseTask):
    """定点播报任务（动态注册，每个播报一条调度条目）。"""

    @property
    def task_id(self) -> str:
        return "scheduled_broadcast"

    def schedule(self) -> List[Dict[str, Any]]:
        """从 config 读取播报时间表并返回调度配置列表。"""
        schedule_list = []
        for bc in get_broadcast_schedule(self.rm.config):
            bc_id = bc.get("id", "")
            if not bc_id:
                continue

            hour = bc.get("hour")
            minute = bc.get("minute")
            if hour is None or minute is None:
                continue

            entry = {
                "job_id": f"broadcast_{bc_id}",
                "trigger": "cron",
                "hour": hour,
                "minute": minute,
                "params": {
                    "chat_id": self.rm.config.get("GROUP_ID", 0),
                    "broadcast_id": bc_id,
                },
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 300,
                },
            }

            if bc.get("day_of_week") is not None:
                entry["day_of_week"] = bc["day_of_week"]
            if bc.get("day_of_month") is not None:
                entry["day"] = bc["day_of_month"]

            schedule_list.append(entry)
            logger.info(f"📢 注册定点播报: {bc_id} ({hour:02d}:{minute:02d})")

        return schedule_list

    def execute(self, ctx: TaskContext) -> None:
        broadcast_id = ctx.params.get("broadcast_id", "")
        chat_id = ctx.params.get("chat_id", 0)
        if not broadcast_id:
            raise ValueError("定点播报缺少 broadcast_id")

        try:
            group_ids = get_all_group_ids(self.rm.config)
            if not group_ids:
                raise ValueError(f"定点播报 {broadcast_id} 已启用但无管理群")

            failures = []
            for gid in group_ids:
                try:
                    execute_scheduled_broadcast(
                        self.rm.bot, gid, self.rm.config, self.rm.db,
                        target_broadcast_id=broadcast_id,
                        ai_engine=self.rm.ai,
                    )
                except Exception as e:
                    logger.warning(f"📢 定点播报 {broadcast_id} 发送到群 {gid} 失败: {e}")
                    failures.append((gid, e))
            if failures:
                failed_groups = ",".join(str(gid) for gid, _ in failures)
                raise RuntimeError(
                    f"定点播报 {broadcast_id} 有 {len(failures)} 个群失败: {failed_groups}"
                ) from failures[0][1]
        except Exception as e:
            logger.error(f"📢 定点播报执行失败 {broadcast_id}: {e}")
            raise
