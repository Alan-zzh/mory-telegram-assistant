import time
from datetime import datetime, timedelta, timezone
from core.database import _db_lock
from core.logging_util import get_logger

_CST = timezone(timedelta(hours=8))
logger = get_logger("daily_quest")

# 每日任务定义
QUEST_DEFS = [
    {"type": "checkin", "name": "签到", "reward": 5},
    {"type": "speech5", "name": "发言5条", "reward": 10},
    {"type": "speech10", "name": "发言10条", "reward": 15},
    {"type": "tip", "name": "打赏1次", "reward": 8},
    {"type": "shop", "name": "使用商城1次", "reward": 10},
]

ALL_QUEST_BONUS = 30


def _today_str():
    """返回今天CST日期字符串 YYYY-MM-DD"""
    return datetime.now(_CST).strftime("%Y-%m-%d")


def _day_bounds_ts():
    """返回今天（CST）的起始/结束 Unix 时间戳 [start, end)"""
    now = datetime.now(_CST)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (int(start.timestamp()), int(start.timestamp()) + 86400)


def _init_daily_quests(db, uid, today):
    """确保今日任务记录存在"""
    for q in QUEST_DEFS:
        db.conn.execute(
            "INSERT OR IGNORE INTO daily_quests (uid, date, quest_type, completed, ts) VALUES (?, ?, ?, 0, 0)",
            (uid, today, q["type"]),
        )
    db.conn.commit()


def get_quest_progress(db, uid, quest_type, config=None):
    """获取某个任务类型的今日进度"""
    today = _today_str()

    if quest_type == "checkin":
        row = db.conn.execute(
            "SELECT COUNT(*) FROM checkin_records WHERE uid=? AND date=?",
            (uid, today),
        ).fetchone()
        return row[0] if row else 0

    elif quest_type in ("speech5", "speech10"):
        row = db.conn.execute(
            "SELECT count FROM speech_daily WHERE uid=? AND date=?",
            (uid, today),
        ).fetchone()
        return row[0] if row else 0

    elif quest_type == "tip":
        # points_log 没有 date 列（旧版按 date 查询是潜伏崩溃分支），
        # 改用当日时间戳范围统计打赏方扣费流水。
        import time as _time
        day_start, day_end = _day_bounds_ts()
        row = db.conn.execute(
            "SELECT COUNT(*) FROM points_log WHERE uid=? AND source='tip' AND change_amount<0 AND ts>=? AND ts<?",
            (uid, day_start, day_end),
        ).fetchone()
        return row[0] if row else 0

    elif quest_type == "shop":
        # exchange_records 同样没有 date 列，改按 created_at/ts 兜底查询
        import time as _time
        cols = {desc[0] for desc in db.conn.execute("SELECT * FROM exchange_records LIMIT 0").description}
        ts_col = "created_at" if "created_at" in cols else ("ts" if "ts" in cols else None)
        if ts_col is None:
            return 0
        day_start, day_end = _day_bounds_ts()
        row = db.conn.execute(
            f"SELECT COUNT(*) FROM exchange_records WHERE uid=? AND {ts_col}>=? AND {ts_col}<?",
            (uid, day_start, day_end),
        ).fetchone()
        return row[0] if row else 0

    return 0


def check_quest_completion(db, uid, quest_type, config=None, bot=None, chat_id=None, uname=None):
    """检查并标记任务完成，返回 True 表示新完成，False 表示已完成"""
    today = _today_str()
    _init_daily_quests(db, uid, today)

    # 检查是否已完成
    row = db.conn.execute(
        "SELECT completed FROM daily_quests WHERE uid=? AND date=? AND quest_type=?",
        (uid, today, quest_type),
    ).fetchone()
    if row and row[0]:
        return False

    # 标记完成
    with _db_lock:
        db.conn.execute(
            "UPDATE daily_quests SET completed=1, ts=? WHERE uid=? AND date=? AND quest_type=?",
            (int(time.time()), uid, today, quest_type),
        )
        db.conn.commit()

    # 发放奖励
    reward = 0
    for q in QUEST_DEFS:
        if q["type"] == quest_type:
            reward = q["reward"]
            break

    _lv_result = None
    if reward > 0:
        _lv_result = db.add_points(uid, reward, source="quest")
        logger.info(f"uid={uid} 完成任务 {quest_type}，奖励 {reward} 积分")

    # 检查是否全部完成
    all_done = True
    for q in QUEST_DEFS:
        row = db.conn.execute(
            "SELECT completed FROM daily_quests WHERE uid=? AND date=? AND quest_type=?",
            (uid, today, q["type"]),
        ).fetchone()
        if not row or not row[0]:
            all_done = False
            break

    _lv_result2 = None
    if all_done:
        _lv_result2 = db.add_points(uid, ALL_QUEST_BONUS, source="quest_bonus")
        logger.info(f"uid={uid} 全部每日任务完成，额外奖励 {ALL_QUEST_BONUS} 积分")

    # 检查升级通知
    if bot and chat_id and config:
        from modules.points_enhanced import check_level_up
        _qname = uname or f"用户{uid}"
        if _lv_result:
            check_level_up(bot, chat_id, uid, _qname, _lv_result, config)
        if _lv_result2:
            check_level_up(bot, chat_id, uid, _qname, _lv_result2, config)

    return True


def handle_daily_quest(bot, m, config, db):
    """处理每日任务查看命令"""
    uid = m.from_user.id
    today = _today_str()
    _init_daily_quests(db, uid, today)

    lines = [f"📋 每日任务 ({today})\n"]
    all_done = True

    for q in QUEST_DEFS:
        row = db.conn.execute(
            "SELECT completed FROM daily_quests WHERE uid=? AND date=? AND quest_type=?",
            (uid, today, q["type"]),
        ).fetchone()
        completed = row and row[0]

        if not completed:
            all_done = False

        icon = "✅" if completed else "⬜"
        lines.append(f"{icon} {q['name']} - 奖励{q['reward']}积分")

    if all_done:
        lines.append(f"\n🎉 全部完成！额外奖励{ALL_QUEST_BONUS}积分")

    bot.reply_to(m, "\n".join(lines))
