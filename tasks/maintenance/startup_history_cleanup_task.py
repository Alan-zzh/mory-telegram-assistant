"""
tasks/maintenance/startup_history_cleanup_task.py - 启动历史清理任务

启动时追溯清理黑名单用户的历史消息，避免白嫖消息残留。
"""

from datetime import timezone, timedelta
from typing import Any, Dict, List

from core.helpers import can_delete_message
from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.startup_history_cleanup")

_CST = timezone(timedelta(hours=8))


class StartupHistoryCleanupTask(BaseTask):
    """启动历史清理任务（一次性，启动时执行）。"""

    @property
    def task_id(self) -> str:
        return "startup_history_cleanup"

    def schedule(self) -> List[Dict[str, Any]]:
        # 一次性任务不由 APScheduler 周期性注册，启动时单独调度
        return []

    def execute(self, ctx: TaskContext) -> None:
        bot = self.rm.bot
        db = self.rm.db
        config = self.rm.config

        if not can_delete_message(config):
            logger.info("[启动历史清理] 消息删除全局开关关闭，跳过")
            return

        gid = config.get("GROUP_ID", 0)
        if gid:
            chat_ids = [gid]
        else:
            try:
                managed_groups = config.get("MANAGED_GROUPS", [])
                chat_ids = [managed_groups] if isinstance(managed_groups, int) else list(managed_groups or [])
            except Exception as e:
                logger.error(f"获取管理群组列表失败: {e}")
                raise

        if not chat_ids:
            logger.info("[启动历史清理] 未找到管理的群组，跳过")
            return

        failures = []
        all_banned_uids = set()
        for table, column in (("blacklist", "uid"), ("global_blacklist", "user_id")):
            try:
                for row in db.conn.execute(f"SELECT {column} FROM {table}").fetchall():
                    all_banned_uids.add(int(row[0]))
            except Exception as e:
                logger.error(f"查询{table}表失败: {e}")
                failures.append(e)

        if not all_banned_uids:
            if failures:
                raise ExceptionGroup("启动历史清理查询黑名单失败", failures)
            logger.info("[启动历史清理] 无黑名单用户，跳过")
            return

        logger.info(f"[启动历史清理] 开始清理 {len(all_banned_uids)} 个黑名单用户的历史消息")
        total_deleted = 0
        for uid in all_banned_uids:
            for cid in chat_ids:
                try:
                    msgs = db.get_user_messages(uid, cid, limit=500)
                except Exception as e:
                    logger.error(f"读取黑名单用户历史失败 uid={uid} cid={cid}: {e}")
                    failures.append(e)
                    continue
                for message in msgs:
                    if message.get("deleted") or not (message_id := message.get("msg_id")):
                        continue
                    try:
                        bot.delete_message(cid, message_id)
                        db.mark_message_deleted(cid, message_id)
                        total_deleted += 1
                    except Exception as e:
                        logger.warning(f"删除黑名单历史消息失败 cid={cid} mid={message_id}: {e}")
                        failures.append(e)

        logger.info(f"[启动历史清理] 完成，共清理 {total_deleted} 条黑名单用户历史消息")
        if failures:
            raise ExceptionGroup("启动历史清理任务失败", failures)
