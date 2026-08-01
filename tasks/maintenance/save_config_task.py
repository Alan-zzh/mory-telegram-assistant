"""
tasks/maintenance/save_config_task.py - 配置保存任务

仅当 CURRENT_MODEL_INDEX 或 BLACKLISTED_MODELS 发生变化时才持久化配置，避免频繁写盘。
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
    """配置保存任务（按分钟检查，仅变化时触发）。

    触发条件：
    1. CURRENT_MODEL_INDEX 变化（模型切换）
    2. AI 引擎黑名单脏标记为 True（模型被拉黑或恢复）
    """

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
            # 检测黑名单脏标记（拉黑/恢复过模型时置 True）
            blacklist_dirty = False
            ai = self.rm.ai
            if ai is not None and hasattr(ai, 'consume_blacklist_dirty'):
                blacklist_dirty = ai.consume_blacklist_dirty()
            need_save = (
                _last_saved_model_idx is None
                or _last_saved_model_idx != current_idx
                or blacklist_dirty
            )
            if need_save:
                save_fn = self.rm.save_config_fn
                if save_fn:
                    idx_changed = (
                        _last_saved_model_idx is None
                        or _last_saved_model_idx != current_idx
                    )
                    with self.rm.locked('config'):
                        save_fn()
                    _last_saved_model_idx = current_idx
                    reason = []
                    if idx_changed:
                        reason.append(f"CURRENT_MODEL_INDEX={current_idx}")
                    if blacklist_dirty:
                        reason.append("BLACKLISTED_MODELS变更")
                    logger.info(f"💾 配置已保存：{', '.join(reason)}")
        except Exception as e:
            logger.error(f"配置保存失败：{e}")
            raise
