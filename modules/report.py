# -*- coding: utf-8 -*-
"""
modules/report.py · 举报/标记系统

功能：
  handle_report(bot, m, config, db) - 举报消息给管理员
  check_report_command(msg) - 检查消息是否为举报命令

命令：
  回复消息 + @admin 或 /report → 举报该消息

被调用：main.py 消息处理流程
"""

import time
from core.logging_util import get_logger

logger = get_logger("report")

# 内存冷却字典：{uid: last_report_timestamp}
_report_cooldown = {}

# 冷却时间（秒）
_COOLDOWN_SECONDS = 300  # 5分钟

# 冷却字典最大条目数（防止内存泄漏）
_MAX_COOLDOWN_ENTRIES = 10000


def check_report_command(msg) -> bool:
    """检查消息是否为举报命令

    只有在回复一条消息时，且文本为 @admin 或 /report 才算举报命令。

    Args:
        msg: Telegram消息对象

    Returns:
        True=是举报命令，False=不是
    """
    if not msg.reply_to_message:
        return False
    text = (msg.text or "").strip()
    return text in ("@admin", "/report")


def handle_report(bot, m, config, db):
    """举报消息给管理员

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
    """
    # 必须回复一条消息
    if not m.reply_to_message:
        bot.reply_to(m, "请回复一条消息来举报")
        return

    reporter = m.from_user
    uid = reporter.id
    now = time.time()

    # 冷却检查
    last_time = _report_cooldown.get(uid, 0)
    if now - last_time < _COOLDOWN_SECONDS:
        bot.reply_to(m, "举报冷却中，请5分钟后再试")
        return

    # 更新冷却时间
    _report_cooldown[uid] = now

    # 防内存泄漏：超出最大条目数时移除最早的1/3条目
    if len(_report_cooldown) > _MAX_COOLDOWN_ENTRIES:
        sorted_items = sorted(_report_cooldown.items(), key=lambda x: x[1])
        evict_count = len(sorted_items) // 3
        for evict_uid, _ in sorted_items[:evict_count]:
            del _report_cooldown[evict_uid]
        logger.info(f"🧹 举报冷却字典超出上限，已清理 {evict_count} 条旧记录")

    # 收集管理员ID
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)

    if not admin_ids:
        bot.reply_to(m, "❌ 未配置管理员，无法举报")
        logger.warning("举报失败：未配置管理员ID")
        return

    # 获取被举报消息的信息
    reported_msg = m.reply_to_message
    reported_user = reported_msg.from_user
    reported_text = (reported_msg.text or reported_msg.caption or "")[:200]
    chat_name = m.chat.title or str(m.chat.id)

    # 举报人信息
    reporter_name = reporter.first_name or str(uid)
    if reporter.last_name:
        reporter_name += f" {reporter.last_name}"

    # 被举报用户信息
    if reported_user:
        reported_name = reported_user.first_name or str(reported_user.id)
        if reported_user.last_name:
            reported_name += f" {reported_user.last_name}"
        reported_uid = reported_user.id
    else:
        reported_name = "未知用户"
        reported_uid = 0

    # 构建通知文本
    notify_text = (
        f"🚨 <b>收到举报</b>\n"
        f"━━━━━━━━━━━━━\n"
        f"📢 举报人：{reporter_name}（ID: <code>{uid}</code>）\n"
        f"👤 被举报人：{reported_name}（ID: <code>{reported_uid}</code>）\n"
        f"💬 群组：{chat_name}\n"
        f"📝 被举报内容：\n<code>{reported_text}</code>"
    )

    # 私信通知每位管理员
    success_count = 0
    for admin_uid in admin_ids:
        try:
            bot.send_message(admin_uid, notify_text, parse_mode="HTML")
            success_count += 1
        except Exception as e:
            logger.warning(f"举报通知发送失败 admin={admin_uid}: {e}")

    # 回复举报人
    if success_count > 0:
        bot.reply_to(m, "已通知管理员，感谢你的举报")
        logger.info(f"举报处理完成: reporter={uid} reported={reported_uid} chat={chat_name} notified={success_count}")
    else:
        bot.reply_to(m, "❌ 通知管理员失败，请稍后再试")
        logger.error(f"举报通知全部失败: reporter={uid} reported={reported_uid}")
