# -*- coding: utf-8 -*-
"""积分功能域数据操作"""
import time
from datetime import datetime

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.points")


class PointsRepo:
    """积分相关数据库操作"""

    # 10级等级体系阈值（统一常量，消除upsert_user_with_points和add_points中的重复定义）
    LEVEL_THRESHOLDS = [0, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]

    def __init__(self, db):
        """db: DB实例，通过 db.conn 和 db.lock 访问连接和锁"""
        self._db = db

    @property
    def conn(self):
        """快捷访问数据库连接"""
        return self._db.conn

    @property
    def lock(self):
        """快捷访问全局锁"""
        return self._db.lock

    # ─────────────────────────────── 等级/积分 ───────────────────────────
    def get_user_points(self, uid: int):
        """查询单用户积分，返回int或None（不存在时）"""
        c = self.conn.cursor()
        c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
        row = c.fetchone()
        return row[0] if row else None

    def add_points(self, uid: int, pts: int, source: str = "system"):
        """增加/扣除积分，同时记录积分日志。

        Args:
            uid: 用户ID
            pts: 积分变动量（正数增加，负数扣除）
            source: 积分来源（speech/checkin/invite/tip/exchange/blindbox/wheel/transfer/quest/achievement/system）

        Returns:
            (new_level, old_level) 升级时返回新旧行，未升级返回 (level, level)
        """
        ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT OR IGNORE INTO user_levels VALUES (?,1,0,?,?)", (uid, ts, ts))
            # 获取旧等级
            c.execute("SELECT level FROM user_levels WHERE uid=?", (uid,))
            row = c.fetchone()
            old_level = row[0] if row else 1
            c.execute("UPDATE user_levels SET points=points+?, last_active=? WHERE uid=?",
                      (pts, ts, uid))
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            total = c.fetchone()[0]
            # 10级等级体系（使用统一常量）
            _thresholds = self.LEVEL_THRESHOLDS
            level = 1
            for i in range(len(_thresholds) - 1, -1, -1):
                if total >= _thresholds[i]:
                    level = i + 1
                    break
            c.execute("UPDATE user_levels SET level=? WHERE uid=?", (level, uid))
            # 记录积分日志
            try:
                c.execute(
                    "INSERT INTO points_log (uid, change_amount, balance_after, source, ts) VALUES (?,?,?,?,?)",
                    (uid, pts, total, source, ts)
                )
            except Exception as e:
                self._db._log_db_error("INSERT INTO points_log", e, "warning", f"uid={uid}, points={pts}")
            self.conn.commit()
        return (level, old_level)

    def get_points_log(self, uid: int, limit: int = 10) -> list:
        """获取用户积分变动记录"""
        c = self.conn.cursor()
        c.execute(
            "SELECT change_amount, balance_after, source, ts FROM points_log WHERE uid=? ORDER BY ts DESC LIMIT ?",
            (uid, limit)
        )
        return c.fetchall()

    def get_today_speech_points(self, uid: int) -> int:
        """获取用户今日通过发言获取的积分总额"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        day_start = int(datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c = self.conn.cursor()
        try:
            c.execute(
                "SELECT COALESCE(SUM(change_amount),0) FROM points_log WHERE uid=? AND source='speech' AND ts>=? AND ts<?",
                (uid, day_start, day_end)
            )
            return c.fetchone()[0]
        except Exception as e:
            self._db._log_db_error("SELECT 今日发言积分", e, "warning", f"uid={uid}")
            return 0

    def get_leaderboard(self, limit: int = 10):
        c = self.conn.cursor()
        c.execute("""SELECT u.uid, u.name, COALESCE(ul.points,0), COALESCE(ul.level,1)
                     FROM users u LEFT JOIN user_levels ul ON u.uid=ul.uid
                     ORDER BY COALESCE(ul.points,0) DESC LIMIT ?""", (limit,))
        return c.fetchall()

    # ─────────────────────────────── 简报 ────────────────────────────────
    def get_daily_report(self) -> dict:
        ts = int(time.time())
        day_ago = ts - 86400
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE last_active>?", (day_ago,))
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE first_seen>?", (day_ago,))
        new_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0]
        # 内联funnel查询（避免跨Repo获取锁导致死锁）
        c.execute("""SELECT
            COUNT(DISTINCT CASE WHEN event='touched'    THEN uid END),
            COUNT(DISTINCT CASE WHEN event='interested' THEN uid END),
            COUNT(DISTINCT CASE WHEN event='consulted'  THEN uid END),
            COUNT(DISTINCT CASE WHEN event='paid'       THEN uid END)
            FROM conversion_events""")
        funnel = c.fetchone()
        c.execute("""SELECT u.name, COALESCE(ul.points,0) FROM users u
                     LEFT JOIN user_levels ul ON u.uid=ul.uid
                     ORDER BY COALESCE(ul.points,0) DESC LIMIT 5""")
        top5 = c.fetchall()
        c.execute("SELECT COUNT(*) FROM blacklist")
        blacklist_cnt = c.fetchone()[0]
        return {
            "active": active,
            "new_users": new_users,
            "total": total,
            "funnel": funnel or (0,0,0,0),
            "top5": top5,
            "blacklist": blacklist_cnt,
        }
