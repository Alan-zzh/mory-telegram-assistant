# -*- coding: utf-8 -*-
"""
双向中继通信处理器 - 用户私聊转发给管理员 + 管理员回复转发给用户

当 RELAY_MODE_ENABLED=true 时：
1. 用户私聊 Bot → 消息转发给管理员（含可点击用户链接）
2. 管理员回复转发消息 → Bot 将回复发送给原用户
3. AI 回复（私聊+群聊）→ 转发给管理员可见
"""

from core.logging_util import get_logger
from core.helpers import format_user_mention

logger = get_logger("relay_handler")


def handle_user_to_admin(bot, db, CONFIG, uid, uname, msg, chat_id, source_type='private'):
    """转发用户消息给管理员 + 写入 relay_sessions

    Args:
        bot: Telebot实例
        db: DB实例
        CONFIG: 配置字典
        uid: 用户ID
        uname: 用户名
        msg: 消息文本
        chat_id: 原始chat ID
        source_type: 'private' 或 'group'

    Returns:
        bool: 是否成功转发
    """
    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if not admin_id or uid == admin_id:
            return False

        # 截断消息防止过长
        msg_display = msg[:500] + "..." if len(msg) > 500 else msg
        # HTML转义消息内容
        safe_msg = msg_display.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        source_label = "私聊" if source_type == "private" else "群聊"
        text = (
            f"📩 {source_label}中继\n"
            f"👤 {format_user_mention(uid, uname)}\n"
            f"💬 {safe_msg}"
        )

        sent = bot.send_message(admin_id, text, parse_mode="HTML")

        # 写入 relay_sessions 记录
        db.save_session(
            admin_chat_id=admin_id,
            admin_msg_id=sent.message_id,
            user_id=uid,
            user_chat_id=chat_id,
            source_type=source_type,
        )

        logger.info(f"📩 中继转发：uid={uid} type={source_type}")
        return True

    except Exception as e:
        logger.warning(f"中继转发失败 uid={uid}：{e}")
        return False


def handle_admin_reply(bot, db, CONFIG, message):
    """处理管理员回复中继消息

    当管理员回复（reply_to）Bot 转发的中继消息时：
    1. 从 relay_sessions 查找原始用户信息
    2. 将管理员回复发送给原用户
    3. 在用户端消息前标注 [管理员回复]

    Args:
        bot: Telebot实例
        db: DB实例
        CONFIG: 配置字典
        message: 管理员的消息对象

    Returns:
        bool: 是否成功处理（True=已处理，False=非中继消息或处理失败）
    """
    try:
        # 检查是否为回复消息
        if not message.reply_to_message:
            return False

        admin_id = CONFIG.get("ADMIN_ID", 0)
        admin_ids = set(CONFIG.get("ADMIN_IDS", []) or [])
        if admin_id:
            admin_ids.add(admin_id)

        # 仅管理员可回复
        if message.from_user.id not in admin_ids:
            return False

        # 从 relay_sessions 查找原始用户
        session = db.find_by_admin_msg(
            admin_chat_id=message.chat.id,
            admin_msg_id=message.reply_to_message.message_id,
        )

        if not session:
            return False  # 非中继消息，静默忽略

        user_id = session["user_id"]
        user_chat_id = session["user_chat_id"]
        source_type = session.get("source_type", "private")

        # 获取管理员回复文本
        reply_text = message.text or ""
        if not reply_text:
            return False

        # 发送给原用户
        prefix = "[管理员回复] "
        sent = bot.send_message(user_chat_id, f"{prefix}{reply_text}")

        # 通知管理员发送成功
        source_label = "私聊" if source_type == "private" else "群聊"
        bot.send_message(
            admin_id,
            f"✅ 已转发给 {format_user_mention(user_id, '用户')}（{source_label}）",
            parse_mode="HTML",
        )

        logger.info(f"📩 管理员中继回复：uid={user_id} chat={user_chat_id} type={source_type}")
        return True

    except Exception as e:
        logger.warning(f"管理员中继回复处理失败：{e}")
        return False


def forward_ai_reply_to_admin(bot, db, CONFIG, uid, uname, resp, chat_id, source_type='private', group_name=''):
    """将 AI 回复转发给管理员（中继模式开启时）

    Args:
        bot: Telebot实例
        db: DB实例
        CONFIG: 配置字典
        uid: 用户ID
        uname: 用户名
        resp: AI回复文本
        chat_id: 原始chat ID
        source_type: 'private' 或 'group'
        group_name: 群名（群聊时使用）

    Returns:
        bool: 是否成功转发
    """
    try:
        admin_id = CONFIG.get("ADMIN_ID", 0)
        if not admin_id or uid == admin_id:
            return False

        # 截断回复防止过长
        resp_display = resp[:500] + "..." if len(resp) > 500 else resp
        safe_resp = resp_display.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if source_type == 'group':
            safe_group = group_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:30] if group_name else "群聊"
            text = (
                f"🤖 AI回复（群聊：{safe_group}）\n"
                f"👤 {format_user_mention(uid, uname)}\n"
                f"💬 {safe_resp}"
            )
        else:
            text = (
                f"🤖 AI回复\n"
                f"👤 {format_user_mention(uid, uname)}\n"
                f"💬 {safe_resp}"
            )

        sent = bot.send_message(admin_id, text, parse_mode="HTML")

        # 写入 relay_sessions（私聊场景，让管理员可以回复）
        if source_type == 'private':
            db.save_session(
                admin_chat_id=admin_id,
                admin_msg_id=sent.message_id,
                user_id=uid,
                user_chat_id=chat_id,
                source_type=source_type,
            )

        logger.debug(f"🤖 AI回复转发：uid={uid} type={source_type}")
        return True

    except Exception as e:
        logger.warning(f"AI回复转发失败 uid={uid}：{e}")
        return False
