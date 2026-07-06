"""
tasks/maintenance/log_cleanup_task.py - 日志自动清理任务

每天凌晨清理过期日志文件和数据库日志表。
"""

import time as _time
from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger, cleanup_old_logs
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.log_cleanup")

_CST = timezone(timedelta(hours=8))


class LogCleanupTask(BaseTask):
    """日志自动清理任务（凌晨 4:00）。"""

    @property
    def task_id(self) -> str:
        return "log_cleanup"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "log_cleanup",
            "trigger": "cron",
            "hour": 4,
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            retention_days = self.rm.config.get("LOG_RETENTION_DAYS", 30)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_dir = os.path.join(base_dir, "logs")

            removed_count = cleanup_old_logs(log_dir, retention_days)
            if removed_count > 0:
                logger.info(f"🧹 日志清理完成：删除 {removed_count} 个超过 {retention_days} 天的日志文件")

            now_ts = int(_time.time())
            cutoff_30 = now_ts - 30 * 86400
            cutoff_90 = now_ts - 90 * 86400

            try:
                db = self.rm.db
                with db.lock:
                    tables_30 = {
                        "task_log": "exec_ts",
                        "spam_track": "window_start",
                        "puzzle_daily": "ts",
                        "broadcast_tracking": "ts",
                        "orphan_cleanup_log": "run_at",
                        "group_join_log": "ts",
                        "group_left_log": "ts",
                        "proactive_engage_log": "ts",
                        "retroactive_scan_log": "ts",
                        "button_click_stats": "last_updated",
                    }
                    for table, ts_col in tables_30.items():
                        try:
                            # 安全：table/ts_col 来自上方硬编码字典字面量，非用户输入，无注入风险
                            db.conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff_30,))
                        except Exception as de:
                            logger.debug(f"清理 {table} 跳过: {de}")

                    tables_90 = {
                        "admin_logs": "ts",
                        "telemetry_events": "ts",
                        "conversation_telemetry": "ts",
                        "ab_guardian_log": "ts",
                        "points_log": "ts",
                        "deleted_messages": "ts",
                        "message_snapshots": "ts",
                        "ab_test_stats": "ts",
                        "weekly_ab_report": "generated_at",
                    }
                    for table, ts_col in tables_90.items():
                        try:
                            # 安全：table/ts_col 来自上方硬编码字典字面量，非用户输入，无注入风险
                            db.conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff_90,))
                        except Exception as de:
                            logger.debug(f"清理 {table} 跳过: {de}")
                    db.conn.commit()
                logger.info(f"🧹 数据库日志表清理完成（30天+90天）")
            except Exception as dbe:
                logger.warning(f"数据库日志表清理失败（非致命）: {dbe}")
        except Exception as e:
            logger.error(f"日志清理失败：{e}")
