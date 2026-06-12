"""批量消息删除模块 - 群管消息清理功能"""
import telebot
from core.logging_util import get_logger

logger = get_logger(__name__)


def _can_delete(config: dict) -> bool:
    """检查是否允许删除消息"""
    if not config.get("ENABLE_MESSAGE_DELETION", False):
        logger.warning("[消息清理] ENABLE_MESSAGE_DELETION 未开启，跳过删除操作")
        return False
    return True


def handle_purge(bot, m, config, db, count_str):
    """删除N条消息 - 从回复的消息开始往前删N条"""
    if not m.reply_to_message:
        bot.reply_to(m, "请回复一条消息后再使用此命令")
        return

    if not _can_delete(config):
        # 功能已关闭，静默忽略，不回复任何消息
        return

    try:
        n = int(count_str)
    except (ValueError, TypeError):
        bot.reply_to(m, "请输入有效的数字，例如 /purge 10")
        return

    n = max(1, min(n, 100))
    start_id = m.reply_to_message.message_id
    deleted = 0

    for msg_id in range(start_id, start_id + n):
        try:
            bot.delete_message(m.chat.id, msg_id)
            deleted += 1
        except telebot.apihelper.ApiTelegramException:
            pass  # 消息已删除或不存在，跳过
        except Exception as e:
            logger.warning(f"删除消息 {msg_id} 异常: {e}")

    # 删除 /purge 命令本身
    try:
        bot.delete_message(m.chat.id, m.message_id)
    except Exception:
        pass

    # 回复删除结果，3秒后自动删除
    try:
        reply = bot.send_message(m.chat.id, f"已删除 {deleted} 条消息")
        bot.register_next_step_handler_by_chat_id(m.chat.id, lambda _: None)  # 占位
        import threading
        threading.Timer(3.0, lambda: _safe_delete(bot, m.chat.id, reply.message_id)).start()
    except Exception as e:
        logger.warning(f"发送删除结果失败: {e}")


def handle_del(bot, m, config, db):
    """删除单条回复的消息"""
    if not m.reply_to_message:
        bot.reply_to(m, "请回复一条消息后再使用此命令")
        return

    if not _can_delete(config):
        # 功能已关闭，静默忽略，不回复任何消息
        return

    # 删除被回复的消息
    try:
        bot.delete_message(m.chat.id, m.reply_to_message.message_id)
    except telebot.apihelper.ApiTelegramException:
        pass  # 消息已删除
    except Exception as e:
        logger.warning(f"删除消息异常: {e}")

    # 删除 /del 命令本身
    try:
        bot.delete_message(m.chat.id, m.message_id)
    except Exception:
        pass


def handle_purge_to(bot, m, config, db):
    """删除从回复消息到当前消息之间的所有消息"""
    if not m.reply_to_message:
        bot.reply_to(m, "请回复一条消息后再使用此命令")
        return

    if not _can_delete(config):
        # 功能已关闭，静默忽略，不回复任何消息
        return

    start_id = m.reply_to_message.message_id
    end_id = m.message_id
    deleted = 0

    for msg_id in range(start_id, end_id + 1):
        try:
            bot.delete_message(m.chat.id, msg_id)
            deleted += 1
        except telebot.apihelper.ApiTelegramException:
            pass  # 消息已删除或不存在，跳过
        except Exception as e:
            logger.warning(f"删除消息 {msg_id} 异常: {e}")

    # 回复删除结果，3秒后自动删除
    try:
        reply = bot.send_message(m.chat.id, f"已删除 {deleted} 条消息")
        import threading
        threading.Timer(3.0, lambda: _safe_delete(bot, m.chat.id, reply.message_id)).start()
    except Exception as e:
        logger.warning(f"发送删除结果失败: {e}")


def _safe_delete(bot, chat_id, message_id):
    """安全删除消息，忽略异常"""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass
