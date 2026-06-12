#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/scheduled_msg.py  ·  定时消息系统                              ║
║                                                                        ║
║  功能：                                                                ║
║    群内设置/列出/删除定时消息，每天指定时间自动发送。                    ║
║    数据表 scheduled_messages: id, chat_id, send_time, content,          ║
║                             created_by, ts, enabled                    ║
║                                                                        ║
║  被调用：main.py 管理员命令处理 + APScheduler 定时任务                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
import time
from datetime import datetime, timezone, timedelta
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("scheduled_msg")

_CST = timezone(timedelta(hours=8))


def handle_schedule_msg(bot, m, config, db, time_str, content):
    """设置定时消息（管理员）"""
    # 校验时间格式 HH:MM
    if not re.match(r'^([01]\d|2[0-3]):([0-5]\d)$', time_str):
        bot.reply_to(m, "❌ 时间格式错误，请使用 HH:MM（24小时制，如 09:30）")
        return

    chat_id = m.chat.id
    uid = m.from_user.id
    ts = int(time.time())
    try:
        with _db_lock:
            db.conn.execute(
                "INSERT INTO scheduled_messages (chat_id, send_time, content, created_by, ts, enabled) VALUES (?,?,?,?,?,1)",
                (chat_id, time_str, content, uid, ts)
            )
            db.conn.commit()
        bot.reply_to(m, f"⏰ 定时消息已设置：每天 {time_str} 发送")
        logger.info(f"⏰ 定时消息设置: chat={chat_id} time={time_str} by={uid}")
    except Exception as e:
        logger.error(f"⏰ 定时消息设置失败: {e}")
        bot.reply_to(m, f"❌ 定时消息设置失败：{e}")


def handle_schedule_list(bot, m, config, db):
    """列出定时消息"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT id, send_time, content FROM scheduled_messages WHERE chat_id=? AND enabled=1 ORDER BY send_time",
                (chat_id,)
            ).fetchall()
        if not rows:
            bot.reply_to(m, "⏰ 当前没有定时消息")
        else:
            lines = []
            for r in rows:
                preview = r[2][:50] + "..." if len(r[2]) > 50 else r[2]
                lines.append(f"#{r[0]} · {r[1]} · {preview}")
            text = "\n".join(lines)
            bot.reply_to(m, f"⏰ 定时消息列表（共{len(rows)}条）：\n{text}")
    except Exception as e:
        logger.error(f"⏰ 定时消息列表获取失败: {e}")
        bot.reply_to(m, f"❌ 定时消息列表获取失败：{e}")


def handle_schedule_delete(bot, m, config, db, schedule_id):
    """删除定时消息（管理员）"""
    chat_id = m.chat.id
    try:
        with _db_lock:
            cur = db.conn.execute(
                "DELETE FROM scheduled_messages WHERE id=? AND chat_id=?",
                (schedule_id, chat_id)
            )
            db.conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            bot.reply_to(m, "🗑 定时消息已删除")
            logger.info(f"⏰ 定时消息删除: chat={chat_id} id={schedule_id}")
        else:
            bot.reply_to(m, "❌ 未找到该定时消息")
    except Exception as e:
        logger.error(f"⏰ 定时消息删除失败: {e}")
        bot.reply_to(m, f"❌ 定时消息删除失败：{e}")


def run_scheduled_messages(bot, config, db):
    """执行定时消息（由APScheduler每分钟调用）"""
    now = datetime.now(_CST)
    current_time = now.strftime("%H:%M")
    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT id, chat_id, content FROM scheduled_messages WHERE send_time=? AND enabled=1",
                (current_time,)
            ).fetchall()
        if not rows:
            return

        success = 0
        fail = 0
        for row in rows:
            msg_id, chat_id, content = row
            try:
                bot.send_message(chat_id, content)
                success += 1
                logger.info(f"⏰ 定时消息发送: id={msg_id} chat={chat_id}")
            except Exception as e:
                fail += 1
                logger.warning(f"⏰ 定时消息发送失败: id={msg_id} chat={chat_id} err={e}")

        logger.info(f"⏰ 定时消息执行完毕: 成功={success} 失败={fail} 当前时间={current_time}")
    except Exception as e:
        logger.error(f"⏰ 定时消息执行异常: {e}")
