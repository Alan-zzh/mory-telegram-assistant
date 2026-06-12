"""
审批白名单系统 - 白名单用户免受群组限制

功能：
  1. 添加/移除白名单用户
  2. 白名单用户免受locks/antiflood/blocklist限制
  3. 查看白名单列表

命令：
  /approve @用户 → handle_approve
  /disapprove @用户 → handle_disapprove
  /approved → handle_approved_list

数据表：approved_users（chat_id, uid, approved_by, ts）
"""
import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("approvals")


def is_approved(db, chat_id, uid):
    """检查用户是否在白名单中"""
    try:
        row = db.conn.execute(
            "SELECT 1 FROM approved_users WHERE chat_id=? AND uid=?",
            (chat_id, uid)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def handle_approve(bot, m, config, db):
    """添加白名单用户"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可添加白名单")
            return
    except Exception:
        return

    # 获取目标用户
    target_uid = _extract_target_uid(m, text)
    if not target_uid:
        bot.reply_to(m, "❌ 请指定用户（回复消息或 @用户）")
        return

    # 不能白名单自己
    if target_uid == uid:
        bot.reply_to(m, "❌ 不能添加自己到白名单")
        return

    # 检查是否已在白名单
    if is_approved(db, chat_id, target_uid):
        bot.reply_to(m, "⚠️ 该用户已在白名单中")
        return

    # 添加到白名单
    now_ts = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT OR IGNORE INTO approved_users (chat_id, uid, approved_by, ts) VALUES (?,?,?,?)",
            (chat_id, target_uid, uid, now_ts)
        )
        db.conn.commit()

    # 获取目标用户名
    try:
        target_member = bot.get_chat_member(chat_id, target_uid)
        target_name = target_member.user.first_name or f"用户{target_uid}"
    except Exception:
        target_name = f"用户{target_uid}"

    bot.reply_to(m, f"✅ {target_name} 已加入白名单\n🛡 该用户将免受群组限制")
    logger.info(f"白名单添加: chat={chat_id} target={target_uid} by={uid}")


def handle_disapprove(bot, m, config, db):
    """移除白名单用户"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()

    # 权限检查
    try:
        member = bot.get_chat_member(chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 仅管理员可移除白名单")
            return
    except Exception:
        return

    target_uid = _extract_target_uid(m, text)
    if not target_uid:
        bot.reply_to(m, "❌ 请指定用户（回复消息或 @用户）")
        return

    with _db_lock:
        cur = db.conn.execute(
            "DELETE FROM approved_users WHERE chat_id=? AND uid=?",
            (chat_id, target_uid)
        )
        db.conn.commit()
        removed = cur.rowcount > 0

    if removed:
        try:
            target_member = bot.get_chat_member(chat_id, target_uid)
            target_name = target_member.user.first_name or f"用户{target_uid}"
        except Exception:
            target_name = f"用户{target_uid}"
        bot.reply_to(m, f"✅ {target_name} 已从白名单移除")
        logger.info(f"白名单移除: chat={chat_id} target={target_uid} by={uid}")
    else:
        bot.reply_to(m, "⚠️ 该用户不在白名单中")


def handle_approved_list(bot, m, config, db):
    """查看白名单列表"""
    chat_id = m.chat.id

    try:
        rows = db.conn.execute(
            "SELECT uid, approved_by, ts FROM approved_users WHERE chat_id=?",
            (chat_id,)
        ).fetchall()
    except Exception:
        bot.reply_to(m, "❌ 查询失败")
        return

    if not rows:
        bot.reply_to(m, "📋 当前群白名单为空")
        return

    lines = ["🛡 白名单用户列表\n━━━━━━━━━━━━━"]
    for i, (a_uid, approved_by, ts) in enumerate(rows, 1):
        try:
            member = bot.get_chat_member(chat_id, a_uid)
            name = member.user.first_name or f"用户{a_uid}"
        except Exception:
            name = f"用户{a_uid}"
        lines.append(f"{i}. {name}")

    bot.reply_to(m, "\n".join(lines))


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
        if part.isdigit():
            return int(part)

    return None
