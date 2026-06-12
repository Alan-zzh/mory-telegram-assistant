"""
modules/ranking.py · 多维排行榜

功能：
  handle_ranking(bot, m, config, db, dimension) - 5维度排行榜

维度：
  points  - 积分排行：从 user_levels 表读取
  checkin - 签到排行：从 checkin_records 表读取连续签到天数
  active  - 活跃排行：从 speech_daily 表读取本月发言数
  consume - 消费排行：从 exchange_records 表读取兑换积分总额
  invite  - 邀请排行：从 invite_records 表读取邀请人数

每个维度显示TOP10，前三名用🥇🥈🥉标识。
"""

import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("ranking")

_CST = timezone(timedelta(hours=8))


def _get_user_name(db, uid: int) -> str:
    """获取用户名，查不到则返回 UID"""
    try:
        c = db.conn.cursor()
        c.execute("SELECT name FROM users WHERE uid=?", (uid,))
        row = c.fetchone()
        return row[0] if row else f"用户{uid}"
    except Exception:
        return f"用户{uid}"


def _format_ranking(db, title: str, rows: list, value_formatter=None) -> str:
    """
    格式化排行榜输出。

    Args:
        title: 排行榜标题
        rows: [(uid, value), ...] 已排序
        value_formatter: 可选的值格式化函数

    Returns:
        格式化的排行榜文本
    """
    if not rows:
        return f"📋 {title}暂无数据"

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 {title}TOP10\n"]

    for i, (uid, value) in enumerate(rows):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        # 延迟获取用户名（只对TOP10获取，性能可控）
        name = _get_user_name(db, uid)
        val_str = value_formatter(value) if value_formatter else str(value)
        lines.append(f"{prefix} {name} — {val_str}")

    return "\n".join(lines)


def _ranking_points(db, limit: int = 10) -> list:
    """积分排行：从 user_levels 表读取"""
    try:
        c = db.conn.cursor()
        c.execute("""
            SELECT uid, points FROM user_levels
            WHERE points > 0
            ORDER BY points DESC
            LIMIT ?
        """, (limit,))
        return c.fetchall()
    except Exception as e:
        logger.error(f"积分排行查询失败: {e}")
        return []


def _ranking_checkin(db, limit: int = 10) -> list:
    """签到排行：从 checkin_records 表读取连续签到天数"""
    try:
        c = db.conn.cursor()
        # 获取每个用户最近一次签到记录的连续天数
        c.execute("""
            SELECT uid, MAX(continuous_days) as max_continuous
            FROM checkin_records
            GROUP BY uid
            ORDER BY max_continuous DESC
            LIMIT ?
        """, (limit,))
        return c.fetchall()
    except Exception as e:
        logger.error(f"签到排行查询失败: {e}")
        return []


def _ranking_active(db, limit: int = 10, chat_id: int = 0) -> list:
    """【v4.17.0修复】活跃排行：从 speech_daily 表读取本月发言数，支持按群组过滤"""
    try:
        now_cst = datetime.now(_CST)
        month_prefix = now_cst.strftime("%Y-%m")
        c = db.conn.cursor()
        if chat_id:
            c.execute("""
                SELECT uid, SUM(count) as total_count
                FROM speech_daily
                WHERE date LIKE ? AND chat_id = ?
                GROUP BY uid
                ORDER BY total_count DESC
                LIMIT ?
            """, (f"{month_prefix}%", chat_id, limit))
        else:
            c.execute("""
                SELECT uid, SUM(count) as total_count
                FROM speech_daily
                WHERE date LIKE ?
                GROUP BY uid
                ORDER BY total_count DESC
                LIMIT ?
            """, (f"{month_prefix}%", limit))
        return c.fetchall()
    except Exception as e:
        logger.error(f"活跃排行查询失败: {e}")
        return []


def _ranking_consume(db, limit: int = 10) -> list:
    """消费排行：从 exchange_records 表读取兑换积分总额"""
    try:
        c = db.conn.cursor()
        c.execute("""
            SELECT uid, SUM(points_cost) as total_cost
            FROM exchange_records
            GROUP BY uid
            ORDER BY total_cost DESC
            LIMIT ?
        """, (limit,))
        return c.fetchall()
    except Exception as e:
        logger.error(f"消费排行查询失败: {e}")
        return []


def _ranking_invite(db, limit: int = 10) -> list:
    """邀请排行：从 invite_records 表读取邀请人数"""
    try:
        c = db.conn.cursor()
        c.execute("""
            SELECT inviter_uid as uid, COUNT(*) as invite_count
            FROM invite_records
            GROUP BY inviter_uid
            ORDER BY invite_count DESC
            LIMIT ?
        """, (limit,))
        return c.fetchall()
    except Exception as e:
        logger.error(f"邀请排行查询失败: {e}")
        return []


# 维度映射表
_DIMENSION_MAP = {
    "points": {
        "title": "积分排行",
        "query": _ranking_points,
        "formatter": lambda v: f"{v} 积分",
    },
    "checkin": {
        "title": "签到排行",
        "query": _ranking_checkin,
        "formatter": lambda v: f"连续 {v} 天",
    },
    "active": {
        "title": "活跃排行",
        "query": _ranking_active,
        "formatter": lambda v: f"{v} 条发言",
    },
    "consume": {
        "title": "消费排行",
        "query": _ranking_consume,
        "formatter": lambda v: f"消费 {v} 积分",
    },
    "invite": {
        "title": "邀请排行",
        "query": _ranking_invite,
        "formatter": lambda v: f"邀请 {v} 人",
    },
}


def handle_ranking(bot, m, config: dict, db, dimension: str):
    """
    多维排行榜。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        dimension: 排行维度（points/checkin/active/consume/invite）
    """
    chat_id = m.chat.id
    dimension = dimension.strip().lower()

    # 无维度参数时显示帮助
    if not dimension:
        lines = [
            "🏆 多维排行榜",
            "",
            "可用维度：",
            "  points  - 积分排行",
            "  checkin - 签到排行",
            "  active  - 活跃排行",
            "  consume - 消费排行",
            "  invite  - 邀请排行",
            "",
            "用法：排行榜 points",
        ]
        bot.send_message(chat_id, "\n".join(lines))
        return

    # 查找维度
    dim_config = _DIMENSION_MAP.get(dimension)
    if not dim_config:
        valid = ", ".join(_DIMENSION_MAP.keys())
        bot.send_message(chat_id, f"❌ 未知维度：{dimension}\n可选维度：{valid}")
        return

    try:
        rows = dim_config["query"](db, chat_id=chat_id)
        text = _format_ranking(
            db,
            title=dim_config["title"],
            rows=rows,
            value_formatter=dim_config["formatter"],
        )
        bot.send_message(chat_id, text)
    except Exception as e:
        logger.error(f"排行榜查询失败 dimension={dimension}: {e}")
        bot.send_message(chat_id, "❌ 排行榜查询失败，请稍后再试")
