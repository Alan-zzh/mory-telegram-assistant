"""
置顶管理 - 置顶/取消置顶消息

功能：
  1. 置顶回复的消息（可选静默）
  2. 取消最新置顶
  3. 取消全部置顶

命令：
  /pin [silent] → handle_pin
  /unpin → handle_unpin
  /unpinall → handle_unpinall

"""
from core.logging_util import get_logger

logger = get_logger("pin_manage")


def handle_pin(bot, m, config, db):
    """置顶消息"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip().lower()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可置顶消息")
            return
    except Exception:
        return

    # 必须回复消息
    if not m.reply_to_message:
        bot.reply_to(m, "❌ 请回复要置顶的消息")
        return

    # 是否静默置顶
    silent = "silent" in text or " s" in text.split()

    try:
        bot.pin_chat_message(chat_id, m.reply_to_message.message_id, disable_notification=silent)
        if not silent:
            bot.reply_to(m, "📌 消息已置顶")
        else:
            # 静默置顶时删除命令消息（受全局开关控制）
            if config.get("ENABLE_MESSAGE_DELETION", False):
                try:
                    bot.delete_message(chat_id, m.message_id)
                except Exception:
                    pass
        logger.info(f"置顶消息: chat={chat_id} msg={m.reply_to_message.message_id} silent={silent}")
    except Exception as e:
        bot.reply_to(m, f"❌ 置顶失败：{e}")


def handle_unpin(bot, m, config, db):
    """取消最新置顶消息"""
    chat_id = m.chat.id
    uid = m.from_user.id

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可取消置顶")
            return
    except Exception:
        return

    try:
        bot.unpin_chat_message(chat_id)
        bot.reply_to(m, "📌 已取消最新置顶消息")
        logger.info(f"取消置顶: chat={chat_id}")
    except Exception as e:
        bot.reply_to(m, f"❌ 取消置顶失败：{e}")


def handle_unpinall(bot, m, config, db):
    """取消全部置顶消息"""
    chat_id = m.chat.id
    uid = m.from_user.id

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可取消全部置顶")
            return
    except Exception:
        return

    try:
        bot.unpin_all_chat_messages(chat_id)
        bot.reply_to(m, "📌 已取消所有置顶消息")
        logger.info(f"取消全部置顶: chat={chat_id}")
    except Exception as e:
        bot.reply_to(m, f"❌ 取消全部置顶失败：{e}")
