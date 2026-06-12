"""
全局黑名单模块 - 跨群封禁功能

功能：
  1. Bot所有者/超级管理员添加全局黑名单 /gban @user reason
  2. Bot所有者/超级管理员移除全局黑名单 /ungban @user
  3. 新成员入群时检查全局黑名单，自动封禁
  4. 查看全局黑名单列表 /gbanlist

数据表：blacklist（uid, reason, date）
已有方法：core/db_repos/group_repo.py → blacklist_add / blacklist_remove / is_blacklisted
默认：DISABLED（被动功能，仅有条目时才激活）

命令：
  /gban <user_id> [reason]  → handle_gban
  /ungban <user_id>         → handle_ungban
  /gbanlist                 → handle_gban_list

被调用：
  core/handlers/member_handlers.py → check_global_blacklist(bot, m, config, db)
"""
import time

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("global_blacklist")


def _is_super_admin(user_id: int, config: dict) -> bool:
    """检查用户是否为Bot所有者或超级管理员"""
    admin_id = config.get("ADMIN_ID", 0)
    if admin_id and user_id == admin_id:
        return True
    super_admins = config.get("SUPER_ADMINS", [])
    if super_admins and user_id in super_admins:
        return True
    return False


def _extract_target_uid(m, text: str) -> int:
    """从消息中提取目标用户ID"""
    if m.reply_to_message and m.reply_to_message.from_user:
        return m.reply_to_message.from_user.id

    entities = m.entities or []
    for ent in entities:
        if ent.type == "text_mention" and ent.user:
            return ent.user.id

    parts = text.split()
    for part in parts[1:]:
        if part.lstrip("-").isdigit():
            return int(part)

    return 0


def handle_gban(bot, m, config, db):
    """处理 /gban 命令 - 添加全局黑名单"""
    user_id = m.from_user.id

    if not _is_super_admin(user_id, config):
        bot.reply_to(m, "❌ 仅Bot所有者可使用全局封禁")
        return

    text = (m.text or "").strip()
    target_uid = _extract_target_uid(m, text)

    if not target_uid:
        bot.reply_to(m, "❌ 用法：/gban <用户ID/回复消息> [原因]")
        return

    if target_uid == user_id:
        bot.reply_to(m, "❌ 不能封禁自己")
        return

    if _is_super_admin(target_uid, config):
        bot.reply_to(m, "❌ 不能封禁超级管理员")
        return

    parts = text.split()
    reason = " ".join(parts[2:]) if len(parts) > 2 else "全局封禁"
    if m.reply_to_message and len(parts) > 1:
        reason_parts = [p for p in parts[1:] if not p.lstrip("-").isdigit()]
        reason = " ".join(reason_parts) if reason_parts else "全局封禁"

    db.blacklist_add(target_uid, reason)

    target_name = f"用户{target_uid}"
    try:
        chat_id = m.chat.id
        member = bot.get_chat_member(chat_id, target_uid)
        target_name = member.user.first_name or target_name
    except Exception:
        pass

    try:
        from telebot.types import ChatPermissions
        bot.restrict_chat_member(
            m.chat.id,
            target_uid,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception:
        try:
            bot.restrict_chat_member(m.chat.id, target_uid, can_send_messages=False)
        except Exception:
            pass

    bot.reply_to(m, f"✅ 已将 {target_name} 加入全局黑名单\n📝 原因：{reason}")
    logger.warning(f"全局黑名单添加: uid={target_uid} reason={reason} by={user_id}")

    admin_id = config.get("ADMIN_ID", 0)
    if admin_id and admin_id != user_id:
        try:
            bot.send_message(
                admin_id,
                f"🚫 全局黑名单通知\n"
                f"👤 用户：{target_name}（ID: {target_uid}）\n"
                f"📝 原因：{reason}\n"
                f"👮 操作者：{m.from_user.first_name}（ID: {user_id}）"
            )
        except Exception:
            pass


def handle_ungban(bot, m, config, db):
    """处理 /ungban 命令 - 移除全局黑名单"""
    user_id = m.from_user.id

    if not _is_super_admin(user_id, config):
        bot.reply_to(m, "❌ 仅Bot所有者可解除全局封禁")
        return

    text = (m.text or "").strip()
    target_uid = _extract_target_uid(m, text)

    if not target_uid:
        bot.reply_to(m, "❌ 用法：/ungban <用户ID/回复消息>")
        return

    if not db.is_blacklisted(target_uid):
        bot.reply_to(m, f"⚠️ 用户 {target_uid} 不在全局黑名单中")
        return

    db.blacklist_remove(target_uid)

    target_name = f"用户{target_uid}"
    try:
        chat_id = m.chat.id
        member = bot.get_chat_member(chat_id, target_uid)
        target_name = member.user.first_name or target_name
    except Exception:
        pass

    bot.reply_to(m, f"✅ 已将 {target_name} 从全局黑名单移除")
    logger.info(f"全局黑名单移除: uid={target_uid} by={user_id}")


def check_global_blacklist(bot, m, config, db):
    """新成员入群时检查全局黑名单"""
    if not m.new_chat_members:
        return

    chat_id = m.chat.id

    for user in m.new_chat_members:
        if user.is_bot:
            continue

        if not db.is_blacklisted(user.id):
            continue

        user_display = user.first_name or f"用户{user.id}"

        try:
            from telebot.types import ChatPermissions
            bot.restrict_chat_member(
                chat_id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            logger.warning(f"全局黑名单永久禁言: uid={user.id} chat_id={chat_id}")
        except Exception as e:
            try:
                bot.restrict_chat_member(chat_id, user.id, can_send_messages=False)
                logger.warning(f"全局黑名单永久禁言: uid={user.id} chat_id={chat_id}")
            except Exception as inner:
                logger.error(f"全局黑名单禁言失败: uid={user.id} err={inner or e}")

        try:
            bot.send_message(
                chat_id,
                f"🚫 {user_display} 在全局黑名单中，已被永久禁言"
            )
        except Exception:
            pass

        admin_id = config.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(
                    admin_id,
                    f"🚫 全局黑名单拦截通知\n"
                    f"👤 用户：{user_display}（ID: {user.id}）\n"
                    f"📍 群组：{chat_id}\n"
                    f"🔨 操作：已永久禁言"
                )
            except Exception:
                pass


def handle_gban_list(bot, m, config, db):
    """处理 /gbanlist 命令 - 查看全局黑名单"""
    user_id = m.from_user.id

    if not _is_super_admin(user_id, config):
        bot.reply_to(m, "❌ 仅Bot所有者可查看全局黑名单")
        return

    try:
        rows = db.conn.execute(
            "SELECT uid, reason, date FROM blacklist ORDER BY date DESC"
        ).fetchall()
    except Exception as e:
        logger.error(f"查询全局黑名单失败: {e}")
        bot.reply_to(m, "❌ 查询失败")
        return

    if not rows:
        bot.reply_to(m, "📋 全局黑名单为空")
        return

    lines = ["🚫 全局黑名单列表\n━━━━━━━━━━━━━"]
    for i, (uid, reason, ts) in enumerate(rows[:20], 1):
        from datetime import datetime, timezone, timedelta
        _CST = timezone(timedelta(hours=8))
        ban_date = datetime.fromtimestamp(ts, _CST).strftime("%Y-%m-%d %H:%M") if ts else "未知"
        lines.append(f"{i}. UID: {uid}\n   📝 {reason}\n   ⏰ {ban_date}")

    if len(rows) > 20:
        lines.append(f"\n... 共 {len(rows)} 条，仅显示前20条")

    bot.reply_to(m, "\n".join(lines))
