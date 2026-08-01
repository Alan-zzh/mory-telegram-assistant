"""
tasks/maintenance/ttl_cleanup_task.py - TTL 历史数据清理任务

每小时清理过期记录并释放内存字典缓存。
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.ttl_cleanup")

_CST = timezone(timedelta(hours=8))


class TtlCleanupTask(BaseTask):
    """TTL 历史数据清理任务（每小时）。"""

    @property
    def task_id(self) -> str:
        return "ttl_cleanup"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "ttl_cleanup",
            "trigger": "cron",
            "minute": 20,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        failures = []
        try:
            ts = int(time.time())
            cutoff = ts - 7 * 86400
            deleted_track, deleted_spam, deleted_puzzle = self.rm.db.cleanup_old_records(cutoff)
            if deleted_track or deleted_spam or deleted_puzzle:
                logger.info(f"🧹 TTL清理: 追踪{deleted_track}条/垃圾{deleted_spam}条/谜题{deleted_puzzle}条")
            self.rm.db.cleanup_old_task_log()
            # 【P2-1】清理 task_execution_history 超过 90 天的历史记录
            try:
                self.rm.db.cleanup_old_history(days=90)
            except Exception as e:
                logger.error(f"task_execution_history 清理失败: {e}")
                failures.append(e)
        except Exception as e:
            logger.error(f"TTL清理失败：{e}")
            failures.append(e)

        try:
            from core.message_dispatcher import _cleanup_conv_tracker, _cleanup_radar_cooldown
            _cleanup_conv_tracker()
            _cleanup_radar_cooldown()
        except Exception as e:
            logger.error(f"内存字典清理失败：{e}")
            failures.append(e)

        try:
            from modules.antiflood import cleanup_flood_cache
            cleanup_flood_cache(max_age=300)
        except Exception as e:
            logger.error(f"刷屏缓存清理失败：{e}")
            failures.append(e)

        try:
            from modules.edit_detector import cleanup_old_snapshots
            cleanup_old_snapshots(max_age=86400)
        except Exception as e:
            logger.error(f"编辑快照清理失败：{e}")
            failures.append(e)

        if failures:
            raise ExceptionGroup("TTL 清理任务失败", failures)
