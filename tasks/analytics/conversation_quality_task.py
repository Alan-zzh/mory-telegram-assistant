"""
tasks/analytics/conversation_quality_task.py - 内容质量评估任务

每日凌晨 3:00 抽样评估昨日对话，LLM-as-a-Judge 打分。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.conversation_quality")

_CST = timezone(timedelta(hours=8))


class ConversationQualityTask(BaseTask):
    """内容质量评估任务（每日凌晨 3:00）。"""

    @property
    def task_id(self) -> str:
        return "quality_eval"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "quality_eval",
            "trigger": "cron",
            "hour": 3,
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
            from core.quality_evaluator import QualityEvaluator
            evaluator = QualityEvaluator(ai=ctx.ai, db=ctx.db, config=ctx.config)
            result = evaluator.run_daily_evaluation()
            logger.info(f"📊 内容质量评估任务完成: {result}")
        except Exception as e:
            logger.error(f"内容质量评估任务失败: {e}")
            raise

        # [Agent G] 风格样本蒸馏链路：默认关闭，开启时从高分评估对话中提取 pending 样本
        if (ctx.config or {}).get("REPLY_EVOLUTION_DISTILL_ENABLED", False):
            try:
                from tasks.analytics.reply_evolution_distill import distill_reply_style_samples
                distill_result = distill_reply_style_samples(ctx.db, config=ctx.config)
                logger.info(f"🍼 风格样本蒸馏结果: {distill_result}")
            except Exception as e:
                logger.error(f"风格样本蒸馏失败: {e}")

        # [Agent G] 风格样本蒸馏链路：默认关闭，开启时从高分评估对话中提取 pending 样本
        if (ctx.config or {}).get("REPLY_EVOLUTION_DISTILL_ENABLED", False):
            try:
                from tasks.analytics.reply_evolution_distill import distill_reply_style_samples
                distill_result = distill_reply_style_samples(ctx.db, config=ctx.config)
                logger.info(f"🍼 风格样本蒸馏结果: {distill_result}")
            except Exception as e:
                logger.error(f"风格样本蒸馏失败: {e}")
