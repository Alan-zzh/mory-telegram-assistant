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
        """获取before_ts之前未活跃且可私聊的用户（醋意挽回用）。

        Telegram Bot 只能主动私聊曾经打开过私聊的用户。过滤 private_messages=0
        可以避免对群成员直接发私信导致 403，同时避免先生成 LLM 文案再失败。
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT uid, name FROM users "
                "WHERE last_active<? AND uid!=? AND private_messages>0 "
                "ORDER BY last_active ASC",
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

    # ─────────────────────────────── 用户画像（v5.18.0） ────────────────────────────────
    def get_user_persona_profile(self, user_id: int) -> dict | None:
        """获取用户画像（persona 版本，来自 user_profiles 表）。

        注意：本方法与 line 176 的 get_user_profile 同名冲突已修复（Python 后定义覆盖前定义）。
        期望 users 表聚合字段的调用方请用 get_user_profile；期望 user_profiles 表 persona
        字段（tags/interests/activity_score/flirt_affinity/memory_summary 等）的调用方用本方法。
        """
        import json
        with self.lock:
            c = self.conn.cursor()
            # [TRAE SOLO CN] v5.19.0 扩展查询：包含 6 个新画像列
            # [TRAE SOLO CN v5.24.0 阶段3-B] 增加 memory_summary 列（带 fallback）
            try:
                c.execute("""SELECT user_id, tags, level, interests, last_interaction, conversation_rounds,
                                    activity_score, flirt_affinity, spend_tendency, resistance_idx,
                                    peak_hours, persona_tags, memory_summary
                             FROM user_profiles WHERE user_id=?""", (user_id,))
            except Exception:
                # 旧表无 memory_summary 列，回退
                c.execute("""SELECT user_id, tags, level, interests, last_interaction, conversation_rounds,
                                    activity_score, flirt_affinity, spend_tendency, resistance_idx,
                                    peak_hours, persona_tags
                             FROM user_profiles WHERE user_id=?""", (user_id,))
            r = c.fetchone()
            if not r:
                return None
            try:
                tags = json.loads(r[1]) if r[1] else []
                interests = json.loads(r[3]) if r[3] else []
                peak_hours = json.loads(r[10]) if r[10] else []
                persona_tags = json.loads(r[11]) if r[11] else []
            except Exception:
                tags, interests, peak_hours, persona_tags = [], [], [], []
            # [v5.24.0] memory_summary 可能不存在（旧表），安全获取
            memory_summary = ""
            try:
                memory_summary = r[12] or ""
            except IndexError:
                pass
            return {
                "user_id": r[0],
                "tags": tags,
                "level": r[2] or 0,
                "interests": interests,
                "last_interaction": r[4],
                "conversation_rounds": r[5] or 0,
                "activity_score": r[6] or 0.0,
                "flirt_affinity": r[7] or 0.0,
                "spend_tendency": r[8] or 0.0,
                "resistance_idx": r[9] if r[9] is not None else 0.5,
                "peak_hours": peak_hours,
                "persona_tags": persona_tags,
                "memory_summary": memory_summary,
            }

    def upsert_user_profile(self, profile: dict) -> None:
        """更新或插入用户画像。"""
        import json
        with self.lock:
            c = self.conn.cursor()
            tags_json = json.dumps(profile.get("tags", []), ensure_ascii=False)
            interests_json = json.dumps(profile.get("interests", []), ensure_ascii=False)
            peak_hours_json = json.dumps(profile.get("peak_hours", []), ensure_ascii=False)
            persona_tags_json = json.dumps(profile.get("persona_tags", []), ensure_ascii=False)
            # [TRAE SOLO CN v5.24.0 阶段3-B] memory_summary 字段支持
            # 未传（None）时不覆盖已有值（COALESCE），传值时写入新摘要
            memory_summary = profile.get("memory_summary")
            # 防御旧表：幂等补列（避免 WriteQueue 反复报错 duplicate column）
            self._db._safe_add_column(c, "user_profiles", "memory_summary", "TEXT DEFAULT ''")
            # [TRAE SOLO CN] v5.19.0 扩展写入：6 个新画像列
            # [TRAE SOLO CN v5.24.0 阶段3-B] 增加 memory_summary 列（COALESCE 保留已有值，幂等不覆盖）
            c.execute("""INSERT INTO user_profiles
                (user_id, tags, level, interests, last_interaction, conversation_rounds,
                 activity_score, flirt_affinity, spend_tendency, resistance_idx,
                 peak_hours, persona_tags, memory_summary, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    tags=excluded.tags,
                    level=excluded.level,
                    interests=excluded.interests,
                    last_interaction=excluded.last_interaction,
                    conversation_rounds=excluded.conversation_rounds,
                    activity_score=excluded.activity_score,
                    flirt_affinity=excluded.flirt_affinity,
                    spend_tendency=excluded.spend_tendency,
                    resistance_idx=excluded.resistance_idx,
                    peak_hours=excluded.peak_hours,
                    persona_tags=excluded.persona_tags,
                    memory_summary=COALESCE(excluded.memory_summary, user_profiles.memory_summary),
                    updated_at=CURRENT_TIMESTAMP
            """, (
                profile["user_id"],
                tags_json,
                profile.get("level", 0),
                interests_json,
                profile.get("last_interaction"),
                profile.get("conversation_rounds", 0),
                profile.get("activity_score", 0.0),
                profile.get("flirt_affinity", 0.0),
                profile.get("spend_tendency", 0.0),
                profile.get("resistance_idx", 0.5),
                peak_hours_json,
                persona_tags_json,
                memory_summary,
            ))
            self.conn.commit()

    def list_user_profiles(self, min_level: int = 0, tag: str = "", limit: int = 100) -> list:
        """列出用户画像（用于画像运营页面）。"""
        import json
        with self.lock:
            c = self.conn.cursor()
            if tag:
                c.execute("SELECT user_id, tags, level, interests, last_interaction, conversation_rounds FROM user_profiles WHERE level >= ? AND tags LIKE ? ORDER BY level DESC, last_interaction DESC LIMIT ?",
                          (min_level, f'%"{tag}"%', limit))
            else:
                c.execute("SELECT user_id, tags, level, interests, last_interaction, conversation_rounds FROM user_profiles WHERE level >= ? ORDER BY level DESC, last_interaction DESC LIMIT ?",
                          (min_level, limit))
            rows = c.fetchall()
        results = []
        for r in rows:
            try:
                tags = json.loads(r[1]) if r[1] else []
                interests = json.loads(r[3]) if r[3] else []
            except Exception:
                tags, interests = [], []
            results.append({
                "user_id": r[0],
                "tags": tags,
                "level": r[2] or 0,
                "interests": interests,
                "last_interaction": r[4],
                "conversation_rounds": r[5] or 0,
            })
        return results

    # ─────────────────────────────── A/B 测试统计（v5.18.0） ────────────────────────────────
    def record_ab_test_sent(self, group_name: str, format_version: str, count: int = 1) -> None:
        """记录 A/B 测试发送数。"""
        import time
        ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT INTO ab_test_stats (group_name, format_version, sent_count, ts)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_name, format_version) DO UPDATE SET
                    sent_count = sent_count + ?,
                    ts = ?
            """, (group_name, format_version, count, ts, count, ts))
            self.conn.commit()

    def record_ab_test_conversion(self, group_name: str, format_version: str, count: int = 1) -> None:
        """记录 A/B 测试转化数。"""
        import time
        ts = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT INTO ab_test_stats (group_name, format_version, conversion_count, ts)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_name, format_version) DO UPDATE SET
                    conversion_count = conversion_count + ?,
                    ts = ?
            """, (group_name, format_version, count, ts, count, ts))
            self.conn.commit()

    def get_ab_test_stats(self) -> dict:
        """获取 A/B 测试统计汇总。"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT format_version, SUM(sent_count), SUM(conversion_count) FROM ab_test_stats GROUP BY format_version")
            rows = c.fetchall()
        result = {"html_sent": 0, "html_conversions": 0, "rich_sent": 0, "rich_conversions": 0}
        for fmt, sent, conv in rows:
            if fmt == "html":
                result["html_sent"] = sent or 0
                result["html_conversions"] = conv or 0
            elif fmt == "rich":
                result["rich_sent"] = sent or 0
                result["rich_conversions"] = conv or 0
        return result

    # ─────────────────────────────── 按钮点击统计（v5.18.0） ────────────────────────────────
    def record_button_impression(self, button_id: str, style: str = "default") -> None:
        """记录按钮展示。"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT INTO button_click_stats (button_id, style, impressions, clicks)
                VALUES (?, ?, 1, 0)
                ON CONFLICT(button_id, style) DO UPDATE SET
                    impressions = impressions + 1,
                    last_updated = CURRENT_TIMESTAMP
            """, (button_id, style))
            self.conn.commit()

    def record_button_click(self, button_id: str, style: str = "default") -> None:
        """记录按钮点击。"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT INTO button_click_stats (button_id, style, impressions, clicks)
                VALUES (?, ?, 0, 1)
                ON CONFLICT(button_id, style) DO UPDATE SET
                    clicks = clicks + 1,
                    last_updated = CURRENT_TIMESTAMP
            """, (button_id, style))
            self.conn.commit()

    def get_button_stats(self) -> list:
        """获取按钮点击统计。"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT button_id, style, impressions, clicks FROM button_click_stats WHERE impressions > 0 OR clicks > 0 ORDER BY (clicks * 1.0 / MAX(impressions, 1)) DESC")
            rows = c.fetchall()
        return [
            {
                "button_id": r[0],
                "style": r[1],
                "impressions": r[2] or 0,
                "clicks": r[3] or 0,
                "ctr": (r[3] or 0) / max(1, r[2] or 0),
            }
            for r in rows
        ]
