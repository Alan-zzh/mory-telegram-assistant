# -*- coding: utf-8 -*-
"""
[Codex] Telegram Business/Guest 新事件处理器。

这层只做状态同步和观测，不把连接/删除类事件送进普通聊天回复链路。
"""

from core.logging_util import get_logger

logger = get_logger("business_handlers")


def register_business_handlers(bot, ctx):
    """注册 SDK 兼容层调用的 Business update 钩子。"""

    def _on_business_update(update):
        return handle_business_update(bot, update, ctx.config, ctx.db)

    setattr(bot, "_mory_business_update_handler", _on_business_update)
    logger.info("Telegram Business update 钩子已注册")


def handle_business_update(bot, update, config: dict, db) -> bool:
    """处理 SDK 暂未原生分发的新 Update 类型。"""
    handled = False

    connection = getattr(update, "business_connection", None)
    if connection is not None:
        _log_business_connection(connection)
        handled = True

    deleted = getattr(update, "deleted_business_messages", None)
    if deleted is not None:
        sync_deleted_business_messages(deleted, db)
        handled = True

    guest_message = getattr(update, "guest_message", None)
    if guest_message is not None:
        chat_id = _get(_get(guest_message, "chat"), "id", 0)
        msg_id = _get(guest_message, "message_id", 0)
        logger.info(f"Guest message 已观测: chat={chat_id} msg={msg_id}")
        handled = True

    if getattr(update, "purchased_paid_media", None) is not None:
        logger.info("收到 purchased_paid_media 事件：项目不在 Bot 内收款，仅记录观测")
        handled = True

    if getattr(update, "managed_bot", None) is not None:
        logger.info("收到 managed_bot 事件：已保留原始字段用于后续兼容")
        handled = True

    return handled


def sync_deleted_business_messages(deleted_business_messages, db) -> int:
    """把 Telegram 已删除的 Business 消息同步标记到本地追踪表。"""
    chat = _get(deleted_business_messages, "chat")
    chat_id = _get(chat, "id", 0) or 0
    message_ids = _get(deleted_business_messages, "message_ids", []) or []
    business_connection_id = _get(deleted_business_messages, "business_connection_id", "")

    if not chat_id or not message_ids:
        logger.debug(f"Business 删除事件缺少 chat/message_ids: {deleted_business_messages}")
        return 0
    if not db or not hasattr(db, "mark_message_deleted"):
        logger.debug("Business 删除事件收到，但数据库不支持 mark_message_deleted")
        return 0

    marked = 0
    for msg_id in message_ids:
        try:
            if db.mark_message_deleted(int(chat_id), int(msg_id)):
                marked += 1
        except Exception as e:
            logger.debug(f"Business 删除标记失败: chat={chat_id} msg={msg_id} err={e}")

    logger.info(
        "Business 删除事件同步: "
        f"bc={business_connection_id or '-'} chat={chat_id} "
        f"messages={len(message_ids)} marked={marked}"
    )
    return marked


def _log_business_connection(connection) -> None:
    """记录 Business 连接状态，避免把状态事件误当成用户消息。"""
    bc_id = _get(connection, "id", "")
    user_chat_id = _get(connection, "user_chat_id", "")
    is_enabled = _get(connection, "is_enabled", "")
    logger.info(f"Business 连接状态: id={bc_id or '-'} user_chat={user_chat_id or '-'} enabled={is_enabled}")


def _get(obj, key: str, default=None):
    """兼容 dict 与 SDK 对象读取。"""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
