"""
tasks/maintenance/flush_alert_summary_task.py - 告警汇总 Flush 任务

每 5 分钟对 5min 窗口内 count>1 的告警发送合并汇总，避免告警刷屏。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.flush_alert_summary")

_CST = timezone(timedelta(hours=8))


class FlushAlertSummaryTask(BaseTask):
    """告警汇总 Flush 任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "flush_alert_summary"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "flush_alert_summary",
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
            from core.alert_bot import flush_alert_summary
            count = flush_alert_summary()
            if count:
                logger.info(f"[告警汇总] 本次 flush 发送 {count} 条合并汇总")
        except Exception as e:
            logger.error(f"告警汇总 flush 异常：{e}")
            raise
