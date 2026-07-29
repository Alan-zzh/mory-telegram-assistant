#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/remote_connect.py  ·  远程群管理模块                            ║
║                                                                        ║
║  功能：通过私聊远程管理群组，仅管理员可用。                              ║
║                                                                        ║
║  handle_connect()        -> 连接到群组                                  ║
║  handle_disconnect()     -> 断开连接                                    ║
║  get_connected_chat()    -> 获取用户连接的群组（工具函数）               ║
║  handle_remote_message() -> 转发私聊消息到已连接的群组                   ║
║                                                                        ║
║  数据表：connected_chats (uid, chat_id, ts)                             ║
║  被调用：main.py 私聊消息处理                                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("remote_connect")


def get_connected_chat(db, uid: int):
    """获取用户连接的群组chat_id，未连接返回None"""
    with _db_lock:
        row = db.conn.execute(
            "SELECT chat_id FROM connected_chats WHERE uid=?",
            (uid,),
        ).fetchone()
    return row[0] if row else None


def handle_connect(bot, m, config, db):
    """连接到群组（仅私聊，仅管理员）"""
    # 仅私聊可用
    if m.chat.type != "private":
        bot.reply_to(m, "❌ 此命令仅在私聊中使用")
        return

    uid = m.from_user.id
    text = (m.text or "").strip()
    # 解析：/connect CHAT_ID
    parts = text.split()
    if len(parts) < 2:
        bot.reply_to(m, "❌ 用法：/connect 群组ID\n💡 群组ID为负数，如 -1001234567890")
        return

    try:
        target_chat_id = int(parts[1])
    except ValueError:
        bot.reply_to(m, "❌ 群组ID格式错误，应为数字（如 -1001234567890）")
        return

    # 验证用户在该群是管理员
    try:
        member = bot.get_chat_member(target_chat_id, uid)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "❌ 你在该群组中不是管理员，无法连接")
            return
    except Exception as e:
        logger.warning(f"验证群管理员失败: chat={target_chat_id} uid={uid} err={e}")
        bot.reply_to(m, "❌ 无法验证群组权限，请稍后重试或联系管理员")
        return

    # 写入连接记录
    now = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT OR REPLACE INTO connected_chats (uid, chat_id, ts) VALUES (?,?,?)",
            (uid, target_chat_id, now),
        )
        db.conn.commit()

    # 获取群名
    try:
        chat_info = bot.get_chat(target_chat_id)
        chat_title = getattr(chat_info, "title", str(target_chat_id)) or str(target_chat_id)
    except Exception:
        chat_title = str(target_chat_id)

    bot.reply_to(m, f"✅ 已连接到群组：{chat_title}（{target_chat_id}）\n💡 你发送的消息将转发到该群组")
    logger.info(f"远程连接: uid={uid} chat={target_chat_id}")


def handle_disconnect(bot, m, config, db):
    """断开群组连接"""
    if m.chat.type != "private":
        bot.reply_to(m, "❌ 此命令仅在私聊中使用")
        return

    uid = m.from_user.id
    with _db_lock:
        cur = db.conn.execute(
            "DELETE FROM connected_chats WHERE uid=?",
            (uid,),
        )
        db.conn.commit()
        deleted = cur.rowcount > 0

    if deleted:
        bot.reply_to(m, "✅ 已断开群组连接")
        logger.info(f"远程断开: uid={uid}")
    else:
        bot.reply_to(m, "❌ 你当前没有连接任何群组")


def handle_remote_message(bot, m, config, db):
    """将私聊消息转发到已连接的群组"""
    # 仅私聊
    if m.chat.type != "private":
        return

    uid = m.from_user.id
    chat_id = get_connected_chat(db, uid)
    if not chat_id:
        return  # 未连接，静默忽略

    try:
        # 复制消息到群组（保留原始类型：文本/图片/文件等）
        bot.copy_message(chat_id, m.chat.id, m.message_id)
    except Exception as e:
        logger.warning(f"远程消息转发失败: uid={uid} chat={chat_id} err={e}")
        try:
            bot.send_message(uid, "❌ 消息转发失败，请稍后重试或联系管理员")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
