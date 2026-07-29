"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/cmd_control.py  ·  命令启用/禁用系统                            ║
║                                                                        ║
║  功能：按群禁用/启用命令，群管可控制本群可用哪些命令。                   ║
║                                                                        ║
║  handle_disable()          -> 禁用命令                                 ║
║  handle_enable()           -> 启用命令                                 ║
║  handle_disabled()         -> 查看本群已禁用命令列表                   ║
║  is_command_disabled()     -> 检查命令是否被禁用（工具函数）            ║
║                                                                        ║
║  数据表：disabled_commands (chat_id, cmd_name, ts)                     ║
║  PRIMARY KEY (chat_id, cmd_name)                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("cmd_control")

# 中文命令名 → 内部命令名映射
CMD_NAME_MAP = {
    "签到": "checkin",
    "商城": "shop",
    "红包": "redpacket",
    "抽奖": "lottery",
    "排行": "ranking",
    "统计": "stats",
    "天气": "weather",
    "汇率": "exchange",
    "盲盒": "blindbox",
    "转盘": "wheel",
    "打赏": "tip",
    "签到日历": "checkin_calendar",
    "警告": "warn",
    "投票踢人": "vote_kick",
    "笔记": "notes",
    "自定义命令": "custom_commands",
    "定时消息": "scheduled_msg",
    "afk": "afk",
    "成就": "achievement",
    "每日任务": "daily_quest",
    "优惠券": "coupon",
    "认证": "certify",
    "标签": "tags",
    "个人资料": "profile",
}


def _resolve_cmd_name(raw_name: str) -> str:
    """将用户输入的命令名解析为内部名（去/前缀、中文映射、小写）"""
    name = raw_name.strip().lstrip("/")
    # 中文映射
    if name in CMD_NAME_MAP:
        return CMD_NAME_MAP[name]
    # 英文名直接小写
    return name.lower()


def is_command_disabled(db, chat_id: int, cmd_name: str) -> bool:
    """检查命令在本群是否被禁用，供 main.py 在处理命令前调用"""
    with _db_lock:
        row = db.conn.execute(
            "SELECT 1 FROM disabled_commands WHERE chat_id=? AND cmd_name=?",
            (chat_id, cmd_name),
        ).fetchone()
    return row is not None


def handle_disable(bot, m, config, db):
    """禁用命令：/disable 签到 或 禁用 签到"""
    chat_id = m.chat.id
    text = (m.text or "").strip()

    # 解析命令名
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "⚠️ 用法：/disable <命令名>\n例：/disable 签到 或 /disable checkin")
        return

    raw_name = parts[1].strip()
    cmd_name = _resolve_cmd_name(raw_name)
    if not cmd_name:
        bot.reply_to(m, "⚠️ 未识别的命令名")
        return

    # 检查是否已禁用
    if is_command_disabled(db, chat_id, cmd_name):
        bot.reply_to(m, f"⚠️ 命令 {raw_name} 在本群已经是禁用状态")
        return

    # 写入禁用记录
    ts = int(time.time())
    try:
        with _db_lock:
            db.conn.execute(
                "INSERT OR IGNORE INTO disabled_commands (chat_id, cmd_name, ts) VALUES (?,?,?)",
                (chat_id, cmd_name, ts),
            )
            db.conn.commit()
        bot.reply_to(m, f"✅ 已在本群禁用命令 {raw_name}")
        logger.info(f"🚫 命令禁用: chat={chat_id} cmd={cmd_name} by={m.from_user.id}")
    except Exception as e:
        logger.error(f"🚫 命令禁用失败: {e}")
        bot.reply_to(m, "❌ 禁用失败，请稍后重试或联系管理员")


def handle_enable(bot, m, config, db):
    """启用命令：/enable 签到 或 启用 签到"""
    chat_id = m.chat.id
    text = (m.text or "").strip()

    # 解析命令名
    parts = text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(m, "⚠️ 用法：/enable <命令名>\n例：/enable 签到 或 /enable checkin")
        return

    raw_name = parts[1].strip()
    cmd_name = _resolve_cmd_name(raw_name)
    if not cmd_name:
        bot.reply_to(m, "⚠️ 未识别的命令名")
        return

    # 删除禁用记录
    try:
        with _db_lock:
            cur = db.conn.execute(
                "DELETE FROM disabled_commands WHERE chat_id=? AND cmd_name=?",
                (chat_id, cmd_name),
            )
            db.conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            bot.reply_to(m, f"✅ 已在本群启用命令 {raw_name}")
            logger.info(f"✅ 命令启用: chat={chat_id} cmd={cmd_name} by={m.from_user.id}")
        else:
            bot.reply_to(m, f"⚠️ 命令 {raw_name} 在本群未被禁用，无需启用")
    except Exception as e:
        logger.error(f"✅ 命令启用失败: {e}")
        bot.reply_to(m, "❌ 启用失败，请稍后重试或联系管理员")


def handle_disabled(bot, m, config, db):
    """查看本群已禁用的命令列表"""
    chat_id = m.chat.id

    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT cmd_name, ts FROM disabled_commands WHERE chat_id=? ORDER BY ts",
                (chat_id,),
            ).fetchall()

        if not rows:
            bot.reply_to(m, "📋 本群没有禁用的命令")
            return

        # 反向映射：内部名 → 中文显示名
        reverse_map = {v: k for k, v in CMD_NAME_MAP.items()}
        lines = [f"📋 本群已禁用命令（{len(rows)}条）："]
        for i, (cmd_name, ts) in enumerate(rows, 1):
            display = reverse_map.get(cmd_name, cmd_name)
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            lines.append(f"{i}. {display}（{cmd_name}）- 禁用于 {t}")

        bot.reply_to(m, "\n".join(lines))
    except Exception as e:
        logger.error(f"📋 禁用命令列表获取失败: {e}")
        bot.reply_to(m, "❌ 获取列表失败，请稍后重试或联系管理员")
