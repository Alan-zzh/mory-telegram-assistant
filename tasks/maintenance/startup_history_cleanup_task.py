"""
tasks/maintenance/startup_history_cleanup_task.py - 启动历史清理任务

启动时追溯清理黑名单用户的历史消息，避免广告消息残留。
"""

import time
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.maintenance.startup_history_cleanup")

_BASELINE_STATE_PREFIX = "startup_history_cleanup_verified_v1"


def _baseline_state_key(chat_id: int) -> str:
    """每个管理群独立建立一次可信基线，新增群不会继承旧群状态。"""
    return f"{_BASELINE_STATE_PREFIX}:{int(chat_id)}"


def _has_trusted_baseline(value: Any) -> bool:
    """只接受本任务写入的正整数时间戳，任意脏值都回到完整核验。"""
    try:
        return int(str(value or "").strip()) > 0
    except (TypeError, ValueError):
        return False


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
        total_deleted = 0
        total_already_absent = 0
        total_candidates = 0
        failed_chats = set()

        for cid in chat_ids:
            state_key = _baseline_state_key(cid)
            baseline_complete = _has_trusted_baseline(db.get_system_state(state_key, ""))
            include_deleted = not baseline_complete
            mode = "完整基线" if include_deleted else "未删除增量"
            chat_failures = []
            batch_number = 0
            while True:
                batch_number += 1
                try:
                    messages = db.get_blacklisted_ad_cleanup_candidates(
                        cid,
                        include_deleted=include_deleted,
                        limit_per_user=500,
                    )
                except Exception as e:
                    logger.error(f"读取黑名单广告清理候选失败 cid={cid}: {e}")
                    chat_failures.append(e)
                    break

                total_candidates += len(messages)
                logger.info(
                    f"[启动历史清理] 群组 {cid} 进入{mode}核验，"
                    f"批次 {batch_number} 候选 {len(messages)} 条"
                )
                if not messages:
                    break

                for message in messages:
                    message_id = message.get("msg_id")
                    if not message_id:
                        error = RuntimeError(f"广告清理候选缺少 msg_id cid={cid}")
                        logger.warning(str(error))
                        chat_failures.append(error)
                        continue
                    try:
                        from modules.ad_enforcement import delete_confirmed_ad_message
                        deletion = delete_confirmed_ad_message(bot, db, cid, message_id)
                    except Exception as e:
                        logger.warning(f"删除黑名单历史消息异常 cid={cid} mid={message_id}: {e}")
                        chat_failures.append(e)
                        continue

                    status = deletion.get("status", "failed")
                    deletion_persisted = deletion.get("deletion_persisted") is True
                    if status in {"deleted", "already_absent"} and not deletion_persisted:
                        error = RuntimeError(
                            f"Telegram 删除结果未可靠落库 cid={cid} mid={message_id} status={status}"
                        )
                        logger.warning(str(error))
                        chat_failures.append(error)
                    elif status == "deleted":
                        total_deleted += 1
                    elif status == "already_absent":
                        total_already_absent += 1
                    else:
                        error = RuntimeError(
                            f"Telegram 删除未完成 cid={cid} mid={message_id} status={status}"
                        )
                        logger.warning(f"删除黑名单历史消息失败: {error}")
                        chat_failures.append(error)

                if chat_failures or include_deleted:
                    break

            if chat_failures:
                failures.extend(chat_failures)
                failed_chats.add(cid)
                continue

            if not baseline_complete:
                try:
                    db.set_system_state(state_key, str(int(time.time())))
                    logger.info(f"[启动历史清理] 群组 {cid} 可信基线已建立")
                except Exception as e:
                    logger.error(f"写入启动历史清理基线失败 cid={cid}: {e}")
                    failures.append(e)
                    failed_chats.add(cid)

        if failures:
            logger.error(
                "[启动历史清理] 未完成，"
                f"候选 {total_candidates} 条，失败群组 {len(failed_chats)} 个，"
                f"失败项 {len(failures)} 个"
            )
            raise ExceptionGroup("启动历史清理任务失败", failures)
        logger.info(
            "[启动历史清理] 完成，"
            f"候选 {total_candidates} 条，实际删除 {total_deleted} 条，"
            f"已不存在 {total_already_absent} 条"
        )
