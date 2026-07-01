"""
tasks/analytics/faq_distill_task.py - FAQ 蒸馏任务

从最近 7 天的用户问题中提取高频问题，生成 FAQ 候选并通知管理员审核。
"""

from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort
from tasks.support.fault_reporter import get_fault_reporter

logger = get_logger("tasks.analytics.faq_distill")


class FaqDistillTask(BaseTask):
    """FAQ 蒸馏任务（每日一次，间隔从配置读取，默认 86400 秒）。"""

    @property
    def task_id(self) -> str:
        return "faq_distill"

    def schedule(self) -> List[Dict[str, Any]]:
        interval = self.rm.config.get("FAQ_DISTILL_INTERVAL", 86400)
        return [{
            "job_id": "faq_distill",
            "trigger": "interval",
            "seconds": interval,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            if not ctx.rm.config.get("FAQ_TRACKING_ENABLED", False):
                return

            min_frequency = ctx.rm.config.get("FAQ_MIN_FREQUENCY", 3)

            with TaskTransactionManager("faq_distill", ctx.rm.db, min_interval_sec=86400) as tx:
                if not tx.claimed:
                    return

                count = ctx.rm.db.distill_candidates(min_frequency=min_frequency, days=7)

                if count > 0:
                    logger.info(f"📋 FAQ蒸馏完成：发现 {count} 个新高频问题候选")
                    get_fault_reporter().report(
                        "FAQ蒸馏",
                        f"发现 {count} 个新高频问题候选，请到Dashboard审核",
                        "📋",
                    )
                else:
                    logger.info("📋 FAQ蒸馏完成：无新高频问题候选")
                    raise TaskAbort("无新高频问题候选")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"FAQ蒸馏失败：{e}")
            get_fault_reporter().report("FAQ蒸馏失败", str(e)[:200], "⚠️")
