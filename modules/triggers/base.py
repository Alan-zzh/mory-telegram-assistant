# 触发器基类（v5.19.0）
"""[TRAE SOLO CN] v5.19.0 场景化触发器基类。

所有触发器继承 TriggerBase，实现 should_fire / execute。
注册到 APScheduler，默认每 5 分钟巡检一次。
统一异常吞掉 + TaskTransactionManager 幂等。
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class TriggerBase:
    """[TRAE SOLO CN] v5.19.0 触发器基类。"""

    job_id: str = ""
    trigger_type: str = "cron"  # cron / interval / event
    enabled_config_key: str = ""  # 如 'COLD_GROUP_TRIGGER_ENABLED'
    interval_minutes: int = 5  # 巡检间隔（分钟）

    def __init__(self):
        self.rm: Any = None  # ResourceManager

    def should_fire(self, rm) -> bool:
        """子类实现：判断是否满足触发条件。"""
        raise NotImplementedError

    def execute(self, rm) -> None:
        """子类实现：执行触发动作。"""
        raise NotImplementedError

    def register(self, scheduler, rm):
        """注册到 APScheduler（事件驱动触发器不注册，由调用方手动触发）。"""
        if self.trigger_type == "event":
            return  # 事件驱动，不轮询
        if not rm.config.get(self.enabled_config_key, False):
            logger.info(f"触发器 {self.job_id} 未启用，跳过注册")
            return
        self.rm = rm
        try:
            scheduler.add_job(
                self._run, id=self.job_id, max_instances=1, coalesce=True,
                trigger="interval", minutes=self.interval_minutes,
                misfire_grace_time=60, args=[rm],
            )
            logger.info(f"✅ 触发器已注册: {self.job_id} (间隔 {self.interval_minutes} 分钟)")
        except Exception as e:
            logger.warning(f"触发器 {self.job_id} 注册失败: {e}")

    def _run(self, rm):
        """统一执行入口：异常吞掉 + 幂等检查。"""
        try:
            if not rm.config.get(self.enabled_config_key, False):
                return
            if self.should_fire(rm):
                logger.info(f"🔥 触发器命中: {self.job_id}")
                self.execute(rm)
        except Exception as e:
            logger.warning(f"触发器 {self.job_id} 执行异常: {e}")
