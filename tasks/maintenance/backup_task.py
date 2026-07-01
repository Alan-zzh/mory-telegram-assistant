"""
tasks/maintenance/backup_task.py - 数据库备份任务

每小时执行一次 SQLite 热备份，保留最近 24 小时全量 + 7 天每日 1 份。
"""

import glob
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.backup")

_CST = timezone(timedelta(hours=8))


def _do_backup(db_file: str):
    """执行数据库备份并清理旧备份。"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    backup_dir = os.path.join(base_dir, "backup")
    os.makedirs(backup_dir, exist_ok=True)
    ts_str = datetime.now(_CST).strftime("%Y%m%d_%H00")
    dest = os.path.join(backup_dir, f"mory_backup_{ts_str}.db")

    try:
        import sqlite3 as _sqlite3
        src_conn = _sqlite3.connect(db_file)
        dst_conn = _sqlite3.connect(dest)
        try:
            src_conn.execute("PRAGMA busy_timeout=30000")
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        all_backups = sorted(glob.glob(os.path.join(backup_dir, "mory_backup_*.db")))
        now_ts = time.time()
        hourly_keep = []
        daily_seen = {}
        for path in all_backups:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            age_hours = (now_ts - mtime) / 3600
            if age_hours <= 24:
                hourly_keep.append(path)
            else:
                basename = os.path.basename(path)
                parts = basename.split("_")
                if len(parts) >= 3 and parts[2][:8].isdigit():
                    date_str = parts[2][:8]
                else:
                    continue
                if date_str not in daily_seen or os.path.getmtime(daily_seen[date_str]) < mtime:
                    daily_seen[date_str] = path
        daily_keep = list(daily_seen.values())[-7:]
        keep = set(hourly_keep + daily_keep)
        removed = 0
        for old in all_backups:
            if old not in keep:
                try:
                    os.remove(old)
                    removed += 1
                except OSError:
                    pass
        logger.info(f"💾 备份完成：{dest}（保留 {len(keep)} 份，清理 {removed} 份）")
    except Exception as e:
        logger.error(f"备份失败：{e}")


class BackupTask(BaseTask):
    """数据库备份任务（每小时）。"""

    @property
    def task_id(self) -> str:
        return "backup"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "backup",
            "trigger": "cron",
            "minute": 5,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            _do_backup(self.rm.db.db_file)
        except Exception as e:
            logger.error(f"数据库备份失败：{e}")
