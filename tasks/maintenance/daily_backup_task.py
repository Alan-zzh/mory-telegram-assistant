"""
tasks/maintenance/daily_backup_task.py - 每日自动备份任务

每天凌晨备份数据库和配置文件，保留最近 7 天。
"""

import os
import shutil
import sqlite3 as _sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.daily_backup")

_CST = timezone(timedelta(hours=8))


class DailyBackupTask(BaseTask):
    """每日自动备份任务（凌晨 3:00）。"""

    @property
    def task_id(self) -> str:
        return "daily_backup"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "daily_backup",
            "trigger": "cron",
            "hour": 3,
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        if not self.rm.config.get("DAILY_BACKUP_ENABLED", False):
            return

        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            backup_dir = os.path.join(base_dir, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            ts_str = datetime.now(_CST).strftime("%Y%m%d_%H%M%S")

            db_src = self.rm.db.db_file
            db_dest = os.path.join(backup_dir, f"backup_{ts_str}.db")
            src_conn = _sqlite3.connect(db_src)
            dst_conn = _sqlite3.connect(db_dest)
            try:
                src_conn.execute("PRAGMA busy_timeout=30000")
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            config_src = os.path.join(base_dir, "config.json")
            config_dest = os.path.join(backup_dir, f"backup_{ts_str}.json")
            if os.path.exists(config_src):
                shutil.copy2(config_src, config_dest)

            cutoff_time = time.time() - (7 * 86400)
            removed_count = 0
            for filename in os.listdir(backup_dir):
                if not (filename.endswith('.db') or filename.endswith('.json')):
                    continue
                filepath = os.path.join(backup_dir, filename)
                try:
                    file_mtime = os.path.getmtime(filepath)
                    if file_mtime < cutoff_time:
                        os.remove(filepath)
                        removed_count += 1
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
            logger.info(f"💾 每日备份完成：数据库+配置文件（清理 {removed_count} 个旧备份）")
        except Exception as e:
            logger.error(f"每日备份失败：{e}")
            raise
