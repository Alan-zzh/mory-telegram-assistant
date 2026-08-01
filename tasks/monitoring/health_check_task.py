"""
tasks/monitoring/health_check_task.py - 任务健康检查任务

检查关键任务是否按时执行，并审计数据库 task_log 异常。
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.support.task_guard import get_task_guard

logger = get_logger("tasks.monitoring.health_check")

_CST = timezone(timedelta(hours=8))
_PROCESS_START_AT = datetime.fromtimestamp(time.time(), _CST)
_LATE_START_NOTICE_SENT_DATES = set()


def _started_after_deadline(today: str, deadline_hour: int, deadline_minute: int) -> bool:
    """判断本进程是否在任务当天截止时间后才启动。"""
    try:
        deadline = datetime.strptime(today, "%Y-%m-%d").replace(
            hour=deadline_hour,
            minute=deadline_minute,
            second=0,
            microsecond=0,
            tzinfo=_CST,
        )
    except Exception:
        return False
    return _PROCESS_START_AT.date() == deadline.date() and _PROCESS_START_AT > deadline

class HealthCheckTask(BaseTask):
    """任务健康检查（每小时）。"""

    @property
    def task_id(self) -> str:
        return "health_check"

    def schedule(self) -> List[Dict[str, Any]]:
        options = {
            "max_instances": 1,
            "coalesce": True,
            "misfire_grace_time": 300,
        }
        return [
            {
                "job_id": "health_check",
                "trigger": "cron",
                "hour": "10,16,22",
                "minute": 0,
                "params": {},
                "options": options,
            },
            {
                "job_id": "health_check_late",
                "trigger": "cron",
                "hour": 23,
                "minute": 45,
                "params": {},
                "options": options,
            },
        ]

    def execute(self, ctx: TaskContext) -> None:
        try:
            now = datetime.now(_CST)
            current_hour = now.hour
            today = now.strftime("%Y-%m-%d")
            admin_id = self.rm.config.get("ADMIN_ID", 0)
            if not admin_id:
                logger.warning("⚠️ [health_check] ADMIN_ID为空，跳过健康检查")
                return

            logger.info(f"🏥 [health_check] 开始检查，当前时间{current_hour}:00，检查日期{today}")

            from modules.auto_tasks import (
                _build_critical_tasks,
                _is_deadline_reached,
                _missing_task_keys_today,
            )

            missed = []
            late_missed = []
            for task in _build_critical_tasks(self.rm.config, today):
                task_desc = task["desc"]
                deadline_hour = task["deadline_hour"]
                deadline_minute = task["deadline_minute"]
                if not _is_deadline_reached(now, deadline_hour, deadline_minute):
                    continue
                missing_keys = _missing_task_keys_today(self.rm.db, task.get("keys", []))
                if missing_keys:
                    suffix = ""
                    if len(missing_keys) <= 3:
                        suffix = f"：{', '.join(missing_keys)}"
                    else:
                        suffix = f"：缺失 {len(missing_keys)} 个目标"
                    line = f"• {task_desc}（应在{deadline_hour:02d}:{deadline_minute:02d}前执行）{suffix}"
                    if _started_after_deadline(today, deadline_hour, deadline_minute):
                        late_missed.append(line)
                        logger.info(
                            f"🏥 [health_check] ⏭️ {task_desc} 今日错过触发窗口: "
                            f"process_start={_PROCESS_START_AT.strftime('%H:%M:%S')} "
                            f"missing={missing_keys[:5]}"
                        )
                    else:
                        missed.append(line)
                        logger.info(f"🏥 [health_check] ❌ {task_desc} 今日未执行完整: {missing_keys[:5]}")
                else:
                    logger.debug(f"🏥 [health_check] ✅ {task_desc} 今日已执行")

            lock_record_anomalies = get_task_guard().audit_task_log(self.rm.db)

            parts = []
            if missed:
                parts.append(f"⚠️ <b>任务未执行</b>\n" + "\n".join(missed))
            if late_missed and today not in _LATE_START_NOTICE_SENT_DATES:
                _LATE_START_NOTICE_SENT_DATES.add(today)
                start_text = _PROCESS_START_AT.strftime("%H:%M:%S")
                parts.append(
                    f"ℹ️ <b>任务窗口已错过</b>\n"
                    f"本进程今日 {start_text} 才启动，以下任务已过当天触发窗口，不会自动补跑：\n"
                    + "\n".join(late_missed)
                )
            if lock_record_anomalies:
                parts.append(
                    f"🚨 <b>任务防重记录异常</b>\n"
                    + "\n".join(lock_record_anomalies)
                )

            if parts:
                msg = f"🏥 <b>任务健康检查</b> · {today}\n\n" + "\n\n".join(parts)
                try:
                    with self.rm.locked('bot'):
                        self.rm.bot.send_message(admin_id, msg, parse_mode="HTML")
                    logger.warning(f"⚠️ [health_check] 发现异常，已通知管理员")
                except Exception as e:
                    logger.error(f"⚠️ [health_check] 通知发送失败：{e}")
                    raise
            else:
                logger.info(f"✅ [health_check] 所有关键任务均正常执行，数据库无异常")
        except Exception as e:
            logger.error(f"❌ [health_check] 健康检查失败：{e}")
            raise
