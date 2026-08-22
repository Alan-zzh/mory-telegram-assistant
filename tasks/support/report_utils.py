"""数据报表任务共享工具（v5.38.69 去重：daily/weekly/monthly 三连克隆收敛）。"""

from core.logging_util import get_logger

logger = get_logger("tasks.analytics.report_utils")


def pct(cur, prev):
    """环比百分比文案：增长📈/下降📉/持平➖/新增🆕。"""
    if prev == 0:
        return "🆕" if cur > 0 else "➖"
    diff = ((cur - prev) / prev) * 100
    if diff > 0:
        return f"📈+{diff:.0f}%"
    if diff < 0:
        return f"📉{diff:.0f}%"
    return "➖0%"


def trend(cur, prev):
    """趋势箭头：升📈/降📉/平➖。"""
    if cur > prev:
        return "📈"
    if cur < prev:
        return "📉"
    return "➖"


def fetch_member_count_with_db_fallback(rm, chat_id: int) -> int:
    """Telegram 实时群人数；API 失败时回退 DB 最近值并留痕（非致命降级）。"""
    try:
        with rm.locked('bot'):
            return rm.bot.get_chat_member_count(chat_id)
    except Exception as e:
        logger.debug(f"群人数API失败，回退DB（非致命）：chat_id={chat_id} err={e}")
        return rm.db.get_group_total_members_latest(chat_id)
