#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/group_info.py  ·  群信息修改模块                                ║
║                                                                        ║
║  功能：修改群标题/描述/头像，管理员专用。                                ║
║                                                                        ║
║  handle_setgtitle()  -> 设置群标题                                      ║
║  handle_setdesc()    -> 设置群描述                                      ║
║  handle_setgpic()    -> 设置群头像（需回复图片消息）                     ║
║                                                                        ║
║  数据表：admin_logs (操作日志)                                          ║
║  被调用：main.py 管理员命令处理                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("group_info")


def _log_admin_action(db, chat_id, operator_uid, action, reason=""):
    """记录管理员操作日志"""
    now = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT INTO admin_logs (chat_id, operator_uid, target_uid, action, reason, ts) VALUES (?,?,?,?,?,?)",
            (chat_id, operator_uid, 0, action, reason, now),
        )
        db.conn.commit()


def handle_setgtitle(bot, m, config, db):
    """设置群标题（管理员）"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    # 解析标题：/setgtitle 新群名
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/setgtitle 新群名")
        return
    title = parts[1].strip()
    try:
        bot.set_chat_title(chat_id, title)
        _log_admin_action(db, chat_id, uid, "setgtitle", title)
        bot.reply_to(m, f"✅ 群标题已修改为：{title}")
        logger.info(f"群标题修改: chat={chat_id} title={title} by={uid}")
    except Exception as e:
        logger.error(f"群标题修改失败: {e}")
        bot.reply_to(m, "❌ 修改群标题失败，请稍后重试或联系管理员")


def handle_setdesc(bot, m, config, db):
    """设置群描述（管理员）"""
    chat_id = m.chat.id
    uid = m.from_user.id
    text = (m.text or "").strip()
    # 解析描述：/setdesc 新描述
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/setdesc 新描述")
        return
    description = parts[1].strip()
    try:
        bot.set_chat_description(chat_id, description)
        _log_admin_action(db, chat_id, uid, "setdesc", description[:100])
        bot.reply_to(m, "✅ 群描述已修改")
        logger.info(f"群描述修改: chat={chat_id} by={uid}")
    except Exception as e:
        logger.error(f"群描述修改失败: {e}")
        bot.reply_to(m, "❌ 修改群描述失败，请稍后重试或联系管理员")


def handle_setgpic(bot, m, config, db):
    """设置群头像（管理员，需回复图片消息）"""
    chat_id = m.chat.id
    uid = m.from_user.id
    # 必须回复一条图片消息
    if not m.reply_to_message or not m.reply_to_message.photo:
        bot.reply_to(m, "❌ 请回复一张图片来设置群头像")
        return
    try:
        # 获取最高分辨率的图片
        photo = m.reply_to_message.photo[-1]
        # 下载图片文件
        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)
        # 设置群头像
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as photo_file:
            bot.set_chat_photo(chat_id, photo_file)
        # 清理临时文件
        import os
        try:
            os.unlink(tmp_path)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        _log_admin_action(db, chat_id, uid, "setgpic", "")
        bot.reply_to(m, "✅ 群头像已修改")
        logger.info(f"群头像修改: chat={chat_id} by={uid}")
    except Exception as e:
        logger.error(f"群头像修改失败: {e}")
        bot.reply_to(m, "❌ 修改群头像失败，请稍后重试或联系管理员")
