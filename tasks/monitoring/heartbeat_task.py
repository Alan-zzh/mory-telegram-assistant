"""
tasks/monitoring/heartbeat_task.py - 心跳更新任务

每 5 分钟更新一次心跳时间戳，供看门狗检测使用。
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
    """更新心跳时间戳。"""
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
    """心跳更新任务（每 5 分钟）。"""

    @property
    def task_id(self) -> str:
        return "heartbeat"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "heartbeat",
            "trigger": "cron",
            "minute": "*/5",
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 120,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        update_heartbeat()
        logger.debug("💓 心跳更新")
