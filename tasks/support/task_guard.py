"""
tasks/support/task_guard.py - 任务执行守卫

将 auto_tasks.py 中内嵌的 _TaskGuard 提取为独立模块，用于并发异常检测与预警。
"""

import threading
import time
from typing import Optional

from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from tasks.support.fault_reporter import get_fault_reporter

logger = get_logger("tasks.task_guard")


class TaskGuard:
    """
    任务执行守卫 - 并发异常检测与预警。

    核心能力：
      1. 记录每次任务调用时间戳，同一任务 5 分钟内被调用 ≥2 次 → 告警管理员
      2. 记录抢占失败原因，连续失败 ≥3 次 → 告警管理员
      3. 健康检查时审计数据库 task_log，只检测异常重复记录
    """

    _ALERT_WINDOW_SEC = 300
    _ALERT_THRESHOLD = 2
    _CLAIM_FAIL_THRESHOLD = 3

    _instance: Optional["TaskGuard"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._call_history: dict = {}
        self._claim_fail_count: dict = {}
        self._alerted: set = set()
        self._lock = threading.Lock()
        self._rm: Optional[ResourceManager] = None
        self._initialized = True

    def bind(self, rm: ResourceManager):
        self._rm = rm

    def record_call(self, task_name: str):
        now = int(time.time())
        with self._lock:
            if task_name not in self._call_history:
                self._call_history[task_name] = []
            self._call_history[task_name].append(now)
            self._call_history[task_name] = [
                t for t in self._call_history[task_name]
                if now - t < self._ALERT_WINDOW_SEC
            ]
            count = len(self._call_history[task_name])
            if count >= self._ALERT_THRESHOLD:
                alert_key = f"{task_name}_{now // 60}"
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    logger.warning(
                        f"🚨 [TaskGuard] {task_name} 在{self._ALERT_WINDOW_SEC}秒内被调用{count}次！疑似并发异常"
                    )
                    from datetime import datetime, timezone, timedelta
                    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    msg = (
                        f"🚨 <b>并发异常预警</b>\n"
                        f"📋 任务：{task_name}\n"
                        f"⚡ {self._ALERT_WINDOW_SEC}秒内被调用{count}次\n"
                        f"🕐 时间：{ts}\n"
                        f"💡 可能存在并发重复执行，请检查日志"
                    )
                    self._send_alert(msg)

            # [P2-NEW-08] 清理过大的 _alerted 集合，避免内存泄漏
            # 时间分桶的 key（如 "taskname_1234567"）天然按字符串有序
            if len(self._alerted) > 10000:
                sorted_keys = sorted(self._alerted)
                self._alerted = set(sorted_keys[-5000:])
                logger.info(f"TaskGuard _alerted 集合已清理，保留最近 5000 条")

    def record_intercept(self, task_name: str, reason: str):
        """记录正常拦截（内存锁/数据库锁），不触发告警。"""
        with self._lock:
            logger.info(f"🛡️ [TaskGuard] {task_name} 正常拦截（{reason}）")

    def record_claim_fail(self, task_name: str, reason: str):
        now = int(time.time())
        with self._lock:
            self._claim_fail_count[task_name] = self._claim_fail_count.get(task_name, 0) + 1
            count = self._claim_fail_count[task_name]
            if count >= self._CLAIM_FAIL_THRESHOLD:
                alert_key = f"claim_{task_name}_{now // 3600}"
                if alert_key not in self._alerted:
                    self._alerted.add(alert_key)
                    logger.warning(f"🚨 [TaskGuard] {task_name} 连续{count}次抢占失败（{reason}）")
                    from datetime import datetime, timezone, timedelta
                    ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                    msg = (
                        f"⚠️ <b>任务抢占异常</b>\n"
                        f"📋 任务：{task_name}\n"
                        f"🔒 连续{count}次抢占失败\n"
                        f"📌 原因：{reason}\n"
                        f"🕐 时间：{ts}\n"
                        f"💡 可能是锁未正确释放，请检查数据库task_log"
                    )
                    self._send_alert(msg)
                self._claim_fail_count[task_name] = 0

    def record_claim_ok(self, task_name: str):
        with self._lock:
            self._claim_fail_count.pop(task_name, None)

    def audit_task_log(self, db) -> list:
        anomalies = []
        try:
            from datetime import datetime, timezone, timedelta
            today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
            from core.helpers import db_lock_from_db
            with db_lock_from_db(db):
                rows = db.conn.execute(
                    "SELECT task_key, COUNT(*) as cnt FROM task_log WHERE exec_date=? GROUP BY task_key HAVING cnt > 1",
                    (today,)
                ).fetchall()
            for task_key, cnt in rows:
                anomalies.append(f"• {task_key}：今日{cnt}条记录（正常应1条）")
                logger.warning(f"🚨 [TaskGuard] 数据库异常：{task_key} 今日有{cnt}条task_log记录")
        except Exception as e:
            logger.error(f"⚠️ [TaskGuard] 审计task_log失败: {e}")
            raise

        return anomalies

    def _send_alert(self, msg: str):
        try:
            get_fault_reporter().report("任务并发异常", msg, "🚨")
        except Exception as e:
            logger.warning(f"[TaskGuard] 告警发送失败: {e}")


_task_guard = TaskGuard()


def get_task_guard() -> TaskGuard:
    return _task_guard
