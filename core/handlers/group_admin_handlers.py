# -*- coding: utf-8 -*-
"""
群管命令处理器 - P8.6 高级群管功能命令

包含：
- 警告系统（警告/查看/清除）
- 消息删除（purge/del/purgeto）
- 锁群/解锁/锁定列表
- 慢速模式
- 举报
- 群规
- 用户信息
- 置顶管理
- 投票踢人
- 群组笔记
- 定时消息
- 自定义命令
- 可视化数据面板
"""

from core.logging_util import get_logger, clear_logging_context
from core.handlers.command_handlers import _extract_uid, _get_admin_ids

logger = get_logger("group_admin_handlers")


# ═══════════════════════════════════════════════════════════════════════
#  P8.6：高级群管功能命令
# ═══════════════════════════════════════════════════════════════════════

def handle_group_admin_commands(dctx) -> bool:
    """P8.6 高级群管功能命令（警告/消息删除/锁群/慢速/举报/群规等）

    返回 True 表示命令已处理
    """
    msg = dctx.text
    if not dctx.is_group or not msg:
        return False

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    uid = dctx.uid
    chat_id = dctx.chat_id

    # 警告系统
    if msg.startswith("警告 ") or msg.startswith("/warn "):
        from modules.warning import handle_warn
        parts = msg.split(None, 2)
        target_uid = _extract_uid(parts[1] if len(parts) > 1 else "", m)
        reason = parts[2] if len(parts) > 2 else ""
        if target_uid:
            handle_warn(bot, m, CONFIG, db, target_uid, reason)
        else:
            bot.reply_to(m, "❌ 无法识别目标用户，请回复用户消息或使用 @用户名")
        clear_logging_context()
        return True
    if msg.startswith("查看警告 "):
        from modules.warning import handle_warn_list
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_warn_list(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True
    if msg.startswith("清除警告 "):
        from modules.warning import handle_warn_reset
        target_uid = _extract_uid(msg[5:].strip(), m)
        if target_uid:
            handle_warn_reset(bot, m, CONFIG, db, target_uid)
        clear_logging_context()
        return True

    # 消息删除
    if msg.startswith("/purge ") and m.reply_to_message:
        from modules.message_clean import handle_purge
        handle_purge(bot, m, CONFIG, db, msg[7:].strip())
        clear_logging_context()
        return True
    if msg == "/del" and m.reply_to_message:
        from modules.message_clean import handle_del
        handle_del(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "/purgeto" and m.reply_to_message:
        from modules.message_clean import handle_purge_to
        handle_purge_to(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 锁群
    if msg.startswith("锁 "):
        from modules.message_locks import handle_lock
        handle_lock(bot, m, CONFIG, db, msg[2:].strip())
        clear_logging_context()
        return True
    if msg.startswith("解锁 "):
        from modules.message_locks import handle_unlock
        handle_unlock(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True
    if msg in ("锁定列表", "/locktypes"):
        from modules.message_locks import handle_lock_list
        handle_lock_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 慢速模式
    if msg.startswith("慢速 "):
        from modules.slow_mode import handle_slow_mode
        handle_slow_mode(bot, m, CONFIG, db, msg[3:].strip())
        clear_logging_context()
        return True

    # 举报
    from modules.report import check_report_command, handle_report
    if check_report_command(m):
        handle_report(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 群规
    if msg in ("/rules", "群规"):
        try:
            row = db.conn.execute("SELECT rules_text FROM welcome_configs WHERE chat_id=?", (chat_id,)).fetchone()
            if row and row[0]:
                bot.reply_to(m, f"📋 群规\n\n{row[0]}")
            else:
                bot.reply_to(m, "📋 暂未设置群规，管理员可使用 /setrules 设置")
        except Exception:
            bot.reply_to(m, "📋 暂未设置群规")
        clear_logging_context()
        return True

    # 用户信息
    if msg in ("/info", "/whois") and m.reply_to_message:
        from modules.user_info import handle_user_info
        handle_user_info(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 置顶管理
    if msg == "/pin" and m.reply_to_message:
        try:
            bot.pin_chat_message(chat_id, m.reply_to_message.message_id, disable_notification=True)
            bot.reply_to(m, "📌 已置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 置顶失败：{e}")
        clear_logging_context()
        return True
    if msg == "/unpin":
        try:
            bot.unpin_chat_message(chat_id)
            bot.reply_to(m, "📌 已取消置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 取消置顶失败：{e}")
        clear_logging_context()
        return True
    if msg == "/unpinall":
        try:
            bot.unpin_all_chat_messages(chat_id)
            bot.reply_to(m, "📌 已取消所有置顶")
        except Exception as e:
            bot.reply_to(m, f"❌ 取消所有置顶失败：{e}")
        clear_logging_context()
        return True

    # 投票踢人
    if msg.startswith("/votekick "):
        from modules.vote_kick import handle_vote_kick
        parts = msg.split(None, 2)
        target_uid = _extract_uid(parts[1] if len(parts) > 1 else "", m)
        reason = parts[2] if len(parts) > 2 else ""
        if target_uid:
            handle_vote_kick(bot, m, CONFIG, db, target_uid, reason)
        else:
            bot.reply_to(m, "❌ 无法识别目标用户")
        clear_logging_context()
        return True

    # 群组笔记
    if msg.startswith("#save "):
        from modules.group_notes import handle_save_note
        parts = msg[6:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_save_note(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：#save 笔记名 内容")
        clear_logging_context()
        return True
    if msg.startswith("#get "):
        from modules.group_notes import handle_get_note
        handle_get_note(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg in ("#notes", "#列表"):
        from modules.group_notes import handle_notes_list
        handle_notes_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("#del "):
        from modules.group_notes import handle_del_note
        handle_del_note(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    # #笔记名 快捷获取
    if msg.startswith("#") and len(msg) > 1 and not msg.startswith("#save") and not msg.startswith("#del"):
        from modules.group_notes import handle_get_note
        note_name = msg[1:].strip()
        if note_name and note_name not in ("notes", "列表"):
            handle_get_note(bot, m, CONFIG, db, note_name)
            clear_logging_context()
            return True

    # 定时消息
    if msg.startswith("定时 "):
        from modules.scheduled_msg import handle_schedule_msg
        parts = msg[3:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_schedule_msg(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：定时 HH:MM 内容")
        clear_logging_context()
        return True
    if msg == "定时列表":
        from modules.scheduled_msg import handle_schedule_list
        handle_schedule_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg.startswith("定时删除 "):
        from modules.scheduled_msg import handle_schedule_delete
        handle_schedule_delete(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True

    # 自定义命令
    if msg.startswith("创建命令 "):
        from modules.custom_commands import handle_create_command
        parts = msg[5:].strip().split(None, 1)
        if len(parts) >= 2:
            handle_create_command(bot, m, CONFIG, db, parts[0], parts[1])
        else:
            bot.reply_to(m, "❌ 格式：创建命令 /命令名 回复内容")
        clear_logging_context()
        return True
    if msg.startswith("删除命令 "):
        from modules.custom_commands import handle_delete_command
        handle_delete_command(bot, m, CONFIG, db, msg[5:].strip())
        clear_logging_context()
        return True
    if msg == "命令列表":
        from modules.custom_commands import handle_commands_list
        handle_commands_list(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    # 可视化数据面板
    if msg in ("数据面板", "/dashboard"):
        from modules.visual_dashboard import handle_group_dashboard
        handle_group_dashboard(bot, m, CONFIG, db)
        clear_logging_context()
        return True
    if msg == "我的数据":
        from modules.visual_dashboard import handle_personal_dashboard
        handle_personal_dashboard(bot, m, CONFIG, db)
        clear_logging_context()
        return True

    return False
