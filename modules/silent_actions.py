"""
静默操作 - 静默封禁/禁言/踢出（不发送通知）

命令：
  /sban @用户 → handle_sban
  /smute @用户 时长 → handle_smute
  /skick @用户 → handle_skick
"""
import time
from core.logging_util import get_logger
from core.database import _db_lock

logger = get_logger("silent_actions")


def _extract_target_uid(m, text):
    """从消息中提取目标用户ID"""
    # 优先：回复消息
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user.id

    # 其次：@提及
    entities = m.entities or []
    for ent in entities:
        if ent.type == "text_mention" and ent.user:
            return ent.user.id

    # 最后：文本中的数字ID
    parts = text.split()
    for part in parts[1:]:
        if part.lstrip("-").isdigit():
            return int(part)

    return None


def _check_admin(bot, m):
    """检查是否管理员"""
    try:
        member = bot.get_chat_member(m.chat.id, m.from_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def handle_sban(bot, m, config, db):
    """静默封禁"""
    if not _check_admin(bot, m):
        return

    chat_id = m.chat.id
    target_uid = _extract_target_uid(m, m.text or "")
    if not target_uid:
        bot.reply_to(m, "❌ 请指定用户")
        return

    try:
        bot.kick_chat_member(chat_id, target_uid)
        # 删除命令消息（受全局开关控制）
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception:
                pass
        # 记录管理日志
        _log_action(db, chat_id, m.from_user.id, target_uid, "sban")
        logger.info(f"静默封禁: chat={chat_id} target={target_uid} by={m.from_user.id}")
    except Exception as e:
        logger.error(f"静默封禁异常: {e}")


def handle_smute(bot, m, config, db):
    """静默禁言"""
    if not _check_admin(bot, m):
        return

    chat_id = m.chat.id
    text = (m.text or "").strip()
    target_uid = _extract_target_uid(m, text)
    if not target_uid:
        bot.reply_to(m, "❌ 请指定用户")
        return

    # 解析时长
    duration = 3600  # 默认1小时
    parts = text.split()
    for part in parts:
        if part.endswith("m") and part[:-1].isdigit():
            duration = int(part[:-1]) * 60
        elif part.endswith("h") and part[:-1].isdigit():
            duration = int(part[:-1]) * 3600
        elif part.endswith("d") and part[:-1].isdigit():
            duration = int(part[:-1]) * 86400

    try:
        bot.restrict_chat_member(
            chat_id, target_uid,
            until_date=int(time.time()) + duration,
            can_send_messages=False
        )
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception:
                pass
        _log_action(db, chat_id, m.from_user.id, target_uid, "smute")
        logger.info(f"静默禁言: chat={chat_id} target={target_uid} duration={duration}s")
    except Exception as e:
        logger.error(f"静默禁言异常: {e}")


def handle_skick(bot, m, config, db):
    """静默踢出"""
    if not _check_admin(bot, m):
        return

    chat_id = m.chat.id
    target_uid = _extract_target_uid(m, m.text or "")
    if not target_uid:
        bot.reply_to(m, "❌ 请指定用户")
        return

    try:
        bot.kick_chat_member(chat_id, target_uid)
        # 立即解封，允许重新加入
        bot.unban_chat_member(chat_id, target_uid)
        if config.get("ENABLE_MESSAGE_DELETION", False):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception:
                pass
        _log_action(db, chat_id, m.from_user.id, target_uid, "skick")
        logger.info(f"静默踢出: chat={chat_id} target={target_uid}")
    except Exception as e:
        logger.error(f"静默踢出异常: {e}")


def _log_action(db, chat_id, operator_uid, target_uid, action):
    """记录管理日志"""
    try:
        now_ts = int(time.time())
        with _db_lock:
            db.conn.execute(
                "INSERT INTO admin_logs (chat_id, operator_uid, target_uid, action, reason, ts) VALUES (?,?,?,?,?,?)",
                (chat_id, operator_uid, target_uid, action, "静默操作", now_ts)
            )
            db.conn.commit()
    except Exception:
        pass
