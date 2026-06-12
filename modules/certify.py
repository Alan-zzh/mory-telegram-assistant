"""
modules/certify.py · 认证系统

功能：
  handle_certify(bot, m, config, db, target_uid) - 管理员认证用户
  handle_uncertify(bot, m, config, db, target_uid) - 取消认证
  is_certified(db, uid) - 检查用户是否已认证

认证用户在等级查询时显示 ✅ 认证标识。
"""

import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("certify")

_CST = timezone(timedelta(hours=8))


def is_certified(db, uid: int) -> bool:
    """
    检查用户是否已认证。

    Args:
        db: DB类实例
        uid: 用户ID

    Returns:
        True=已认证，False=未认证
    """
    try:
        c = db.conn.cursor()
        c.execute("SELECT 1 FROM certified_users WHERE uid=?", (uid,))
        return c.fetchone() is not None
    except Exception as e:
        logger.error(f"检查认证状态失败 uid={uid}: {e}")
        return False


def handle_certify(bot, m, config: dict, db, target_uid: int):
    """
    管理员认证用户。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        target_uid: 待认证的用户ID
    """
    chat_id = m.chat.id
    admin_uid = m.from_user.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)

    if admin_uid not in admin_ids:
        bot.send_message(chat_id, "⛔ 只有管理员才能执行认证操作")
        return

    if not target_uid:
        bot.send_message(chat_id, "❌ 请指定要认证的用户ID")
        return

    try:
        ts = int(time.time())
        c = db.conn.cursor()

        # 检查是否已认证
        c.execute("SELECT 1 FROM certified_users WHERE uid=?", (target_uid,))
        if c.fetchone():
            bot.send_message(chat_id, f"⚠️ 用户 {target_uid} 已经是认证用户")
            return

        # 写入认证记录
        c.execute(
            "INSERT INTO certified_users (uid, certified_by, reason, ts) VALUES (?,?,?,?)",
            (target_uid, admin_uid, "", ts),
        )
        db.conn.commit()

        # 获取用户名
        c.execute("SELECT name FROM users WHERE uid=?", (target_uid,))
        user_row = c.fetchone()
        name = user_row[0] if user_row else f"用户{target_uid}"

        bot.send_message(chat_id, f"✅ 已认证用户 {name}（UID: {target_uid}）")
        logger.info(f"认证用户: uid={target_uid} by admin={admin_uid}")
    except Exception as e:
        logger.error(f"认证操作失败: {e}")
        bot.send_message(chat_id, "❌ 认证操作失败，请稍后再试")


def handle_uncertify(bot, m, config: dict, db, target_uid: int):
    """
    管理员取消用户认证。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        target_uid: 待取消认证的用户ID
    """
    chat_id = m.chat.id
    admin_uid = m.from_user.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)

    if admin_uid not in admin_ids:
        bot.send_message(chat_id, "⛔ 只有管理员才能取消认证")
        return

    if not target_uid:
        bot.send_message(chat_id, "❌ 请指定要取消认证的用户ID")
        return

    try:
        c = db.conn.cursor()

        # 检查是否已认证
        c.execute("SELECT 1 FROM certified_users WHERE uid=?", (target_uid,))
        if not c.fetchone():
            bot.send_message(chat_id, f"⚠️ 用户 {target_uid} 不是认证用户")
            return

        # 删除认证记录
        c.execute("DELETE FROM certified_users WHERE uid=?", (target_uid,))
        db.conn.commit()

        # 获取用户名
        c.execute("SELECT name FROM users WHERE uid=?", (target_uid,))
        user_row = c.fetchone()
        name = user_row[0] if user_row else f"用户{target_uid}"

        bot.send_message(chat_id, f"✅ 已取消用户 {name}（UID: {target_uid}）的认证")
        logger.info(f"取消认证: uid={target_uid} by admin={admin_uid}")
    except Exception as e:
        logger.error(f"取消认证操作失败: {e}")
        bot.send_message(chat_id, "❌ 取消认证操作失败，请稍后再试")
