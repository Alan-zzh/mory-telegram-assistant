import time
from datetime import datetime, timezone, timedelta
from core.database import _db_lock
from core.logging_util import get_logger

_CST = timezone(timedelta(hours=8))
logger = get_logger("afk")


def _format_duration(ts):
    """将时间戳格式化为可读时长"""
    now = time.time()
    delta = int(now - ts)
    if delta < 60:
        return "不到1分钟"
    minutes = delta // 60
    hours = minutes // 60
    days = hours // 24
    if days > 0:
        remain_hours = hours % 24
        return f"{days}天{remain_hours}小时" if remain_hours else f"{days}天"
    if hours > 0:
        remain_minutes = minutes % 60
        return f"{hours}小时{remain_minutes}分钟" if remain_minutes else f"{hours}小时"
    return f"{minutes}分钟"


def is_afk(db, uid):
    """检查用户是否处于AFK状态，返回 (is_afk, reason, ts)"""
    try:
        row = db.conn.execute(
            "SELECT reason, ts FROM afk_status WHERE uid = ?", (uid,)
        ).fetchone()
        if row:
            return True, row[0], row[1]
        return False, None, None
    except Exception as e:
        logger.error(f"查询AFK状态失败: {e}")
        return False, None, None


def handle_set_afk(bot, m, config, db, reason=None):
    """设置AFK状态"""
    uid = m.from_user.id
    username = m.from_user.first_name
    text = m.text or m.caption or ""
    if reason is None:
        # 去掉命令部分，提取原因
        parts = text.split(None, 1)
        reason = parts[1].strip() if len(parts) > 1 else "未说明"

    with _db_lock:
        try:
            db.conn.execute(
                "INSERT OR REPLACE INTO afk_status (uid, reason, ts) VALUES (?, ?, ?)",
                (uid, reason, time.time()),
            )
            db.conn.commit()
        except Exception as e:
            logger.error(f"设置AFK状态失败: {e}")
            return

    bot.reply_to(m, f"💤 {username} 已进入AFK状态\n📝 原因：{reason}")
    logger.info(f"用户 {uid}({username}) 设置AFK: {reason}")


def check_afk_on_message(bot, m, config, db):
    """检查AFK用户发送消息时自动解除AFK"""
    uid = m.from_user.id
    username = m.from_user.first_name

    afk, reason, ts = is_afk(db, uid)
    if not afk:
        return

    duration = _format_duration(ts)
    with _db_lock:
        try:
            db.conn.execute("DELETE FROM afk_status WHERE uid = ?", (uid,))
            db.conn.commit()
        except Exception as e:
            logger.error(f"解除AFK状态失败: {e}")
            return

    bot.reply_to(m, f"👋 {username} 回来了！离开了 {duration}")
    logger.info(f"用户 {uid}({username}) 自动解除AFK，离开了 {duration}")


def check_afk_mention(bot, m, config, db, mentioned_uid):
    """检查被提及的用户是否AFK"""
    afk, reason, ts = is_afk(db, mentioned_uid)
    if not afk:
        return

    # 获取被提及用户的名称
    try:
        chat_member = bot.get_chat_member(m.chat.id, mentioned_uid)
        username = chat_member.user.first_name
    except Exception:
        username = str(mentioned_uid)

    duration = _format_duration(ts)
    bot.reply_to(m, f"💤 {username} 正在AFK\n📝 原因：{reason}\n⏰ 已离开：{duration}")
