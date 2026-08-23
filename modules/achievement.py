import time
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("achievement")

ACHIEVEMENT_DEFS = {
    "first_checkin": {"name": "初来乍到", "desc": "首次签到", "icon": "🌱"},
    "checkin_7d": {"name": "坚持不懈", "desc": "连续签到7天", "icon": "🔥"},
    "checkin_15d": {"name": "签到达人", "desc": "连续签到15天", "icon": "💪"},
    "checkin_30d": {"name": "月度之星", "desc": "连续签到30天", "icon": "⭐"},
    "points_100": {"name": "小有积蓄", "desc": "积分达到100", "icon": "💰"},
    "points_500": {"name": "财富自由", "desc": "积分达到500", "icon": "💎"},
    "speech_100": {"name": "话唠", "desc": "累计发言100条", "icon": "🗣️"},
    "speech_1000": {"name": "演说家", "desc": "累计发言1000条", "icon": "🎤"},
    "invite_3": {"name": "人脉王", "desc": "邀请3人入群", "icon": "🤝"},
    "blindbox_10": {"name": "赌神", "desc": "开10次盲盒", "icon": "🎲"},
    "tip_5": {"name": "慷慨解囊", "desc": "打赏5次", "icon": "💝"},
    "wheel_10": {"name": "幸运儿", "desc": "转10次转盘", "icon": "🎡"},
}


def handle_my_achievements(bot, m, config, db):
    """查看我的成就"""
    uid = m.from_user.id
    chat_id = m.chat.id

    # 获取已解锁成就
    with _db_lock:
        rows = db.conn.execute(
            "SELECT achievement_id FROM achievements WHERE uid = ?",
            (uid,)
        ).fetchall()
    unlocked_ids = {row[0] for row in rows}

    lines = ["🎖️ <b>我的成就</b>\n"]
    for aid, info in ACHIEVEMENT_DEFS.items():
        if aid in unlocked_ids:
            lines.append(f"  ✅ {info['icon']} {info['name']}")
        else:
            # 未解锁也展示解锁条件，用户才知道要做什么
            lines.append(f"  🔒 {info['name']}（{info['desc']}）")

    total = len(ACHIEVEMENT_DEFS)
    lines.append(f"\n📊 已解锁 {len(unlocked_ids)}/{total} 个成就")

    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


def check_achievement(db, uid, achievement_id):
    """检查用户是否已有某成就"""
    with _db_lock:
        row = db.conn.execute(
            "SELECT 1 FROM achievements WHERE uid = ? AND achievement_id = ?",
            (uid, achievement_id)
        ).fetchone()
    return row is not None


def unlock_achievement(bot, chat_id, db, uid, achievement_id, config):
    """解锁成就，返回True表示新解锁，False表示已有"""
    if check_achievement(db, uid, achievement_id):
        return False

    info = ACHIEVEMENT_DEFS.get(achievement_id)
    if not info:
        logger.warning(f"未知成就ID: {achievement_id}")
        return False

    with _db_lock:
        db.conn.execute(
            "INSERT INTO achievements (uid, achievement_id, earned_at) VALUES (?, ?, ?)",
            (uid, achievement_id, int(time.time()))
        )
        db.conn.commit()

    # 发送解锁通知
    bot.send_message(
        chat_id,
        f"🏆 成就解锁！{info['icon']} {info['name']}\n📝 {info['desc']}",
        parse_mode="HTML"
    )

    # 奖励10积分
    _lv_result = db.add_points(uid, 10, source="achievement")

    # 检查升级通知
    from modules.points_enhanced import check_level_up
    # 升级通知需要用户名：查 users 表真名，避免群里出现“用户123456789”
    try:
        _name_row = db.conn.execute(
            "SELECT name FROM users WHERE uid = ?", (uid,)
        ).fetchone()
    except Exception:
        _name_row = None
    _ach_uname = (_name_row[0] if _name_row and _name_row[0] else "") or f"用户{uid}"
    check_level_up(bot, chat_id, uid, _ach_uname, _lv_result, config)

    logger.info(f"用户 {uid} 解锁成就: {achievement_id}")
    return True


def check_achievements_for_user(bot, chat_id, db, uid, config):
    """检查用户所有可能的成就，自动解锁新成就"""
    newly_unlocked = []

    # --- 签到类 ---
    with _db_lock:
        # first_checkin: 有签到记录
        row = db.conn.execute(
            "SELECT 1 FROM checkin_records WHERE uid = ? LIMIT 1",
            (uid,)
        ).fetchone()
        has_checkin = row is not None

        # checkin_7d/15d/30d: 最大连续签到天数
        row = db.conn.execute(
            "SELECT MAX(continuous_days) FROM checkin_records WHERE uid = ?",
            (uid,)
        ).fetchone()
        max_continuous = row[0] if row and row[0] else 0

        # points_100/500: 当前积分
        row = db.conn.execute(
            "SELECT points FROM user_levels WHERE uid = ?",
            (uid,)
        ).fetchone()
        current_points = row[0] if row else 0

        # speech_100/1000: 累计发言数
        row = db.conn.execute(
            "SELECT SUM(group_messages) FROM users WHERE uid = ?",
            (uid,)
        ).fetchone()
        total_speech = row[0] if row and row[0] else 0

        # invite_3: 邀请人数
        row = db.conn.execute(
            "SELECT COUNT(*) FROM invite_records WHERE uid = ?",
            (uid,)
        ).fetchone()
        invite_count = row[0] if row else 0

        # blindbox_10: 开盲盒次数（按扣费流水计，中奖流水只是其中一部分）
        row = db.conn.execute(
            "SELECT COUNT(*) FROM points_log WHERE uid = ? AND source = 'blindbox_cost'",
            (uid,)
        ).fetchone()
        blindbox_count = row[0] if row else 0

        # tip_5: 打赏次数（打赏方扣费流水 source='tip' 且 change_amount < 0）
        row = db.conn.execute(
            "SELECT COUNT(*) FROM points_log WHERE uid = ? AND source = 'tip' AND change_amount < 0",
            (uid,)
        ).fetchone()
        tip_count = row[0] if row else 0

        # wheel_10: 转盘次数（按实际转动次数计：lucky_wheel_results 一天一行，
        # 旧行数统计把“转10次”算成“转10天”）
        row = db.conn.execute(
            "SELECT COALESCE(SUM(spin_count), 0) FROM lucky_wheel_results WHERE uid = ?",
            (uid,)
        ).fetchone()
        wheel_count = row[0] if row else 0

    # 逐项检查并解锁
    checks = [
        ("first_checkin", has_checkin),
        ("checkin_7d", max_continuous >= 7),
        ("checkin_15d", max_continuous >= 15),
        ("checkin_30d", max_continuous >= 30),
        ("points_100", current_points >= 100),
        ("points_500", current_points >= 500),
        ("speech_100", total_speech >= 100),
        ("speech_1000", total_speech >= 1000),
        ("invite_3", invite_count >= 3),
        ("blindbox_10", blindbox_count >= 10),
        ("tip_5", tip_count >= 5),
        ("wheel_10", wheel_count >= 10),
    ]

    for aid, condition in checks:
        if condition:
            if unlock_achievement(bot, chat_id, db, uid, aid, config):
                newly_unlocked.append(aid)

    if newly_unlocked:
        logger.info(f"用户 {uid} 新解锁成就: {newly_unlocked}")

    return newly_unlocked
