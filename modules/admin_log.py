"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/admin_log.py  ·  管理员操作日志系统                            ║
║                                                                        ║
║  功能：记录和查看管理员操作（封禁/踢出/禁言/警告等）。                   ║
║                                                                        ║
║  log_admin_action()       -> 记录管理员操作（工具函数）                 ║
║  handle_adminlog()        -> 查看最近管理员操作记录                     ║
║                                                                        ║
║  数据表：admin_logs (id, chat_id, operator_uid, target_uid,             ║
║           action, reason, ts)                                          ║
║  action值：ban/kick/mute/unmute/warn/clear_warn/promote/demote/        ║
║           fban/lock/unlock/purge/pin/unpin                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("admin_log")

_CST = timezone(timedelta(hours=8))

# action 中文映射
ACTION_LABELS = {
    "ban": "封禁",
    "kick": "踢出",
    "mute": "禁言",
    "unmute": "解禁",
    "warn": "警告",
    "clear_warn": "清除警告",
    "promote": "升管",
    "demote": "降管",
    "fban": "联邦封禁",
    "lock": "锁定",
    "unlock": "解锁",
    "purge": "清屏",
    "pin": "置顶",
    "unpin": "取消置顶",
}


def log_admin_action(db, chat_id: int, operator_uid: int, target_uid: int, action: str, reason: str = ""):
    """记录管理员操作，供各管理模块调用"""
    ts = int(time.time())
    try:
        with _db_lock:
            db.conn.execute(
                "INSERT INTO admin_logs (chat_id, operator_uid, target_uid, action, reason, ts) VALUES (?,?,?,?,?,?)",
                (chat_id, operator_uid, target_uid, action, reason, ts),
            )
            db.conn.commit()
        logger.info(f"📝 管理操作记录: chat={chat_id} op={operator_uid} target={target_uid} action={action}")
    except Exception as e:
        logger.error(f"📝 管理操作记录失败: {e}")


def handle_adminlog(bot, m, config, db):
    """查看本群最近的管理员操作记录（仅管理员可用）"""
    chat_id = m.chat.id

    # 权限检查：仅管理员
    try:
        member = bot.get_chat_member(chat_id, m.from_user.id)
        if member.status not in ("administrator", "creator"):
            bot.reply_to(m, "⚠️ 仅管理员可查看操作日志")
            return
    except Exception as e:
        logger.warning(f"权限检查失败: {e}")
        bot.reply_to(m, "❌ 权限检查失败，请稍后重试")
        return

    try:
        with _db_lock:
            rows = db.conn.execute(
                "SELECT operator_uid, target_uid, action, reason, ts FROM admin_logs WHERE chat_id=? ORDER BY ts DESC LIMIT 10",
                (chat_id,),
            ).fetchall()

        if not rows:
            bot.reply_to(m, "📋 本群暂无管理员操作记录")
            return

        lines = [f"📋 最近管理操作（{len(rows)}条）："]
        for i, (op_uid, target_uid, action, reason, ts) in enumerate(rows, 1):
            t = datetime.fromtimestamp(ts, tz=_CST).strftime("%m-%d %H:%M")
            action_label = ACTION_LABELS.get(action, action)
            # 格式：操作者 → 目标: 动作 (原因) [时间]
            line = f"{i}. {op_uid} → {target_uid}: {action_label}"
            if reason:
                line += f"（{reason}）"
            line += f" [{t}]"
            lines.append(line)

        bot.reply_to(m, "\n".join(lines))
    except Exception as e:
        logger.error(f"📋 管理日志查询失败: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后重试或联系管理员")
