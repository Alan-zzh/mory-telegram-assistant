"""每周轻互动任务（默认关闭，不编造 Mory 的生活或隐私）。"""

import random
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort, retry_task, send_and_track
from tasks.support.message_templates import MessageTemplates

logger = get_logger("tasks.interaction.leak")

_CST = timezone(timedelta(hours=8))


def _generate_leak_text(rm) -> str:
    """从已审阅的非事实问题池取值，不让模型编造生活信息。"""
    return MessageTemplates.get_weekly_interaction_question()


class LeakTask(BaseTask):
    """每周轻互动（默认关闭）。"""

    @property
    def task_id(self) -> str:
        return "leak"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "leak",
            "trigger": "cron",
            "day_of_week": "wed",
            "hour": 0,
            "minute": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            cfg = self.rm.config.get("LEAK_CONFIG", {})
            if not isinstance(cfg, dict) or not cfg.get("enabled", False):
                logger.info("每周轻互动未开启，跳过")
                return
            with TaskTransactionManager("leak", self.rm.db, resources=None,
                                        min_interval_sec=86400) as tx:
                if not tx.claimed:
                    return

                now = datetime.now(_CST)
                current_week = now.isocalendar()[1]
                gid = self.rm.config.get("GROUP_ID", 0)
                last_leak_week = self.rm.config.get("_LAST_LEAK_WEEK", -1)

                if gid == 0 or current_week == last_leak_week or now.weekday() < 2:
                    raise TaskAbort("条件不满足", expected=True)

                leak = _generate_leak_text(self.rm)
                if not leak:
                    raise TaskAbort("AI 生成失败")

                leak_prefix = MessageTemplates.get_leak_prefix()
                sent = send_and_track(self.rm, gid, f"{leak_prefix}{leak}")
                if not sent:
                    raise TaskAbort("发送失败")

                self.rm.config["_LAST_LEAK_WEEK"] = current_week
                save_fn = self.rm.save_config_fn
                if save_fn:
                    save_fn()
                logger.info(f"每周轻互动触发(周{current_week})：{leak[:30]}")
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"每周轻互动失败：{e}")
            retry_task(self.rm, self.run, "leak")
            raise
