# -*- coding: utf-8 -*-
"""
modules/user_info.py · 用户信息查询

功能：
  handle_user_info(bot, m, config, db) - 查看用户详细信息

命令：
  回复用户消息 + 用户信息 / info → 查看被回复者的详细信息

数据表：
  users           → first_seen, last_active, group_messages
  user_levels     → level, points
  warnings        → 警告次数（按chat_id过滤）
  certified_users → 是否认证
  user_tags       → 标签
  speech_daily    → 今日发言数

被调用：main.py 消息处理流程
"""

from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.database import _db_lock

logger = get_logger("user_info")

_CST = timezone(timedelta(hours=8))

# 等级称号映射（与profile_card模块保持一致）
_DEFAULT_LEVEL_TITLES = {"1": "萌新", "2": "常客", "3": "达人", "4": "大佬"}


def _get_level_title(level: int, config: dict) -> str:
    """获取等级称号，优先从config读取，回退到默认"""
    titles = config.get("LEVEL_TITLES", _DEFAULT_LEVEL_TITLES)
    return titles.get(str(level), _DEFAULT_LEVEL_TITLES.get(str(level), "未知"))


def handle_user_info(bot, m, config, db):
    """查看用户详细信息

    必须回复一条用户消息才能使用。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
    """
    # 必须回复一条消息
    if not m.reply_to_message or not m.reply_to_message.from_user:
        bot.reply_to(m, "请回复用户消息查看信息")
        return

    target = m.reply_to_message.from_user
    uid = target.id
    chat_id = m.chat.id

    # 基本信息
    user_name = target.first_name or str(uid)
    if target.last_name:
        user_name += f" {target.last_name}"

    try:
        # 从数据库查询各项信息
        first_seen = "未知"
        last_active = "未知"
        group_messages = 0
        level = 1
        points = 0
        warning_count = 0
        certified = False
        tags = []
        today_speech = 0

        with _db_lock:
            # users表：入群时间、最后活跃、群消息数
            row = db.conn.execute(
                "SELECT first_seen, last_active, group_messages FROM users WHERE uid=?",
                (uid,)
            ).fetchone()
            if row:
                if row[0]:
                    first_seen = datetime.fromtimestamp(row[0], _CST).strftime("%Y-%m-%d %H:%M")
                if row[1]:
                    last_active = datetime.fromtimestamp(row[1], _CST).strftime("%Y-%m-%d %H:%M")
                group_messages = row[2] or 0

            # user_levels表：等级、积分
            row = db.conn.execute(
                "SELECT level, points FROM user_levels WHERE uid=?",
                (uid,)
            ).fetchone()
            if row:
                level = row[0] or 1
                points = row[1] or 0

            # warnings表：本群警告次数
            row = db.conn.execute(
                "SELECT COUNT(*) FROM warnings WHERE uid=? AND chat_id=?",
                (uid, chat_id)
            ).fetchone()
            if row:
                warning_count = row[0]

            # certified_users表：是否认证
            row = db.conn.execute(
                "SELECT 1 FROM certified_users WHERE uid=?",
                (uid,)
            ).fetchone()
            certified = row is not None

            # user_tags表：标签
            rows = db.conn.execute(
                "SELECT tag FROM user_tags WHERE uid=? ORDER BY ts DESC",
                (uid,)
            ).fetchall()
            tags = [r[0] for r in rows]

            # speech_daily表：今日发言数
            today_str = datetime.now(_CST).strftime("%Y-%m-%d")
            row = db.conn.execute(
                "SELECT SUM(count) FROM speech_daily WHERE uid=? AND date=?",
                (uid, today_str)
            ).fetchone()
            if row and row[0]:
                today_speech = row[0]

        # 格式化信息卡
        title = _get_level_title(level, config)
        tags_str = " | ".join(tags) if tags else "暂无"
        certified_str = "是" if certified else "否"

        info_text = (
            f"👤 <b>用户信息</b>\n"
            f"━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"📛 名称: {user_name}\n"
            f"📅 入群时间: {first_seen}\n"
            f"🏅 等级: Lv{level} ({title})\n"
            f"💎 积分: {points}\n"
            f"⚠️ 警告: {warning_count}次\n"
            f"✅ 认证: {certified_str}\n"
            f"🏷 标签: {tags_str}\n"
            f"💬 今日发言: {today_speech}条"
        )

        bot.reply_to(m, info_text, parse_mode="HTML")
        logger.info(f"查询用户信息: uid={uid} by={m.from_user.id}")

    except Exception as e:
        logger.error(f"查询用户信息失败 uid={uid}: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")
