"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/admin_promote.py  ·  管理员升降职模块                          ║
║                                                                        ║
║  功能：群管理员升降职操作。                                             ║
║                                                                        ║
║  handle_promote()  -> 提升用户为管理员（可配置权限）                     ║
║  handle_demote()   -> 降职管理员为普通成员                              ║
║                                                                        ║
║  配置项（config.json）：                                                ║
║    PROMOTE_PERMISSIONS -> 提升时授予的权限字典，默认全部True             ║
║                                                                        ║
║  数据表：admin_logs（由 core/database.py 创建）                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("admin_promote")

# 默认提升权限：全部开启
_DEFAULT_PERMISSIONS = {
    "can_change_info": True,
    "can_post_messages": True,
    "can_edit_messages": True,
    "can_delete_messages": True,
    "can_invite_users": True,
    "can_restrict_members": True,
    "can_pin_messages": True,
    "can_promote_members": False,
    "can_manage_video_chats": True,
    "can_manage_chat": True,
}


def _log_action(db, chat_id: int, operator_uid: int, target_uid: int, action: str, reason: str = ""):
    """记录管理员操作到admin_logs表"""
    now = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT INTO admin_logs (chat_id, operator_uid, target_uid, action, reason, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, operator_uid, target_uid, action, reason, now),
        )
        db.conn.commit()


def handle_promote(bot, m, config: dict, db, target_uid: int):
    """
    提升用户为管理员。
    权限从 config["PROMOTE_PERMISSIONS"] 读取，未配置则使用默认值。

    Args:
        bot: TeleBot实例
        m: 触发消息
        config: 配置字典
        db: 数据库实例
        target_uid: 被提升目标UID
    """
    chat_id = m.chat.id
    operator_uid = m.from_user.id

    # 合并权限配置：默认值 + 用户自定义覆盖
    perms = {**_DEFAULT_PERMISSIONS, **config.get("PROMOTE_PERMISSIONS", {})}

    try:
        bot.promote_chat_member(
            chat_id,
            target_uid,
            can_change_info=perms.get("can_change_info", True),
            can_post_messages=perms.get("can_post_messages", True),
            can_edit_messages=perms.get("can_edit_messages", True),
            can_delete_messages=perms.get("can_delete_messages", True),
            can_invite_users=perms.get("can_invite_users", True),
            can_restrict_members=perms.get("can_restrict_members", True),
            can_pin_messages=perms.get("can_pin_messages", True),
            can_promote_members=perms.get("can_promote_members", False),
            can_manage_video_chats=perms.get("can_manage_video_chats", True),
            can_manage_chat=perms.get("can_manage_chat", True),
        )
    except Exception as e:
        bot.reply_to(m, f"⚠️ 提升管理员失败：{e}")
        logger.warning("提升管理员失败: chat=%s target=%s error=%s", chat_id, target_uid, e)
        return

    # 记录操作日志
    _log_action(db, chat_id, operator_uid, target_uid, "promote", "提升为管理员")

    target_mention = f"<a href='tg://user?id={target_uid}'>用户</a>"
    bot.send_message(
        chat_id,
        f"⬆️ {target_mention} 已被提升为管理员",
        parse_mode="HTML",
    )
    logger.info("⬆️ 提升管理员: chat=%s target=%s operator=%s", chat_id, target_uid, operator_uid)


def handle_demote(bot, m, config: dict, db, target_uid: int):
    """
    降职管理员为普通成员。
    移除所有管理员权限。

    Args:
        bot: TeleBot实例
        m: 触发消息
        config: 配置字典
        db: 数据库实例
        target_uid: 被降职目标UID
    """
    chat_id = m.chat.id
    operator_uid = m.from_user.id

    try:
        bot.promote_chat_member(
            chat_id,
            target_uid,
            can_change_info=False,
            can_post_messages=False,
            can_edit_messages=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
            can_manage_chat=False,
        )
    except Exception as e:
        bot.reply_to(m, f"⚠️ 降职失败：{e}")
        logger.warning("降职失败: chat=%s target=%s error=%s", chat_id, target_uid, e)
        return

    # 记录操作日志
    _log_action(db, chat_id, operator_uid, target_uid, "demote", "降职为普通成员")

    target_mention = f"<a href='tg://user?id={target_uid}'>用户</a>"
    bot.send_message(
        chat_id,
        f"⬇️ {target_mention} 已被降职为普通成员",
        parse_mode="HTML",
    )
    logger.info("⬇️ 降职管理员: chat=%s target=%s operator=%s", chat_id, target_uid, operator_uid)
