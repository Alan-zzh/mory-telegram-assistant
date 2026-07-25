"""每分钟物理清理超过 30 分钟的短期业务会话原文。"""

from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.conversation_context_cleanup")


class ConversationContextCleanupTask(BaseTask):
    """保证短期上下文 TTL 不依赖后续用户写入。"""

    @property
    def task_id(self) -> str:
        return "conversation_context_cleanup"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": self.task_id,
            "trigger": "cron",
            "minute": "*",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        cleanup = getattr(self.rm.db, "cleanup_expired_business_context", None)
        if not callable(cleanup):
            logger.warning("短期业务上下文清理接口不可用")
            return
        deleted = cleanup()
        if deleted:
            logger.info("已物理清理 %s 条过期短期业务上下文", deleted)
