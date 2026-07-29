#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/custom_commands.py  ·  自定义命令系统                          ║
║                                                                        ║
║  功能：                                                                ║
║    群内创建/删除/列出/匹配自定义命令，按群隔离。                        ║
║    数据表 custom_commands: id, chat_id, cmd_name, response,             ║
║                          created_by, ts  UNIQUE(chat_id, cmd_name)     ║
║                                                                        ║
║  被调用：main.py 管理员命令处理 + 消息处理流程                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.database import _db_lock
from core.logging_util import get_logger
from core.admin_utils import is_admin_user

logger = get_logger("custom_commands")


def handle_create_command(bot, m, config, db, cmd_name, response):
    """创建自定义命令（管理员）"""
    # 【P2-3 安全加固】防御性权限校验：即便调用方未拦截，也强制要求管理员
    if not is_admin_user(config, m.from_user.id):
        bot.reply_to(m, "⛔ 仅管理员可操作")
        return
    # 确保命令名以 / 开头
    if not cmd_name.startswith("/"):
        cmd_name = "/" + cmd_name

    chat_id = m.chat.id
    uid = m.from_user.id
    ts = int(time.time())
    try:
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO custom_commands (chat_id, cmd_name, response, created_by, ts) VALUES (?,?,?,?,?)",
                (chat_id, cmd_name, response, uid, ts)
            )
            db.conn.commit()
        bot.reply_to(m, f"✅ 命令 {cmd_name} 已创建")
        logger.info(f"⚙️ 自定义命令创建: chat={chat_id} cmd={cmd_name} by={uid}")
    except Exception as e:
        logger.error(f"⚙️ 自定义命令创建失败: {e}")
        bot.reply_to(m, "❌ 命令创建失败，请稍后重试或联系管理员")


def handle_delete_command(bot, m, config, db, cmd_name):
    """删除自定义命令（管理员）"""
    # 【P2-3 安全加固】防御性权限校验：即便调用方未拦截，也强制要求管理员
    if not is_admin_user(config, m.from_user.id):
        bot.reply_to(m, "⛔ 仅管理员可操作")
        return
    if not cmd_name.startswith("/"):
        cmd_name = "/" + cmd_name

    chat_id = m.chat.id
    try:
        with _db_lock:
            cur = db.conn.execute(
                "DELETE FROM custom_commands WHERE chat_id=? AND cmd_name=?",
                (chat_id, cmd_name)
            )
            db.conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            bot.reply_to(m, f"🗑 命令 {cmd_name} 已删除")
            logger.info(f"⚙️ 自定义命令删除: chat={chat_id} cmd={cmd_name}")
        else:
            bot.reply_to(m, f"❌ 未找到命令 {cmd_name}")
    except Exception as e:
        logger.error(f"⚙️ 自定义命令删除失败: {e}")
        bot.reply_to(m, "❌ 命令删除失败，请稍后重试或联系管理员")


def handle_commands_list(bot, m, config, db):
    """列出自定义命令"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT cmd_name, response FROM custom_commands WHERE chat_id=? ORDER BY cmd_name",
                (chat_id,)
            ).fetchall()
        if not rows:
            bot.reply_to(m, "⚙️ 当前没有自定义命令")
        else:
            lines = []
            for r in rows:
                preview = r[1][:50] + "..." if len(r[1]) > 50 else r[1]
                lines.append(f"• {r[0]} → {preview}")
            text = "\n".join(lines)
            bot.reply_to(m, f"⚙️ 自定义命令列表（共{len(rows)}条）：\n{text}")
    except Exception as e:
        logger.error(f"⚙️ 自定义命令列表获取失败: {e}")
        bot.reply_to(m, "❌ 命令列表获取失败，请稍后重试或联系管理员")


def check_custom_command(bot, m, config, db):
    """检查消息是否匹配自定义命令，匹配则回复并返回True"""
    text = getattr(m, 'text', '') or ''
    if not text.startswith("/"):
        return False

    # 提取命令名（去掉@botname后缀和参数）
    cmd_name = text.split()[0].split("@")[0]
    chat_id = m.chat.id

    try:
        with _db_lock:
            row = db.conn.execute(
                "SELECT response FROM custom_commands WHERE chat_id=? AND cmd_name=?",
                (chat_id, cmd_name)
            ).fetchone()
        if row:
            bot.reply_to(m, row[0])
            logger.info(f"⚙️ 自定义命令命中: chat={chat_id} cmd={cmd_name}")
            return True
        return False
    except Exception as e:
        logger.error(f"⚙️ 自定义命令检查失败: {e}")
        return False
