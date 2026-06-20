"""
反频道转发 - 自动删除频道转发消息

功能：
  1. 检测频道转发消息并自动删除
  2. 管理员豁免
  3. 开关控制

命令：
  /antichannel on/off → handle_antichannel

数据表：anti_channel_settings（chat_id, enabled, ts）
"""
import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("anti_channel")


def _get_settings(db, chat_id):
    """获取反频道设置"""
    try:
        row = db.conn.execute(
            "SELECT enabled FROM anti_channel_settings WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def check_anti_channel(bot, m, config, db):
    """检查消息是否为频道转发，返回True表示已处理（消息已删除）"""
    chat_id = m.chat.id

    # 检查是否开启
    enabled = _get_settings(db, chat_id)
    if not enabled:
        # 也检查全局默认配置
        if not config.get("ANTI_CHANNEL_DEFAULT", False):
            return False

    # 检查管理员豁免
    uid = m.from_user.id
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status in ("administrator", "creator"):
            return False
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # 检查是否为频道转发
    is_channel_forward = False
    if m.forward_origin:
        # pyTelegramBotAPI v4.x: forward_origin有type属性
        origin = m.forward_origin
        if hasattr(origin, 'type') and origin.type == 'channel':
            is_channel_forward = True
        # 兼容：检查forward_from_chat
        if hasattr(m, 'forward_from_chat') and m.forward_from_chat:
            if m.forward_from_chat.type == 'channel':
                is_channel_forward = True

    if is_channel_forward:
        try:
            if config.get("ENABLE_MESSAGE_DELETION", False):
                bot.delete_message(chat_id, m.message_id)
            else:
                logger.warning(f"[反频道] ENABLE_MESSAGE_DELETION 未开启，跳过删除消息")
            logger.info(f"反频道删除: chat={chat_id} msg={m.message_id}")
            return True
        except Exception as e:
            logger.error(f"反频道删除失败: {e}")

    return False


def handle_antichannel(bot, m, config, db):
    """处理 /antichannel 命令"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    parts = text.split()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可设置反频道")
            return
    except Exception:
        return

    if len(parts) < 2:
        enabled = _get_settings(db, chat_id)
        status = "开启" if enabled else "关闭"
        bot.reply_to(m, f"📊 反频道转发状态：{status}\n\n用法：/antichannel on/off")
        return

    action = parts[1].lower()
    now_ts = int(time.time())

    if action == "on":
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO anti_channel_settings (chat_id, enabled, ts) VALUES (?,?,?)",
                (chat_id, 1, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, "✅ 反频道转发已开启\n🚫 频道转发消息将被自动删除")
        logger.info(f"反频道开启: chat={chat_id} by={uid}")

    elif action == "off":
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO anti_channel_settings (chat_id, enabled, ts) VALUES (?,?,?)",
                (chat_id, 0, now_ts)
            )
            db.conn.commit()
        bot.reply_to(m, "✅ 反频道转发已关闭")

    else:
        bot.reply_to(m, "用法：/antichannel on/off")
