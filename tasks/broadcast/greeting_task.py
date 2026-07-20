"""
tasks/broadcast/greeting_task.py - 早/午/晚安问候任务

负责按配置时间向管理群发送早安、午安、晚安问候，支持链式互删。
"""

import random
from typing import Any, Dict, List

from core.broadcast_formatter import build_rich_greeting_html, build_rich_greeting_card_message
from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import send_greeting, TaskAbort, retry_task
from tasks.support.message_templates import MessageTemplates
from tasks.support.task_config import get_greeting_time, is_greeting_enabled, get_all_group_ids

logger = get_logger("tasks.broadcast.greeting")


class GreetingTask(BaseTask):
    """早/午/晚安问候任务。"""

    @property
    def task_id(self) -> str:
        return "greeting"

    def schedule(self) -> List[Dict[str, Any]]:
        periods = ["morning", "afternoon", "evening"]
        schedule_list = []
        for period in periods:
            hour, minute = get_greeting_time(self.rm.config, period)
            schedule_list.append({
                "job_id": f"greeting_{period}",
                "trigger": "cron",
                "hour": hour,
                "minute": minute,
                "params": {"period": period},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 60,
                },
            })
        return schedule_list

    def execute(self, ctx: TaskContext) -> None:
        period = ctx.params.get("period", "morning")
        if not is_greeting_enabled(self.rm.config, period):
            logger.info(f"[Codex] {period} 问候未开启，跳过")
            return

        try:
            today = ctx.now_str("%Y-%m-%d")
            task_key = f"greeting_{period}_{today}"
            with TaskTransactionManager(task_key, self.rm.db, resources=None, min_interval_sec=7200) as tx:
                if not tx.claimed:
                    return

                group_ids = get_all_group_ids(self.rm.config)
                if not group_ids:
                    logger.warning(f"🌅 {period} 问候无管理群，跳过")
                    raise TaskAbort("无管理群")

                seed = random.randint(100000, 999999)
                msg = self.rm.ai.ask(
                    "早安" if period == "morning" else ("午安" if period == "afternoon" else "晚安"),
                    mode=period,
                    seed=seed,
                )
                if not msg:
                    msg = MessageTemplates.get_fallback_greeting(period)
                    logger.info(f"🌅 {period} 问候使用话术池兜底")

                # [v5.32] 移除强制单段，保留 AI 生成的多段结构，放宽到 400 字
                msg = msg.strip()[:400]
                suffix = MessageTemplates.get_dynamic_suffix(period) if MessageTemplates.needs_suffix(msg) else ""
                # [v5.32] 同时构建 HTML 版本和 Rich Message 版本
                rich_html = build_rich_greeting_html(period, msg, suffix.strip())
                rich_message_html = build_rich_greeting_card_message(period, msg, suffix.strip())

                sent_any = False
                for gid in group_ids:
                    try:
                        sent = send_greeting(
                            self.rm, gid, rich_html, f"greeting_{period}",
                            rich_text=rich_message_html,
                        )
                        if sent:
                            sent_any = True
                            logger.info(f"🌅 {period} 问候已发送到群 {gid}：{msg}")
                    except Exception as e:
                        logger.warning(f"🌅 {period} 问候发送到群 {gid} 失败: {e}")

                if not sent_any:
                    raise TaskAbort(f"{period} 问候全部群发送失败")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"{period} 问候失败：{e}")
            retry_task(self.rm, lambda rm: self.run({"period": period}), f"greeting_{period}")
