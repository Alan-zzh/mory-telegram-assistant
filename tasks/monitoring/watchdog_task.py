"""
tasks/monitoring/watchdog_task.py - 看门狗任务

检测心跳超时并触发自动重启，由 systemd Restart=always 拉起。
"""

import os
import threading
import time
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.monitoring.heartbeat_task import check_heartbeat
from tasks.support.fault_reporter import get_fault_reporter

logger = get_logger("tasks.monitoring.watchdog")

_DEFAULT_TIMEOUT_SEC = 900


def _watchdog_loop(rm, timeout_sec: int):
    """看门狗后台循环。"""
    while True:
        time.sleep(60)
        if check_heartbeat(timeout_sec):
            try:
                get_fault_reporter().report(
                    "心跳超时",
                    f"心跳超时 {timeout_sec}s，触发自动重启",
                    "🚨"
                )
            except Exception as e:
                logger.warning(f"心跳超时告警上报失败: {e}")
            logger.critical(f"心跳超时 {timeout_sec}s，触发自动重启")
            time.sleep(5)
            os._exit(42)


class WatchdogTask(BaseTask):
    """看门狗任务（不进入 APScheduler，启动时单独启动后台线程）。"""

    @property
    def task_id(self) -> str:
        return "watchdog"

    def schedule(self) -> List[Dict[str, Any]]:
        return []

    def execute(self, ctx: TaskContext) -> None:
        """看门狗不进入 APScheduler，execute 为空实现。"""
        pass

    def start(self, timeout_sec: int = _DEFAULT_TIMEOUT_SEC):
        """启动看门狗后台线程。"""
        from tasks.monitoring.heartbeat_task import update_heartbeat
        update_heartbeat()
        t = threading.Thread(target=_watchdog_loop, args=(self.rm, timeout_sec), daemon=True)
        t.start()
        logger.info(f"watchdog 启动：超时阈值={timeout_sec}s")
