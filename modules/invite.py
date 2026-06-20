"""
modules/invite.py · 邀请系统

功能：
  record_invite(db, inviter_uid, invitee_uid, chat_id) - 记录邀请关系，给邀请人加积分
  handle_invite_rank(bot, m, config, db) - 邀请排行TOP10

邀请积分从 config 的 POINTS_PER_INVITE 读取（默认5分）。
"""

import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("invite")

_CST = timezone(timedelta(hours=8))


def record_invite(db, inviter_uid: int, invitee_uid: int, chat_id: int, config=None, bot=None) -> bool:
    """
    记录邀请关系，给邀请人加积分。

    Args:
        db: DB类实例
        inviter_uid: 邀请人UID
        invitee_uid: 被邀请人UID
        chat_id: 发生邀请的群ID

    Returns:
        True=新记录成功，False=重复邀请或失败
    """
    ts = int(time.time())
    try:
        with db.conn:
            c = db.conn.cursor()
            # 防重复：同一邀请人+被邀请人只记一次
            c.execute(
                "SELECT 1 FROM invite_records WHERE inviter_uid=? AND invitee_uid=?",
                (inviter_uid, invitee_uid),
            )
            if c.fetchone():
                logger.debug(f"邀请重复: inviter={inviter_uid} invitee={invitee_uid}")
                return False

            # 写入邀请记录
            c.execute(
                "INSERT INTO invite_records (inviter_uid, invitee_uid, chat_id, ts) VALUES (?,?,?,?)",
                (inviter_uid, invitee_uid, chat_id, ts),
            )
            db.conn.commit()

        # 给邀请人加积分
        try:
            points_per_invite = config.get("POINTS_PER_INVITE", 5) if config else 5
            _lv_result = db.add_points(inviter_uid, points_per_invite, source="invite")
            logger.info(f"邀请积分: inviter={inviter_uid} +{points_per_invite}")
            # 检查升级通知
            if bot and config:
                from modules.points_enhanced import check_level_up
                try:
                    c2 = db.conn.cursor()
                    c2.execute("SELECT name FROM users WHERE uid=?", (inviter_uid,))
                    _row = c2.fetchone()
                    _inviter_name = _row[0] if _row else f"用户{inviter_uid}"
                    check_level_up(bot, chat_id, inviter_uid, _inviter_name, _lv_result, config)
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.error(f"邀请积分发放失败: {e}")

        logger.info(f"邀请记录: inviter={inviter_uid} invitee={invitee_uid} chat={chat_id}")
        return True
    except Exception as e:
        logger.error(f"记录邀请失败: {e}")
        return False


def handle_invite_rank(bot, m, config: dict, db):
    """
    邀请排行TOP10。

    显示邀请人数最多的前10名用户。
    """
    chat_id = m.chat.id
    try:
        with db.conn:
            c = db.conn.cursor()
            c.execute("""
                SELECT ir.inviter_uid, COUNT(*) as invite_count
                FROM invite_records ir
                GROUP BY ir.inviter_uid
                ORDER BY invite_count DESC
                LIMIT 10
            """)
            rows = c.fetchall()

        if not rows:
            bot.send_message(chat_id, "📋 邀请排行榜暂无数据")
            return

        # 查询用户名
        lines = ["🏆 邀请排行榜 TOP10\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, count) in enumerate(rows):
            # 获取用户名
            c2 = db.conn.cursor()
            c2.execute("SELECT name FROM users WHERE uid=?", (uid,))
            user_row = c2.fetchone()
            name = user_row[0] if user_row else f"用户{uid}"

            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} {name} — 邀请了 {count} 人")

        bot.send_message(chat_id, "\n".join(lines))
    except Exception as e:
        logger.error(f"邀请排行查询失败: {e}")
        bot.send_message(chat_id, "❌ 邀请排行查询失败，请稍后再试")
