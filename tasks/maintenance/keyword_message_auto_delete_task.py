"""关键词消息延迟删除的重启恢复任务。"""

from typing import Any, Dict, List

from core.logging_util import get_logger
from modules.keyword_auto_delete import (
    get_keyword_auto_delete_config,
    run_due_keyword_message_deletes,
)
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.keyword_message_auto_delete")


class KeywordMessageAutoDeleteTask(BaseTask):
    """每分钟补偿处理到期待删消息；准点路径由进程内定时器负责。"""

    @property
    def task_id(self) -> str:
        return "keyword_message_auto_delete"

    def schedule(self) -> List[Dict[str, Any]]:
        if not get_keyword_auto_delete_config(self.rm.config)["enabled"]:
            return []
        return [{
            "job_id": "keyword_message_auto_delete",
            "trigger": "interval",
            "minutes": 1,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 120,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        counts = run_due_keyword_message_deletes(ctx.bot, ctx.db, ctx.config)
        if counts["found"]:
            logger.info("关键词延迟删恢复任务回执: %s", counts)
        if counts["retry"] or counts["failed"]:
            raise RuntimeError(f"关键词延迟删存在未闭环消息: {counts}")
