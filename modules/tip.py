"""打赏/积分转赠模块"""
import time
from datetime import datetime, timezone, timedelta
from core.database import _db_lock
from core.logging_util import get_logger

_CST = timezone(timedelta(hours=8))
logger = get_logger("tip")


def handle_tip(bot, m, config, db, extra=""):
    """打赏其他用户积分 — 回复某人消息发送 '打赏 金额' 或 '打赏 N积分'"""
    # 必须是回复消息
    if not m.reply_to_message:
        bot.reply_to(m, "⚠️ 请回复要打赏的人的消息，再发送 打赏 金额")
        return

    reply_msg = m.reply_to_message
    recipient = reply_msg.from_user
    tipper = m.from_user

    # 不能打赏自己
    if recipient.id == tipper.id:
        bot.reply_to(m, "⚠️ 不能打赏自己哦～")
        return

    # 不能打赏机器人
    if recipient.is_bot:
        bot.reply_to(m, "⚠️ 不能打赏机器人～")
        return

    # 解析金额
    text = m.text.strip()
    # 去掉命令前缀，提取数字部分
    parts = text.split()
    if len(parts) < 2:
        bot.reply_to(m, "⚠️ 格式：打赏 金额（如：打赏 10 或 打赏 10积分）")
        return

    amount_str = parts[1].replace("积分", "").strip()
    try:
        amount = int(amount_str)
    except ValueError:
        bot.reply_to(m, "⚠️ 金额必须是整数")
        return

    if amount < 1:
        bot.reply_to(m, "⚠️ 打赏金额最少为 1 积分")
        return

    # [TRAE SOLO CN] 原子扣款：UPDATE ... WHERE uid=? AND points>=?，避免 TOCTOU 竞态
    with _db_lock:
        cur = db.conn.execute(
            "UPDATE user_levels SET points = points - ? WHERE uid = ? AND points >= ?",
            (amount, tipper.id, amount)
        )
        if cur.rowcount == 0:
            db.conn.rollback()
            tipper_points = db.get_user_points(tipper.id) or 0
            bot.reply_to(m, f"⚠️ 积分不足！你当前有 {tipper_points} 积分，还差 {amount - tipper_points} 积分")
            return
        # 记录积分日志
        try:
            db.conn.execute(
                "INSERT INTO points_log (uid, change_amount, balance_after, source, ts) VALUES (?,?,?,?,?)",
                (tipper.id, -amount, db.get_user_points(tipper.id), "tip", int(time.time()))
            )
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        db.conn.commit()

    # 执行打赏：增加接收者（add_points 内部自带锁与日志）
    _lv_result = db.add_points(recipient.id, amount, source="tip")

    # 群内公告
    tipper_name = tipper.first_name
    recipient_name = recipient.first_name
    bot.reply_to(m, f"🎁 {tipper_name} 打赏了 {recipient_name} {amount} 积分！")

    # 检查接收者升级通知
    from modules.points_enhanced import check_level_up
    check_level_up(bot, m.chat.id, recipient.id, recipient_name, _lv_result, config)

    # 私聊通知接收者
    try:
        bot.send_message(recipient.id, f"🎁 {tipper_name} 打赏了你 {amount} 积分！")
    except Exception as e:
        logger.warning(f"打赏私聊通知失败: uid={recipient.id}, err={e}")


def handle_tip_rank(bot, m, config, db):
    """打赏排行 — 显示收到打赏最多的 TOP10 用户"""
    try:
        conn = db.conn
        cursor = conn.execute(
            "SELECT uid, SUM(change_amount) as total "
            "FROM points_log WHERE source='tip' AND change_amount > 0 "
            "GROUP BY uid ORDER BY total DESC LIMIT 10"
        )
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"查询打赏排行失败: {e}")
        bot.reply_to(m, "⚠️ 查询打赏排行失败，请稍后再试")
        return

    if not rows:
        bot.reply_to(m, "📊 暂无打赏记录")
        return

    lines = ["🏆 打赏排行榜 TOP10", ""]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, total) in enumerate(rows):
        medal = medals[i] if i < 3 else f" {i + 1}."
        # 尝试获取用户名
        try:
            user_info = bot.get_chat_member(m.chat.id, uid)
            name = user_info.user.first_name
        except Exception:
            name = f"用户{uid}"
        lines.append(f"{medal} {name} — {total} 积分")

    bot.reply_to(m, "\n".join(lines))
