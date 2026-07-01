"""
tasks/support/fault_reporter.py - 统一故障通知中心

将 auto_tasks.py 中内嵌的 _FaultReporter 提取为独立模块，供所有任务模块共享。
"""

import json
import os
import threading
import time
from typing import Optional

from core.logging_util import get_logger
from core.resource_manager import ResourceManager

logger = get_logger("tasks.fault_reporter")


class FaultReporter:
    """
    统一故障上报入口，自动 Telegram 通知 + 本地兜底。

    严重度分级：
      - 🚨 P0(瘫痪)
      - ⚠️ P1(降级)
      - 📋 P2(轻微)

    防刷机制：同类故障 5 分钟内不重复通知（持久化到文件，重启不丢失）。
    兜底机制：Telegram 通知失败时写入本地 fault_alerts.log，下次成功时补发。
    """

    _DEDUP_SEC = 300
    _ALERT_FILE = "fault_alerts.log"
    _DEDUP_STATE_FILE = "fault_dedup_state.json"
    _MAX_PENDING = 50

    _instance: Optional["FaultReporter"] = None
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
        self._rm: Optional[ResourceManager] = None
        self._last_alert: dict = {}
        self._lock = threading.Lock()
        self._pending: list = []
        self._load_dedup_state()
        self._initialized = True

    def bind(self, rm: ResourceManager):
        """绑定 ResourceManager，并在绑定成功后补发历史告警。"""
        self._rm = rm
        self._flush_pending()

    @property
    def rm(self) -> Optional[ResourceManager]:
        return self._rm

    def _load_dedup_state(self):
        """从文件加载去重状态（重启后恢复，防止轰炸）。"""
        try:
            if os.path.exists(self._DEDUP_STATE_FILE):
                with open(self._DEDUP_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                now = int(time.time())
                self._last_alert = {
                    k: v for k, v in data.items() if now - v < self._DEDUP_SEC
                }
        except Exception as e:
            logger.warning(f"告警去重状态加载失败，去重窗口被清空: {e}")
            self._last_alert = {}

    def _save_dedup_state(self):
        """持久化去重状态到文件。"""
        try:
            with open(self._DEDUP_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._last_alert, f)
        except Exception as e:
            logger.warning(f"告警去重状态持久化失败: {e}")

    def report(self, category: str, detail: str, severity: str = "⚠️", extra: str = ""):
        """统一故障上报入口。"""
        now = int(time.time())
        dedup_key = f"{severity}_{category}"
        with self._lock:
            if dedup_key in self._last_alert and now - self._last_alert[dedup_key] < self._DEDUP_SEC:
                logger.debug(f"[FaultReporter] 去重跳过：{category}")
                return
            self._last_alert[dedup_key] = now
            self._save_dedup_state()

        from datetime import datetime, timezone, timedelta
        ts = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{severity} <b>{category}</b>\n📝 {detail}\n"
        if extra:
            msg += f"📎 {extra}\n"
        msg += f"🕐 {ts}"

        logger.warning(f"[FaultReporter] {severity} {category}: {detail}")

        if not self._send_telegram(msg):
            self._save_local(category, detail, severity, ts)

    def _send_telegram(self, msg: str) -> bool:
        if not self._rm:
            return False
        try:
            admin_id = self._rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                return False
            with self._rm.locked('bot'):
                self._rm.bot.send_message(admin_id, msg, parse_mode="HTML")
            return True
        except Exception as e:
            logger.error(f"[FaultReporter] Telegram通知失败: {e}")
            return False

    def _save_local(self, category: str, detail: str, severity: str, ts: str):
        try:
            line = f"[{ts}] {severity} {category} | {detail}\n"
            with open(self._ALERT_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            self._pending.append(line)
            if len(self._pending) > self._MAX_PENDING:
                self._pending = self._pending[-self._MAX_PENDING:]
            logger.info(f"[FaultReporter] 已写入本地告警文件: {category}")
        except Exception as e:
            logger.error(f"[FaultReporter] 本地告警写入失败: {e}")

    def _flush_pending(self):
        if not self._pending or not self._rm:
            return
        pending = list(self._pending)
        self._pending.clear()
        try:
            admin_id = self._rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                return
            count = len(pending)
            if count > 5:
                summary = f"📋 <b>历史告警补发（{count}条）</b>\n" + "".join(pending[:5])
                summary += f"\n... 及其他{count - 5}条"
            else:
                summary = f"📋 <b>历史告警补发（{count}条）</b>\n" + "".join(pending)
            with self._rm.locked('bot'):
                self._rm.bot.send_message(admin_id, summary, parse_mode="HTML")
            logger.info(f"[FaultReporter] 补发{count}条历史告警")
        except Exception as e:
            logger.error(f"[FaultReporter] 补发失败，重新入队: {e}")
            self._pending.extend(pending)


# 全局单例
_fault_reporter = FaultReporter()


def get_fault_reporter() -> FaultReporter:
    return _fault_reporter


def report_fault(category: str, detail: str, severity: str = "⚠️", extra: str = ""):
    """全局故障上报函数（保持与原 auto_tasks.report_fault 接口兼容）。"""
    _fault_reporter.report(category, detail, severity, extra)
