"""
提醒系统 - 定时提醒功能

命令：
  /remind 30m 内容 → handle_remind
  /reminders → handle_reminders
  /cancelremind ID → handle_cancel_remind

数据表：reminders（id, uid, chat_id, trigger_ts, content, sent, ts）
"""
import re
import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("reminder")


def _parse_duration(text):
    """解析时间字符串，返回秒数。支持 30m/1h/2d/30s 格式"""
    match = re.match(r'^(\d+)([smhd])$', text.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]


def handle_remind(bot, m, config, db):
    """设置提醒"""
    uid = m.from_user.id
    chat_id = m.chat.id
    text = (m.text or "").strip()
    parts = text.split(None, 2)

    if len(parts) < 3:
        bot.reply_to(m, "❌ 用法：/remind 时间 内容\n💡 时间格式：30s/30m/1h/2d\n示例：/remind 30m 开会")
        return

    duration_str = parts[1]
    content = parts[2]

    seconds = _parse_duration(duration_str)
    if not seconds:
        bot.reply_to(m, "❌ 时间格式错误\n💡 支持：30s/30m/1h/2d")
        return

    if seconds > 86400 * 30:  # 最长30天
        bot.reply_to(m, "❌ 提醒时间不能超过30天")
        return

    trigger_ts = int(time.time()) + seconds
    now_ts = int(time.time())

    with _db_lock:
        cursor = db.conn.execute(
            "INSERT INTO reminders (uid, chat_id, trigger_ts, content, sent, ts) VALUES (?,?,?,?,?,?)",
            (uid, chat_id, trigger_ts, content, 0, now_ts)
        )
        db.conn.commit()
        remind_id = cursor.lastrowid

    # 格式化时间
    if seconds >= 86400:
        time_str = f"{seconds // 86400}天"
    elif seconds >= 3600:
        time_str = f"{seconds // 3600}小时"
    elif seconds >= 60:
        time_str = f"{seconds // 60}分钟"
    else:
        time_str = f"{seconds}秒"

    bot.reply_to(m, f"⏰ 提醒已设置！\n📝 内容：{content}\n⏱ {time_str}后提醒你\n🆔 ID：{remind_id}")
    logger.info(f"提醒设置: uid={uid} id={remind_id} trigger={trigger_ts}")


def handle_reminders(bot, m, config, db):
    """查看提醒列表"""
    uid = m.from_user.id
    now_ts = int(time.time())

    try:
        rows = db.conn.execute(
            "SELECT id, trigger_ts, content FROM reminders WHERE uid=? AND sent=0 ORDER BY trigger_ts",
            (uid,)
        ).fetchall()
    except Exception:
        bot.reply_to(m, "❌ 查询失败")
        return

    if not rows:
        bot.reply_to(m, "📋 暂无待触发提醒")
        return

    from datetime import datetime, timezone, timedelta
    _CST = timezone(timedelta(hours=8))

    lines = ["📋 你的提醒列表：\n"]
    for rid, trigger_ts, content in rows:
        remaining = trigger_ts - now_ts
        if remaining > 0:
            if remaining >= 86400:
                remain_str = f"{remaining // 86400}天后"
            elif remaining >= 3600:
                remain_str = f"{remaining // 3600}小时后"
            elif remaining >= 60:
                remain_str = f"{remaining // 60}分钟后"
            else:
                remain_str = f"{remaining}秒后"
        else:
            remain_str = "即将触发"

        lines.append(f"🆔{rid} | {remain_str} | {content}")

    lines.append("\n💡 取消提醒：/cancelremind ID")
    bot.reply_to(m, "\n".join(lines)[:4000])


def handle_cancel_remind(bot, m, config, db):
    """取消提醒"""
    uid = m.from_user.id
    text = (m.text or "").strip()
    parts = text.split()

    if len(parts) < 2:
        bot.reply_to(m, "❌ 用法：/cancelremind ID")
        return

    try:
        remind_id = int(parts[1])
    except ValueError:
        bot.reply_to(m, "❌ ID必须是数字")
        return

    with _db_lock:
        cur = db.conn.execute(
            "DELETE FROM reminders WHERE id=? AND uid=? AND sent=0",
            (remind_id, uid)
        )
        db.conn.commit()
        removed = cur.rowcount > 0

    if removed:
        bot.reply_to(m, f"✅ 提醒 {remind_id} 已取消")
    else:
        bot.reply_to(m, "❌ 未找到该提醒")


def check_reminders(bot, config, db):
    """检查并触发到期提醒（定时任务调用）"""
    now_ts = int(time.time())

    try:
        rows = db.conn.execute(
            "SELECT id, uid, chat_id, content FROM reminders WHERE sent=0 AND trigger_ts<=?",
            (now_ts,)
        ).fetchall()
    except Exception:
        return

    for rid, uid, chat_id, content in rows:
        try:
            bot.send_message(chat_id, f"⏰ 提醒！\n📝 {content}", reply_to_message_id=None)
            with _db_lock:
                db.conn.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))
                db.conn.commit()
            logger.info(f"提醒触发: id={rid} uid={uid}")
        except Exception as e:
            logger.error(f"提醒触发异常: id={rid} err={e}")
