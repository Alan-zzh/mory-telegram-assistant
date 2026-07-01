"""
tasks/analytics/prometheus_metrics_task.py - Prometheus 指标采集任务

每 5 分钟刷新 Prometheus 指标，并刷盘 LLMCostGuard 累计成本。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.prometheus_metrics")

_CST = timezone(timedelta(hours=8))


class PrometheusMetricsTask(BaseTask):
    """Prometheus 指标采集任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "update_prometheus_metrics"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "update_prometheus_metrics",
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
            from core.metrics import update_metrics
            update_metrics()
        except Exception as e:
            logger.error(f"Prometheus 指标采集异常：{e}")

        # v5.31.2 修复：LLMCostGuard 刷盘，避免累计成本数据丢失
        try:
            from core.llm_cost_guard import get_guard
            guard = get_guard()
            if guard and guard.enabled:
                raw_conn = getattr(ctx.db, '_real_conn', None) or getattr(ctx.db, 'conn', None)
                if raw_conn:
                    guard.flush_to_db(raw_conn)
        except Exception as _flush_err:
            logger.debug(f"LLMCostGuard flush_to_db 跳过: {_flush_err}")
