"""
tasks/maintenance/check_db_migration_task.py - DB 迁移时机指标监控任务

每小时检查一次 DB 迁移触发指标，超阈值时仅告警，不自动迁移。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.check_db_migration")

_CST = timezone(timedelta(hours=8))


class CheckDbMigrationTask(BaseTask):
    """DB 迁移时机指标监控任务（每小时）。"""

    @property
    def task_id(self) -> str:
        return "check_db_migration"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "check_db_migration",
            "trigger": "interval",
            "hours": 1,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            from core.db_migration_monitor import check_migration_indicators
            indicators = check_migration_indicators(ctx.db)
            exceeded = [k for k, v in indicators.items() if v.get("exceeded")]
            if exceeded:
                logger.warning(f"[DB迁移监控] 超阈值指标: {exceeded}")
        except Exception as e:
            logger.error(f"DB迁移指标监控异常：{e}")
            raise
