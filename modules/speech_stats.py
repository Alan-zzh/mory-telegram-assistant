# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/speech_stats.py  ·  发言统计模块                               ║
║                                                                        ║
║  功能：                                                                ║
║    increment_speech_count  - 增加用户当日发言计数（消息分发中调用）      ║
║    handle_my_stats         - 个人统计：今日/本周/本月发言数+排名+活跃时段 �
║    handle_group_stats      - 群组统计（管理员）：日活/周活/月活+趋势     ║
║                                                                        ║
║  数据表：speech_daily (uid, date, chat_id, count)                      ║
║  被调用：main.py 消息分发 + 管理员指令                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.database import _db_lock

logger = get_logger("speech_stats")

_CST = timezone(timedelta(hours=8))


def increment_speech_count(db, uid: int, chat_id: int):
    """增加用户当日发言计数（在消息分发中调用）

    Args:
        db: DB类实例
        uid: 用户ID
        chat_id: 群组ID
    """
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    try:
        cur = db.conn.execute(
            "SELECT count FROM speech_daily WHERE uid=? AND date=? AND chat_id=?",
            (uid, today, chat_id)
        )
        row = cur.fetchone()
        if row:
            db.conn.execute(
                "UPDATE speech_daily SET count=count+1 WHERE uid=? AND date=? AND chat_id=?",
                (uid, today, chat_id)
            )
        else:
            db.conn.execute(
                "INSERT INTO speech_daily (uid, date, chat_id, count) VALUES (?,?,?,1)",
                (uid, today, chat_id)
            )
        db.conn.commit()
    except Exception as e:
        logger.error(f"发言计数更新失败 uid={uid} chat_id={chat_id}: {e}")


def _get_speech_count(db, uid: int, start_date: str, end_date: str, chat_id: int = 0) -> int:
    """获取用户在指定日期范围内的发言总数"""
    try:
        if chat_id:
            row = db.conn.execute(
                "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE uid=? AND date>=? AND date<=? AND chat_id=?",
                (uid, start_date, end_date, chat_id)
            ).fetchone()
        else:
            row = db.conn.execute(
                "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE uid=? AND date>=? AND date<=?",
                (uid, start_date, end_date)
            ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"发言统计查询失败 uid={uid}: {e}")
        return 0


def _get_user_rank(db, uid: int, date: str, chat_id: int = 0) -> int:
    """获取用户当日发言排名（1-based）"""
    try:
        if chat_id:
            row = db.conn.execute(
                """SELECT rank FROM (
                    SELECT uid, RANK() OVER (ORDER BY SUM(count) DESC) as rank
                    FROM speech_daily WHERE date=? AND chat_id=?
                    GROUP BY uid
                ) WHERE uid=?""",
                (date, chat_id, uid)
            ).fetchone()
        else:
            row = db.conn.execute(
                """SELECT rank FROM (
                    SELECT uid, RANK() OVER (ORDER BY SUM(count) DESC) as rank
                    FROM speech_daily WHERE date=?
                    GROUP BY uid
                ) WHERE uid=?""",
                (date, uid)
            ).fetchone()
        return row[0] if row else 0
    except Exception as e:
        logger.error(f"发言排名查询失败 uid={uid}: {e}")
        return 0


def _get_active_hour(db, uid: int, chat_id: int = 0) -> str:
    """获取用户最活跃时段（基于最近30天发言数据推断）"""
    try:
        # 从users表获取最后活跃时间推断时段
        row = db.conn.execute(
            "SELECT last_active FROM users WHERE uid=?", (uid,)
        ).fetchone()
        if row and row[0]:
            hour = datetime.fromtimestamp(row[0], _CST).hour
            if 0 <= hour < 6:
                return "深夜 (0-6点)"
            elif 6 <= hour < 12:
                return "上午 (6-12点)"
            elif 12 <= hour < 18:
                return "下午 (12-18点)"
            else:
                return "晚间 (18-24点)"
        return "未知"
    except Exception as e:
        logger.error(f"活跃时段查询失败 uid={uid}: {e}")
        return "未知"


def handle_my_stats(bot, m, config, db):
    """个人统计：今日/本周/本月发言数+排名+活跃时段

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    uid = m.from_user.id
    chat_id = m.chat.id if m.chat else 0
    today = datetime.now(_CST).strftime("%Y-%m-%d")

    # 本周起止（周一到今天）
    now_cst = datetime.now(_CST)
    weekday = now_cst.weekday()
    week_start = (now_cst - timedelta(days=weekday)).strftime("%Y-%m-%d")

    # 本月起止
    month_start = now_cst.strftime("%Y-%m-01")

    # 查询发言数
    today_count = _get_speech_count(db, uid, today, today, chat_id)
    week_count = _get_speech_count(db, uid, week_start, today, chat_id)
    month_count = _get_speech_count(db, uid, month_start, today, chat_id)

    # 排名
    rank = _get_user_rank(db, uid, today, chat_id)

    # 活跃时段
    active_hour = _get_active_hour(db, uid, chat_id)

    text = f"📊 我的发言统计\n"
    text += f"━━━━━━━━━━━━━\n"
    text += f"📅 今日发言：{today_count} 条\n"
    text += f"📆 本周发言：{week_count} 条\n"
    text += f"🗓 本月发言：{month_count} 条\n"
    if rank > 0:
        text += f"🏆 今日排名：第 {rank} 名\n"
    text += f"⏰ 活跃时段：{active_hour}"

    bot.reply_to(m, text)


def handle_group_stats(bot, m, config, db):
    """群组统计（管理员）：日活/周活/月活+发言趋势+TOP发言者

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    chat_id = m.chat.id if m.chat else 0
    now_cst = datetime.now(_CST)
    today = now_cst.strftime("%Y-%m-%d")

    # 日期范围
    weekday = now_cst.weekday()
    week_start = (now_cst - timedelta(days=weekday)).strftime("%Y-%m-%d")
    month_start = now_cst.strftime("%Y-%m-01")

    try:
        # 日活：今日有发言的唯一用户数
        row = db.conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM speech_daily WHERE date=? AND chat_id=?",
            (today, chat_id)
        ).fetchone()
        daily_active = row[0] if row else 0

        # 周活
        row = db.conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
            (week_start, today, chat_id)
        ).fetchone()
        weekly_active = row[0] if row else 0

        # 月活
        row = db.conn.execute(
            "SELECT COUNT(DISTINCT uid) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
            (month_start, today, chat_id)
        ).fetchone()
        monthly_active = row[0] if row else 0

        # 今日总发言数
        row = db.conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date=? AND chat_id=?",
            (today, chat_id)
        ).fetchone()
        today_total = row[0] if row else 0

        # TOP5 发言者（今日）
        rows = db.conn.execute(
            """SELECT sd.uid, COALESCE(u.name, '未知'), SUM(sd.count)
               FROM speech_daily sd LEFT JOIN users u ON sd.uid=u.uid
               WHERE sd.date=? AND sd.chat_id=?
               GROUP BY sd.uid ORDER BY SUM(sd.count) DESC LIMIT 5""",
            (today, chat_id)
        ).fetchall()

        # 近7天发言趋势
        trend_days = 7
        trend_start = (now_cst - timedelta(days=trend_days - 1)).strftime("%Y-%m-%d")
        trend_rows = db.conn.execute(
            """SELECT date, COALESCE(SUM(count),0) FROM speech_daily
               WHERE date>=? AND date<=? AND chat_id=?
               GROUP BY date ORDER BY date""",
            (trend_start, today, chat_id)
        ).fetchall()

        text = f"📊 群组发言统计\n"
        text += f"━━━━━━━━━━━━━\n"
        text += f"👤 日活（今日）：{daily_active} 人\n"
        text += f"👥 周活：{weekly_active} 人\n"
        text += f"🌐 月活：{monthly_active} 人\n"
        text += f"💬 今日总发言：{today_total} 条\n"

        # TOP5
        if rows:
            text += f"\n🏆 今日TOP发言者：\n"
            for i, (top_uid, top_name, top_count) in enumerate(rows, 1):
                text += f"  {i}. {top_name} - {top_count} 条\n"

        # 发言趋势
        if trend_rows:
            text += f"\n📈 近{trend_days}天发言趋势：\n"
            for date_str, day_count in trend_rows:
                # 简易柱状图
                bar_len = min(day_count // 10, 20)
                bar = "█" * bar_len if bar_len > 0 else "▏"
                short_date = date_str[5:]  # MM-DD
                text += f"  {short_date} {bar} {day_count}\n"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"群组统计查询失败 chat_id={chat_id}: {e}")
        bot.reply_to(m, "❌ 群组统计查询失败，请稍后再试")


def _is_admin(uid: int, config: dict) -> bool:
    """检查用户是否为管理员"""
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    # 向下兼容：ADMIN_ID 也算管理员
    if admin_id and uid == admin_id:
        return True
    return uid in admin_ids


def _time_ago(ts: float) -> str:
    """将时间戳转换为'X天前'/'X小时前'格式"""
    now = time.time()
    diff = now - ts
    if diff < 0:
        return "刚刚"
    days = int(diff // 86400)
    if days >= 1:
        return f"{days}天前"
    hours = int(diff // 3600)
    if hours >= 1:
        return f"{hours}小时前"
    minutes = int(diff // 60)
    if minutes >= 1:
        return f"{minutes}分钟前"
    return "刚刚"


def handle_silent_users(bot, m, config, db):
    """沉默用户（7天未发言）- 管理员指令

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    uid = m.from_user.id
    if not _is_admin(uid, config):
        bot.reply_to(m, "❌ 仅管理员可查看沉默用户")
        return

    now_cst = datetime.now(_CST)
    seven_days_ago_ts = (now_cst - timedelta(days=7)).timestamp()
    seven_days_ago_date = (now_cst - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        with _db_lock:
            # 从users表找last_active < 7天前的用户
            rows = db.conn.execute(
                """SELECT u.uid, COALESCE(u.name, '未知'), u.last_active
                   FROM users u
                   WHERE u.last_active > 0 AND u.last_active < ?
                   ORDER BY u.last_active ASC LIMIT 20""",
                (seven_days_ago_ts,)
            ).fetchall()

            # 排除7天内有发言记录的用户（交叉验证speech_daily）
            silent_users = []
            for row in rows:
                user_uid, user_name, last_active = row
                # 检查该用户7天内是否有发言
                recent = db.conn.execute(
                    "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE uid=? AND date>=?",
                    (user_uid, seven_days_ago_date)
                ).fetchone()
                recent_count = recent[0] if recent else 0
                if recent_count == 0:
                    silent_users.append((user_uid, user_name, last_active))

        if not silent_users:
            bot.reply_to(m, "🎉 没有沉默用户，大家都很活跃！")
            return

        text = "🔇 沉默用户（7天未发言）\n━━━━━━━━━━━━━\n"
        for user_uid, user_name, last_active in silent_users:
            time_ago = _time_ago(last_active)
            text += f"👤 {user_name} (uid={user_uid}) - 最后活跃：{time_ago}\n"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"沉默用户查询失败: {e}")
        bot.reply_to(m, "❌ 沉默用户查询失败，请稍后再试")


def handle_interaction_rank(bot, m, config, db):
    """互动排行榜 - TOP10获赞最多的用户

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    try:
        with _db_lock:
            # 从reply_feedback统计每个用户获得的like数
            rows = db.conn.execute(
                """SELECT rf.user_id, COALESCE(u.name, '未知'), COUNT(*) as like_count
                   FROM reply_feedback rf
                   LEFT JOIN users u ON rf.user_id = u.uid
                   WHERE rf.feedback = 'like'
                   GROUP BY rf.user_id
                   ORDER BY like_count DESC
                   LIMIT 10"""
            ).fetchall()

        if not rows:
            bot.reply_to(m, "🤝 暂无互动数据，还没有人点过赞哦~")
            return

        medals = ["🥇", "🥈", "🥉"]
        text = "🤝 互动排行榜\n━━━━━━━━━━━━━\n"
        for i, (user_uid, user_name, like_count) in enumerate(rows, 1):
            medal = medals[i - 1] if i <= 3 else f"  {i}."
            text += f"{medal} {user_name} - {like_count} 赞\n"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"互动排行查询失败: {e}")
        bot.reply_to(m, "❌ 互动排行查询失败，请稍后再试")
