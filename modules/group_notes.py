#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/group_notes.py  ·  群笔记系统                                  ║
║                                                                        ║
║  功能：                                                                ║
║    群内保存/获取/列出/删除笔记，按群隔离。                              ║
║    数据表 group_notes: id, chat_id, note_name, content, created_by, ts  ║
║    UNIQUE(chat_id, note_name)                                          ║
║                                                                        ║
║  被调用：main.py 管理员命令处理                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("group_notes")


def handle_save_note(bot, m, config, db, note_name, content):
    """保存笔记（管理员）"""
    chat_id = m.chat.id
    uid = m.from_user.id
    ts = int(time.time())
    try:
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO group_notes (chat_id, note_name, content, created_by, ts) VALUES (?,?,?,?,?)",
                (chat_id, note_name, content, uid, ts)
            )
            db.conn.commit()
        bot.reply_to(m, f"📝 笔记 '{note_name}' 已保存")
        logger.info(f"📝 笔记保存: chat={chat_id} name={note_name} by={uid}")
    except Exception as e:
        logger.error(f"📝 笔记保存失败: {e}")
        bot.reply_to(m, f"❌ 笔记保存失败：{e}")


def handle_get_note(bot, m, config, db, note_name):
    """获取笔记"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            row = db.conn.execute(
                "SELECT content FROM group_notes WHERE chat_id=? AND note_name=?",
                (chat_id, note_name)
            ).fetchone()
        if row:
            bot.reply_to(m, row[0])
        else:
            bot.reply_to(m, f"❌ 未找到笔记 '{note_name}'")
    except Exception as e:
        logger.error(f"📝 笔记获取失败: {e}")
        bot.reply_to(m, f"❌ 笔记获取失败：{e}")


def handle_notes_list(bot, m, config, db):
    """列出所有笔记"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT note_name FROM group_notes WHERE chat_id=? ORDER BY note_name",
                (chat_id,)
            ).fetchall()
        if not rows:
            bot.reply_to(m, "📝 当前没有保存任何笔记")
        else:
            names = "\n".join(f"• {r[0]}" for r in rows)
            bot.reply_to(m, f"📝 笔记列表（共{len(rows)}条）：\n{names}")
    except Exception as e:
        logger.error(f"📝 笔记列表获取失败: {e}")
        bot.reply_to(m, f"❌ 笔记列表获取失败：{e}")


def handle_del_note(bot, m, config, db, note_name):
    """删除笔记（管理员）"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            cur = db.conn.execute(
                "DELETE FROM group_notes WHERE chat_id=? AND note_name=?",
                (chat_id, note_name)
            )
            db.conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            bot.reply_to(m, f"🗑 笔记 '{note_name}' 已删除")
            logger.info(f"📝 笔记删除: chat={chat_id} name={note_name}")
        else:
            bot.reply_to(m, f"❌ 未找到笔记 '{note_name}'")
    except Exception as e:
        logger.error(f"📝 笔记删除失败: {e}")
        bot.reply_to(m, f"❌ 笔记删除失败：{e}")
