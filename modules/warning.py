"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/warning.py  ·  群警告系统                                      ║
║                                                                        ║
║  功能：群组成员警告管理。                                               ║
║                                                                        ║
║  handle_warn()        -> 警告用户，达到上限自动禁言/踢出                ║
║  handle_warn_list()   -> 查看用户警告记录                               ║
║  handle_warn_reset()  -> 清除用户所有警告                               ║
║  get_warning_count()  -> 获取用户警告数（工具函数）                      ║
║                                                                        ║
║  配置项（config.json）：                                                ║
║    WARN_LIMIT        -> 警告上限，默认3                                 ║
║    WARN_ACTION       -> 达上限动作 "mute"或"kick"，默认"mute"           ║
║    WARN_MUTE_DURATION -> 禁言时长（秒），默认3600                       ║
║                                                                        ║
║  数据表：warnings (uid, chat_id, reason, warned_by, ts)                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("warning")

_CST = timezone(timedelta(hours=8))


def get_warning_count(db, uid: int, chat_id: int) -> int:
    """获取用户在本群的警告次数"""
    with _db_lock:
        row = db.conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE uid=? AND chat_id=?",
            (uid, chat_id),
        ).fetchone()
    return row[0] if row else 0


def handle_warn(bot, m, config: dict, db, target_uid: int, reason: str):
    """
    警告用户。
    记录警告 → 计数 → 达上限自动执行动作 → 回复 → 尝试私聊通知。
    """
    chat_id = m.chat.id
    warned_by = m.from_user.id
    now = int(time.time())

    # 写入警告记录
    with _db_lock:
        db.conn.execute(
            "INSERT INTO warnings (uid, chat_id, reason, warned_by, ts) VALUES (?,?,?,?,?)",
            (target_uid, chat_id, reason, warned_by, now),
        )
        db.conn.commit()
        count = db.conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE uid=? AND chat_id=?",
            (target_uid, chat_id),
        ).fetchone()[0]

    limit = config.get("WARN_LIMIT", 3)
    action = config.get("WARN_ACTION", "mute")
    mute_duration = config.get("WARN_MUTE_DURATION", 3600)

    # 达到上限 → 自动执行动作
    if count >= limit:
        try:
            if action == "kick":
                bot.kick_chat_member(chat_id, target_uid)
                auto_msg = f"⚠️ 警告达上限({count}/{limit})，已踢出群聊。"
            else:
                bot.restrict_chat_member(
                    chat_id,
                    target_uid,
                    until_date=int(time.time()) + mute_duration,
                    can_send_messages=False,
                )
                mins = mute_duration // 60
                auto_msg = f"⚠️ 警告达上限({count}/{limit})，已禁言{mins}分钟。"
        except Exception as e:
            auto_msg = f"⚠️ 警告达上限({count}/{limit})，自动{action}未生效，请联系管理员处理"
            logger.warning("自动%s失败: %s", action, e)
    else:
        auto_msg = ""

    # 构造回复
    target_mention = f"<a href='tg://user?id={target_uid}'>用户</a>"
    reply = f"⚠️ {target_mention} 收到警告 ({count}/{limit})\n原因：{reason}"
    if auto_msg:
        reply += f"\n{auto_msg}"
    else:
        # 未达上限时提示上限与申诉渠道；达上限时 auto_msg 已含相关信息，不重复
        reply += f"\n⚠️ 警告上限 {limit} 次，达上限将自动{action}。如认为误判，请联系群管理员。"

    try:
        bot.send_message(chat_id, reply, parse_mode="HTML")
    except Exception as e:
        logger.warning("发送警告消息失败: %s", e)

    # 尝试私聊通知被警告用户
    try:
        pm_text = f"你在群组中收到一条警告 ({count}/{limit})\n原因：{reason}"
        if auto_msg:
            pm_text += f"\n{auto_msg}"
        bot.send_message(target_uid, pm_text)
    except Exception as e:
        logger.debug(f"私聊通知失败: {e}")  # 私聊失败（用户屏蔽了私聊）属正常情况，静默忽略


def handle_warn_list(bot, m, config: dict, db, target_uid: int):
    """查看用户在本群的所有警告记录"""
    chat_id = m.chat.id

    with _db_lock:
        rows = db.conn.execute(
            "SELECT reason, warned_by, ts FROM warnings WHERE uid=? AND chat_id=? ORDER BY ts",
            (target_uid, chat_id),
        ).fetchall()

    if not rows:
        bot.reply_to(m, "该用户没有警告记录。")
        return

    lines = [f"📋 警告记录 ({len(rows)}条)："]
    for i, (reason, warned_by, ts) in enumerate(rows, 1):
        t = datetime.fromtimestamp(ts, tz=_CST).strftime("%Y-%m-%d %H:%M")
        lines.append(f"{i}. [{t}] {reason} (by {warned_by})")

    bot.reply_to(m, "\n".join(lines))


def handle_warn_reset(bot, m, config: dict, db, target_uid: int):
    """清除用户在本群的所有警告"""
    chat_id = m.chat.id

    with _db_lock:
        count = db.conn.execute(
            "SELECT COUNT(*) FROM warnings WHERE uid=? AND chat_id=?",
            (target_uid, chat_id),
        ).fetchone()[0]
        db.conn.execute(
            "DELETE FROM warnings WHERE uid=? AND chat_id=?",
            (target_uid, chat_id),
        )
        db.conn.commit()

    bot.reply_to(m, f"已清除该用户的 {count} 条警告记录。")
