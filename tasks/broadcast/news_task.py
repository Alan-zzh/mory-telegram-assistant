"""
tasks/broadcast/news_task.py - 新闻播报任务

负责早/午/晚三个时段的新闻播报，包含新闻源选择、去重、富文本排版和发送。
"""

from typing import Any, Dict, List

from core.broadcast_formatter import build_rich_greeting_html
from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import execute_news_task
from tasks.support.task_config import get_news_time

logger = get_logger("tasks.broadcast.news")


class NewsTask(BaseTask):
    """新闻播报任务：早/午/晚三次播报。"""

    @property
    def task_id(self) -> str:
        return "news_broadcast"

    def schedule(self) -> List[Dict[str, Any]]:
        periods = ["morning", "afternoon", "evening"]
        time_desc_map = {
            "morning": "早间",
            "afternoon": "午间",
            "evening": "晚间",
        }
        schedule_list = []
        for period in periods:
            hour, minute = get_news_time(self.rm.config, period)
            schedule_list.append({
                "job_id": f"news_{period}",
                "trigger": "cron",
                "hour": hour,
                "minute": minute,
                "params": {"period": period, "time_desc": time_desc_map[period]},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 60,
                },
            })
        return schedule_list

    def execute(self, ctx: TaskContext) -> None:
        period = ctx.params.get("period", "morning")
        time_desc = ctx.params.get("time_desc", "早间")
        task_name = f"news_{period}"
        logger.info(f"📰 触发 {time_desc} 新闻播报")
        execute_news_task(ctx.rm, task_name, time_desc)
