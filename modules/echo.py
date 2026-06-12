"""
Echo复读机 - Bot发送指定消息

命令：
  /echo 消息内容 → handle_echo（仅管理员）
"""
from core.logging_util import get_logger

logger = get_logger("echo")


def handle_echo(bot, m, config, db):
    """Bot发送指定消息"""
    chat_id = m.chat.id
    uid = m.from_user.id

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可使用复读功能")
            return
    except Exception:
        return

    text = (m.text or "").strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/echo 消息内容")
        return

    content = parts[1].strip()

    try:
        bot.send_message(chat_id, content)
        # 删除命令消息（受全局开关控制）
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception:
                pass
        logger.info(f"Echo: chat={chat_id} uid={uid} len={len(content)}")
    except Exception as e:
        logger.error(f"Echo异常: {e}")
        bot.reply_to(m, "❌ 发送失败")
