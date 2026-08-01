"""
tasks/monitoring/heartbeat_task.py - 心跳更新任务

每 1 分钟更新一次心跳时间戳，供看门狗 + /api/health 检测使用。
心跳同时写入内存（供同进程看门狗快速读取）和 system_states 表（供 Dashboard
跨进程健康检查读取，key='last_heartbeat'）。
"""

import time
import threading
from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.monitoring.heartbeat")

_CST = timezone(timedelta(hours=8))

_LAST_HEARTBEAT = 0
_HEARTBEAT_LOCK = threading.Lock()


def update_heartbeat():
    """更新内存心跳时间戳（不写数据库，仅同进程使用）。"""
    global _LAST_HEARTBEAT
    with _HEARTBEAT_LOCK:
        _LAST_HEARTBEAT = int(time.time())


def check_heartbeat(timeout_sec: int = 900) -> bool:
    """检查心跳是否超时，True 表示超时。"""
    with _HEARTBEAT_LOCK:
        return (int(time.time()) - _LAST_HEARTBEAT) > timeout_sec


def get_last_heartbeat() -> int:
    with _HEARTBEAT_LOCK:
        return _LAST_HEARTBEAT


class HeartbeatTask(BaseTask):
    """心跳更新任务（每 1 分钟）。

    写入两个位置：
      1. 模块级 _LAST_HEARTBEAT 内存变量（供同进程 watchdog 快速读取）
      2. system_states 表 last_heartbeat 键（供 Dashboard /api/health 跨进程读取）
    """

    @property
    def task_id(self) -> str:
        return "heartbeat"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "heartbeat",
            "trigger": "cron",
            "minute": "*/1",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 120,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        update_heartbeat()
        # 同步写入数据库 system_states 表，供 Dashboard /api/health 跨进程读取
        try:
            ctx.db.set_system_state("last_heartbeat", str(int(time.time())))
        except Exception as e:
            logger.error(f"心跳写入数据库失败: {e}")
            raise
        logger.debug("💓 心跳更新")
