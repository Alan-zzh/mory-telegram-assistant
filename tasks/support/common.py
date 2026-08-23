"""
tasks/support/common.py - 任务模块通用工具函数

多任务复用的工具函数集（v5.38.69 自已拆除的 auto_tasks.py 迁出）。
"""

import os
import re
import threading
from datetime import datetime, timedelta, timezone

from core.helpers import can_delete_message, get_broadcast_auto_delete_config
from core.logging_util import get_logger
from core.resource_manager import ResourceManager
from core.task_transaction import TaskTransactionManager
from core.telegram_send_utils import send_message_compat, send_photo_compat
from tasks.support.fault_reporter import get_fault_reporter
from telebot import types

logger = get_logger("tasks.support.common")

_CST = timezone(timedelta(hours=8))

class TaskAbort(Exception):
    """任务中止（非异常，但不应确认完成，需释放数据库锁）。"""

    def __init__(self, message: str, expected: bool = False):
        super().__init__(message)
        self.expected = expected


def record_abort(task_name: str, reason: str):
    """记录任务 abort 原因，连续 3 次触发 P0 告警。"""
    from tasks.support.task_guard import get_task_guard
    get_task_guard().record_claim_fail(task_name, reason)
    logger.warning(f"⚠️ [{task_name}] abort: {reason}")


def send_and_track(rm: ResourceManager, chat_id: int, text: str, parse_mode=None,
                   disable_web_page_preview=None, reply_markup=None):
    """发送消息并追踪浏览量（主动消息也入库 channel_tracking）。"""
    try:
        with rm.locked('bot'):
            # [v5.32] 修复：link_preview_options 由 send_message_compat 统一处理
            # 避免传 dict 给 pyTelegramBotAPI 4.34.0 触发 'dict' object has no attribute 'is_disabled'
            sent = send_message_compat(
                rm.bot,
                chat_id,
                text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
        if sent and hasattr(sent, 'message_id'):
            schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
            if chat_id < 0:
                rm.db.track_channel_message(chat_id, sent.message_id, "text")
                rm.db.track_bot_message(chat_id, sent.message_id)
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None


def build_mory_contact_markup(period: str = "", config: dict = None):
    """按播报场景生成低打扰按钮；问候和新闻不夹带成交入口。

    v5.38.14：当 config.BUTTON_STYLE_ENABLED=true 时走 create_colored_button 统一上色
    （"看看预览"=了解语义→primary 蓝），与定点播报/玄学栏目视觉统一。
    """
    actions = {
        "afternoon": ("👀 看看预览", "https://t.me/moryselect"),
        "night": ("👀 看看预览", "https://t.me/moryselect"),
    }
    action = actions.get(period)
    if not action:
        return None
    label, url = action
    markup = types.InlineKeyboardMarkup()
    button_style_enabled = bool((config or {}).get("BUTTON_STYLE_ENABLED", False))
    if button_style_enabled:
        from core.telegram_send_utils import create_colored_button
        markup.add(create_colored_button(text=label, url=url, style="primary"))
    else:
        markup.add(types.InlineKeyboardButton(label, url=url))
    return markup


def send_greeting(
    rm: ResourceManager,
    chat_id: int,
    text: str,
    category: str = "greeting",
    rich_text: str = "",
    reply_markup=None,
    image_path: str = "",
):
    """发送早安/午安/晚安问候，支持"发新删旧"链式互删。

    [v5.32] 新增 rich_text 参数：当 RICH_MESSAGE_ENABLED=true 且 BROADCAST_FORMAT_VERSION
    ∈ {"rich","auto"} 时优先用 rich_text 走 sendRichMessage，失败回退到 text + HTML。

    [v5.38.15] 新增 image_path 参数：当提供有效本地图片路径时，优先以图片卡形式发送，
    失败回退 Rich Message / HTML。
    """
    auto_cfg = get_broadcast_auto_delete_config(rm.config)

    # 链式互删
    if auto_cfg["greeting_chain_delete"] and hasattr(rm, "db") and rm.db is not None:
        try:
            last = rm.db.get_last_broadcast(chat_id, "greeting")
            if last and last[0]:
                last_msg_id, last_ts = last
                try:
                    if can_delete_message(rm.config):
                        with rm.locked('bot'):
                            rm.bot.delete_message(chat_id, last_msg_id)
                        logger.info(f"🗑️ 链式互删：已删除上一条问候 [{category}] msg={last_msg_id} ts={last_ts}")
                except Exception as del_err:
                    logger.debug(f"链式互删失败（继续发新问候）: {del_err}")
                try:
                    rm.db.delete_broadcast(chat_id, "greeting")
                except Exception as e:
                    logger.debug(f"删除旧问候播报追踪失败: {e}")
        except Exception as e:
            logger.debug(f"链式互删查询失败（继续发新问候）: {e}")

    sent = None

    # [v5.38.15] 优先尝试图片卡路径
    if image_path and os.path.isfile(image_path):
        try:
            with rm.locked('bot'):
                sent = send_photo_compat(
                    rm.bot,
                    chat_id,
                    image_path,
                    caption=None,
                    reply_markup=reply_markup,
                )
            if sent and hasattr(sent, 'message_id'):
                schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
                if chat_id < 0:
                    rm.db.track_channel_message(chat_id, sent.message_id, "image")
                    rm.db.track_bot_message(chat_id, sent.message_id)
        except Exception as e:
            logger.warning(f"问候图片卡发送失败，回退 Rich Message/HTML: {e}")
            sent = None

    # [v5.32] 优先尝试 Rich Message 路径
    if sent is None:
        cfg = rm.config or {}
        rich_enabled = bool(cfg.get("RICH_MESSAGE_ENABLED", False))
        format_version = str(cfg.get("BROADCAST_FORMAT_VERSION", "html") or "html").lower()
        if rich_enabled and rich_text and format_version in ("rich", "auto"):
            try:
                with rm.locked('bot'):
                    from core.telegram_send_utils import send_rich_message_compat
                    sent = send_rich_message_compat(
                        rm.bot,
                        chat_id,
                        rich_text,
                        reply_markup=reply_markup,
                    )
                if sent and hasattr(sent, 'message_id'):
                    schedule_auto_delete(rm, chat_id, sent.message_id, 24 * 3600)
                    if chat_id < 0:
                        rm.db.track_channel_message(chat_id, sent.message_id, "text")
                        rm.db.track_bot_message(chat_id, sent.message_id)
            except Exception as e:
                logger.warning(f"问候 Rich Message 发送失败，回退 HTML: {e}")
                sent = None

    # 回退到 HTML parse_mode 路径
    if sent is None:
        sent = send_and_track(
            rm,
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )

    if sent and hasattr(sent, 'message_id') and hasattr(rm, "db") and rm.db is not None:
        try:
            rm.db.track_broadcast(chat_id, "greeting", sent.message_id)
            logger.info(f"📌 问候追踪入库：chat={chat_id} category={category} msg={sent.message_id}")
        except Exception as e:
            logger.debug(f"问候追踪入库失败: {e}")
    return sent


def schedule_auto_delete(rm: ResourceManager, chat_id: int, message_id: int, delay_seconds: int):
    """定时消息 24 小时无人理自动删除（使用 APScheduler 调度，避免线程泄漏）。"""
    try:
        from tasks.task_scheduler import get_scheduler_instance
        scheduler = get_scheduler_instance()
        if scheduler:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_seconds)
            scheduler.add_job(
                _do_delete_message,
                trigger='date',
                run_date=run_at,
                args=[rm, chat_id, message_id],
                id=f"auto_del_{chat_id}_{message_id}",
                max_instances=1,
                misfire_grace_time=300,
                replace_existing=False,
            )
    except Exception as e:
        logger.error(f"定时删除调度失败: {e}")


def _do_delete_message(rm: ResourceManager, chat_id: int, message_id: int):
    """APScheduler 回调：删除指定消息。"""
    try:
        if can_delete_message(rm.config):
            with rm.locked('bot'):
                rm.bot.delete_message(chat_id, message_id)
            logger.info(f"🗑️ 定时消息已自动删除: chat={chat_id}, msg={message_id}")
        else:
            logger.info(f"消息删除已禁用，跳过删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"定时消息删除失败（可能已被手动删除）: {e}")


def retry_task(rm: ResourceManager, task_func, task_name: str, delay_sec: int = 300):
    """5 分钟后重试失败的任务，仍失败则通知管理员。"""
    logger.info(f"🔄 [{task_name}] 调度重试，{delay_sec}秒后执行")

    def _do_retry(rm_inner: ResourceManager):
        from tasks.support.task_guard import get_task_guard
        try:
            logger.info(f"🔄 [{task_name}] 开始重试执行")
            task_func(rm_inner)
        except Exception as e:
            logger.error(f"❌ [{task_name}] 重试仍失败: {e}")
            get_fault_reporter().report("定时任务失败", f"任务: {task_name}，错误: {str(e)[:200]}", "⚠️")

    try:
        from tasks.task_scheduler import get_scheduler_instance
        scheduler = get_scheduler_instance()
        if scheduler:
            run_at = datetime.now(_CST) + timedelta(seconds=delay_sec)
            scheduler.add_job(
                _do_retry,
                trigger='date',
                run_date=run_at,
                args=[rm],
                id=f"retry_{task_name}",
                max_instances=1,
                misfire_grace_time=300,
                replace_existing=True,
            )
        else:
            logger.warning(f"跳过 {task_name} 重试：调度器不可用或正在关闭")
            return False
    except Exception as e:
        logger.error(f"重试任务调度失败: {e}")
        return False
    logger.info(f"⏰ 已安排{task_name}在{delay_sec}秒后重试")
    return True
