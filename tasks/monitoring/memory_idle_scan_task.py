"""
tasks/monitoring/memory_idle_scan_task.py - 混合记忆静默期扫描任务

每 5 分钟扫描已静默 >30min 的用户，触发异步记忆摘要。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.monitoring.memory_idle_scan")

_CST = timezone(timedelta(hours=8))


class MemoryIdleScanTask(BaseTask):
    """混合记忆静默期扫描任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "memory_idle_scan"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "memory_idle_scan",
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
            from core.memory_summarizer import scan_idle_users
            triggered = scan_idle_users(ctx.db, max_check=50)
            if triggered:
                logger.info(f"[MEMORY] 静默扫描触发 {triggered} 个用户的记忆摘要")
        except Exception as e:
            logger.debug(f"记忆静默扫描异常：{e}")
