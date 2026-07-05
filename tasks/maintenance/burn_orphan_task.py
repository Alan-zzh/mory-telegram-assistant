"""
tasks/maintenance/burn_orphan_task.py - Bot消息超时清理任务

每 6 小时清理超过 30 分钟的群聊 Bot 回复和主动播报。
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.helpers import can_orphan_cleanup
from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.burn_orphan")

_CST = timezone(timedelta(hours=8))

# 模块级告警状态，防刷屏
_orphan_disabled_alert_state = {"last_alert_ts": 0}
_ORPHAN_DISABLED_ALERT_INTERVAL = 86400  # 24小时一次


def _handle_orphan_disabled_alert(rm, orphan_count: int):
    """ORPHAN_CLEANUP_ENABLED=False 时通知管理员（每24h一次）。"""
    now_ts = int(time.time())
    last_ts = _orphan_disabled_alert_state["last_alert_ts"]

    logger.warning(f"⚠️ ORPHAN_CLEANUP_ENABLED=False, {orphan_count} 条孤儿堆积待清理")

    if now_ts - last_ts < _ORPHAN_DISABLED_ALERT_INTERVAL:
        return

    admin_id = rm.config.get("ADMIN_ID", 0)
    if not admin_id:
        return

    try:
        alert_msg = (
            f"⚠️ <b>孤儿消息清理告警</b>\n\n"
            f"当前 <code>ORPHAN_CLEANUP_ENABLED=False</code>，"
            f"本次发现 <b>{orphan_count}</b> 条超时孤儿无法被删除。\n\n"
            f"开启方式：\n"
            f"1. Dashboard → 设置 → 消息管理 → 启用孤儿清理\n"
            f"2. 或修改 config.json: <code>\"ORPHAN_CLEANUP_ENABLED\": true</code>\n\n"
            f"本告警每 24 小时最多发送一次。"
        )
        with rm.locked('bot'):
            rm.bot.send_message(admin_id, alert_msg, parse_mode="HTML")
        _orphan_disabled_alert_state["last_alert_ts"] = now_ts
        logger.info(f"📨 孤儿清理告警已发管理员 admin_id={admin_id}")
    except Exception as e:
        logger.error(f"孤儿清理告警发送失败: {e}")


class BurnOrphanTask(BaseTask):
    """阅后即焚清理任务（每6小时一次）。"""

    @property
    def task_id(self) -> str:
        return "burn_orphan"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "burn_orphan",
            "trigger": "cron",
            "hour": "*/6",
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
            logger.info("🔍 [Phase1] 检查超时Bot消息（30分钟窗口）...")
            orphans = self.rm.db.get_orphan_messages()
            active_messages = []
            if hasattr(self.rm.db, "get_expired_channel_messages"):
                try:
                    active_messages = self.rm.db.get_expired_channel_messages()
                except Exception as active_err:
                    logger.warning(f"主动播报追踪查询失败，继续清理reply_tracking: {active_err}")

            pending = {}
            for bot_mid, cid, user_mid in orphans:
                pending[(int(cid), int(bot_mid))] = (int(bot_mid), int(cid), int(user_mid))
            for bot_mid, cid, user_mid in active_messages:
                pending.setdefault((int(cid), int(bot_mid)), (int(bot_mid), int(cid), int(user_mid)))
            targets = list(pending.values())

            if targets:
                if can_orphan_cleanup(self.rm.config):
                    logger.info(
                        f"🗑️ 发现{len(targets)}条超时Bot消息（>30分钟），"
                        f"reply={len(orphans)} active={len(active_messages)}，开始清理..."
                    )
                    success_count = 0
                    fail_count = 0
                    for bot_mid, cid, user_mid in targets:
                        try:
                            with self.rm.locked('bot'):
                                self.rm.bot.delete_message(cid, int(bot_mid))
                            success_count += 1
                        except Exception as del_err:
                            fail_count += 1
                            logger.debug(f"  删除失败：bot_mid={bot_mid}, err={del_err}")
                        if hasattr(self.rm.db, "delete_bot_message_records"):
                            self.rm.db.delete_bot_message_records(cid, bot_mid)
                        else:
                            self.rm.db.delete_tracked(bot_mid, cid)
                    logger.info(f"✅ Phase1完成：成功{success_count}条，失败{fail_count}条")
                    try:
                        self.rm.db.log_orphan_cleanup(
                            found_count=len(targets),
                            deleted_count=success_count,
                            skipped_count=fail_count,
                            trigger="scheduled",
                        )
                    except Exception as log_err:
                        logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")
                else:
                    _handle_orphan_disabled_alert(self.rm, len(targets))
                    logger.info(f"[孤儿清理] ORPHAN_CLEANUP_ENABLED=False, 跳过删除{len(targets)}条孤儿消息")
                    try:
                        self.rm.db.log_orphan_cleanup(
                            found_count=len(targets),
                            deleted_count=0,
                            skipped_count=len(targets),
                            error="ORPHAN_CLEANUP_ENABLED=False",
                            trigger="scheduled",
                        )
                    except Exception as log_err:
                        logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")
            else:
                logger.info("✅ Phase1：无超时Bot消息")
                try:
                    self.rm.db.log_orphan_cleanup(
                        found_count=0, deleted_count=0, skipped_count=0,
                        trigger="scheduled",
                    )
                except Exception as log_err:
                    logger.debug(f"orphan_cleanup_log 写入失败: {log_err}")

            logger.info("✅ [Phase2] 已跳过forward探测（v4.5.35废弃），依赖Phase1 TTL清理")
        except Exception as e:
            logger.error(f"❌ 阅后即焚孤儿清理失败：{e}", exc_info=True)
            try:
                self.rm.db.log_orphan_cleanup(
                    found_count=0, deleted_count=0, skipped_count=0,
                    error=str(e)[:200], trigger="scheduled",
                )
            except Exception:
                logger.debug(f"记录孤儿清理日志失败: {e}")
