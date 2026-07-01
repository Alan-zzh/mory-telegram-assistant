"""
tasks/monitoring/health_check_task.py - 任务健康检查任务

检查关键任务是否按时执行，并审计数据库 task_log 异常。
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.support.task_guard import get_task_guard

logger = get_logger("tasks.monitoring.health_check")

_CST = timezone(timedelta(hours=8))

# 关键任务清单：(task_key, 描述, 预期小时)
_CRITICAL_TASKS = [
    ("greeting_morning", "早安问候", 10),
    ("greeting_afternoon", "午安问候", 13),
    ("greeting_evening", "晚安问候", 23),
    ("news_morning", "早间新闻", 10),
    ("news_afternoon", "午间新闻", 14),
    ("news_evening", "晚间新闻", 21),
    ("daily_report", "每日日报", 10),
]


class HealthCheckTask(BaseTask):
    """任务健康检查（每小时）。"""

    @property
    def task_id(self) -> str:
        return "health_check"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "health_check",
            "trigger": "cron",
            "hour": "10,16,22",
            "minute": 0,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
            },
        }]

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

            missed = []
            for task_key, task_desc, expected_hour in _CRITICAL_TASKS:
                if current_hour < expected_hour:
                    continue
                check_key = f"{task_key}_{today}"
                if not self.rm.db.is_task_executed_today(check_key):
                    missed.append(f"• {task_desc}（应在{expected_hour}:00前执行）")
                    logger.info(f"🏥 [health_check] ❌ {task_desc} 今日未执行")
                else:
                    logger.debug(f"🏥 [health_check] ✅ {task_desc} 今日已执行")

            anomalies = get_task_guard().audit_task_log(self.rm.db)

            parts = []
            if missed:
                parts.append(f"⚠️ <b>任务未执行</b>\n" + "\n".join(missed))
            if anomalies:
                parts.append(f"🚨 <b>数据库锁异常</b>\n" + "\n".join(anomalies))

            if parts:
                msg = f"🏥 <b>任务健康检查</b> · {today}\n\n" + "\n\n".join(parts)
                try:
                    with self.rm.locked('bot'):
                        self.rm.bot.send_message(admin_id, msg, parse_mode="HTML")
                    logger.warning(f"⚠️ [health_check] 发现异常，已通知管理员")
                except Exception as e:
                    logger.error(f"⚠️ [health_check] 通知发送失败：{e}")
            else:
                logger.info(f"✅ [health_check] 所有关键任务均正常执行，数据库无异常")
        except Exception as e:
            logger.error(f"❌ [health_check] 健康检查失败：{e}")
