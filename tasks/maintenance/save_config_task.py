"""
tasks/maintenance/save_config_task.py - 配置保存任务

仅当 CURRENT_MODEL_INDEX 发生变化时才持久化配置，避免频繁写盘。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.save_config")

_CST = timezone(timedelta(hours=8))

# 模块级状态，记录上次保存的模型索引
_last_saved_model_idx = None


class SaveConfigTask(BaseTask):
    """配置保存任务（按分钟检查，仅变化时触发）。"""

    @property
    def task_id(self) -> str:
        return "save_config"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "save_config",
            "trigger": "cron",
            "minute": 30,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        global _last_saved_model_idx
        try:
            with self.rm.locked('config'):
                current_idx = self.rm.config.get("CURRENT_MODEL_INDEX", 0)
            if _last_saved_model_idx is None or _last_saved_model_idx != current_idx:
                save_fn = self.rm.save_config_fn
                if save_fn:
                    with self.rm.locked('config'):
                        save_fn()
                    _last_saved_model_idx = current_idx
                    logger.info(f"💾 配置已保存：CURRENT_MODEL_INDEX={current_idx}")
        except Exception as e:
            logger.error(f"配置保存失败：{e}")
