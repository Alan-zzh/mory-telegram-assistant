# -*- coding: utf-8 -*-
"""用户功能域数据操作"""
import time
from datetime import datetime

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.users")


class UserRepo:
    """用户相关数据库操作"""

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

    # ─────────────────────────────── 用户 ────────────────────────────────
    def upsert_user(self, uid: int, name: str, msg_type: str = "group"):
        ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO users
                (uid, name, first_seen, last_active) VALUES (?,?,?,?)""",
                (uid, name, ts, ts))
            if msg_type == "group":
                c.execute("UPDATE users SET last_active=?, group_messages=group_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            else:
                c.execute("UPDATE users SET last_active=?, private_messages=private_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            self.conn.commit()

    def upsert_user_with_points(self, uid: int, name: str, msg_type: str = "group", pts: int = 1):
        """更新用户活跃度并增加积分，返回 (new_level, old_level)"""
        ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO users
                (uid, name, first_seen, last_active) VALUES (?,?,?,?)""",
                (uid, name, ts, ts))
            if msg_type == "group":
                c.execute("UPDATE users SET last_active=?, group_messages=group_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            else:
                c.execute("UPDATE users SET last_active=?, private_messages=private_messages+1, name=? WHERE uid=?",
                          (ts, name, uid))
            c.execute("INSERT OR IGNORE INTO user_levels VALUES (?,1,0,?,?)", (uid, ts, ts))
            # 获取旧等级
            c.execute("SELECT level FROM user_levels WHERE uid=?", (uid,))
            row = c.fetchone()
            old_level = row[0] if row else 1
            c.execute("UPDATE user_levels SET points=points+?, last_active=? WHERE uid=?",
                      (pts, ts, uid))
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            total = c.fetchone()[0]
            # 10级等级体系（使用PointsRepo统一常量）
            from core.db_repos.points_repo import PointsRepo
            _thresholds = PointsRepo.LEVEL_THRESHOLDS
            level = 1
            for i in range(len(_thresholds) - 1, -1, -1):
                if total >= _thresholds[i]:
                    level = i + 1
                    break
            c.execute("UPDATE user_levels SET level=? WHERE uid=?", (level, uid))
            self.conn.commit()
        return (level, old_level)

    def get_user(self, uid: int):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM users WHERE uid=?", (uid,))
            return c.fetchone()

    def add_keyword(self, uid: int, keyword: str):
        """追加用户画像关键词"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT keywords FROM users WHERE uid=?", (uid,))
            row = c.fetchone()
            if row:
                existing = row[0] or ""
                if keyword not in existing:
                    new_kw = (existing + "," + keyword).strip(",")
                    c.execute("UPDATE users SET keywords=? WHERE uid=?", (new_kw, uid))
            self.conn.commit()

    def get_active_users(self, since_ts: int):
        """获取since_ts之后活跃的用户列表"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, name, keywords FROM users WHERE last_active>?", (since_ts,))
            return c.fetchall()

    def get_inactive_users(self, before_ts: int, exclude_uid: int):
        """获取before_ts之前未活跃的用户（醋意挽回用）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, name FROM users WHERE last_active<? AND uid!=?",
                      (before_ts, exclude_uid))
            return c.fetchall()

    def reset_last_active(self, uid: int):
        ts = int(time.time())
        with self.lock:
            self.conn.execute("UPDATE users SET last_active=? WHERE uid=?", (ts, uid))
            self.conn.commit()

    # [TRAE SOLO CN] v5.12.3 新增：轻量级 last_active 更新（不依赖 upsert_user_with_points）
    # 确保每条消息都更新 last_active，即使后续优先级拦截终止分发
    def update_last_active(self, uid: int):
        """更新用户最后活跃时间（轻量级，仅更新 last_active 字段）"""
        ts = int(time.time())
        with self.lock:
            try:
                self.conn.execute("UPDATE users SET last_active=? WHERE uid=?", (ts, uid))
                self.conn.commit()
            except Exception as e:
                logger.warning(f"update_last_active 失败 uid={uid}: {e}")

    # ─────────────────────────────── 勋章 ────────────────────────────────
    def earn_badge(self, uid: int, badge_id: str) -> bool:
        """
        授予用户勋章（已拥有则忽略）

        Args:
            uid: 用户ID
            badge_id: 勋章ID

        Returns:
            True表示新获得勋章，False表示已有
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT 1 FROM user_badges WHERE uid=? AND badge_id=?", (uid, badge_id))
            if c.fetchone():
                return False  # 已有
            c.execute("INSERT INTO user_badges VALUES (?,?,?)", (uid, badge_id, int(time.time())))
            self.conn.commit()
            logger.info(f"🏅 授予勋章: uid={uid} badge={badge_id}")
            return True

    def get_user_badges(self, uid: int) -> list:
        """获取用户所有勋章"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT badge_id, earned_at FROM user_badges WHERE uid=? ORDER BY earned_at DESC", (uid,))
            return c.fetchall()

    def get_all_badges_leaderboard(self, limit: int = 10) -> list:
        """获取拥有最多勋章的用户排行榜"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""
                SELECT u.uid, u.name, COUNT(b.badge_id) as badge_count
                FROM users u
                LEFT JOIN user_badges b ON u.uid = b.uid
                GROUP BY u.uid
                ORDER BY badge_count DESC
                LIMIT ?
            """, (limit,))
            return c.fetchall()

    # ─────────────────────────────── 画像简报 ────────────────────────────
    def get_user_profile(self, uid: int) -> dict | None:
        """获取用户完整画像数据，用于「查看画像」指令"""
        with self.lock:
            c = self.conn.cursor()
            # 用户基础信息
            c.execute("SELECT * FROM users WHERE uid=?", (uid,))
            row = c.fetchone()
            if not row:
                return None
            user_data = {
                "uid": row[0],
                "name": row[1],
                "first_seen": row[2],
                "last_active": row[3],
                "group_messages": row[4],
                "private_messages": row[5],
                "keywords": row[6] or "",
                "conversion_status": row[7] or "unknown",
            }
            # 等级积分
            c.execute("""SELECT level, points FROM user_levels WHERE uid=?""", (uid,))
            lv_row = c.fetchone()
            user_data["level"] = lv_row[0] if lv_row else 1
            user_data["points"] = lv_row[1] if lv_row else 0
            # 转化漏斗（从事件表聚合）
            c.execute("""SELECT
                COUNT(CASE WHEN event='touched'    THEN 1 END),
                COUNT(CASE WHEN event='interested' THEN 1 END),
                COUNT(CASE WHEN event='consulted'  THEN 1 END),
                COUNT(CASE WHEN event='paid'       THEN 1 END)
                FROM conversion_events WHERE uid=?""", (uid,))
            fn_row = c.fetchone()
            user_data["funnel"] = {
                "touched": fn_row[0] if fn_row else 0,
                "interested": fn_row[1] if fn_row else 0,
                "consulted": fn_row[2] if fn_row else 0,
                "paid": fn_row[3] if fn_row else 0,
            }
            # 活跃时段分析
            c.execute("SELECT last_active FROM users WHERE uid=?", (uid,))
            la_row = c.fetchone()
            if la_row and la_row[0]:
                hour = datetime.fromtimestamp(la_row[0], _CST).hour
                if 0 <= hour < 6:
                    user_data["active_time"] = "深夜活跃"
                elif 6 <= hour < 12:
                    user_data["active_time"] = "上午活跃"
                elif 12 <= hour < 18:
                    user_data["active_time"] = "下午活跃"
                else:
                    user_data["active_time"] = "晚间活跃"
            else:
                user_data["active_time"] = "未知"
            return user_data

    def get_all_user_profiles(self) -> list:
        """获取所有用户的画像数据列表，用于批量分析（优化为单次JOIN查询）"""
        with self.lock:
            c = self.conn.cursor()
            # 【修复】：用 JOIN 一条 SQL 查出所有数据，避免 N+1 查询风暴
            c.execute("""
                SELECT u.uid, u.name, u.first_seen, u.last_active,
                       u.group_messages, u.private_messages, u.keywords, u.conversion_status,
                       COALESCE(ul.level, 1), COALESCE(ul.points, 0),
                       COALESCE(ft.touched, 0), COALESCE(ft.interested, 0),
                       COALESCE(ft.consulted, 0), COALESCE(ft.paid, 0)
                FROM users u
                LEFT JOIN user_levels ul ON u.uid = ul.uid
                LEFT JOIN (
                    SELECT uid,
                        COUNT(CASE WHEN event='touched'    THEN 1 END) AS touched,
                        COUNT(CASE WHEN event='interested' THEN 1 END) AS interested,
                        COUNT(CASE WHEN event='consulted'  THEN 1 END) AS consulted,
                        COUNT(CASE WHEN event='paid'       THEN 1 END) AS paid
                    FROM conversion_events GROUP BY uid
                ) ft ON u.uid = ft.uid
                ORDER BY u.last_active DESC
            """)
            rows = c.fetchall()

        profiles = []
        for r in rows:
            hour = datetime.fromtimestamp(r[3], _CST).hour if r[3] else 0
            if 0 <= hour < 6: active_time = "深夜活跃"
            elif 6 <= hour < 12: active_time = "上午活跃"
            elif 12 <= hour < 18: active_time = "下午活跃"
            else: active_time = "晚间活跃"

            profiles.append({
                "uid": r[0], "name": r[1], "first_seen": r[2], "last_active": r[3],
                "group_messages": r[4], "private_messages": r[5], "keywords": r[6] or "",
                "conversion_status": r[7] or "unknown",
                "level": r[8], "points": r[9],
                "funnel": {"touched": r[10], "interested": r[11], "consulted": r[12], "paid": r[13]},
                "active_time": active_time
            })
        return profiles

    def delete_user(self, uid: int):
        """删除无效用户及其关联数据（购物车挽回/醋意挽回中清理400用户）"""
        with self.lock:
            try:
                self.conn.execute("DELETE FROM cart_recovery WHERE uid=?", (uid,))
                self.conn.execute("DELETE FROM users WHERE uid=?", (uid,))
                self.conn.commit()
            except Exception as e:
                logger.warning(f"delete_user失败 uid={uid}: {e}")
