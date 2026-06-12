# -*- coding: utf-8 -*-
"""社交功能域数据操作"""
import time
from datetime import datetime

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.social")


class SocialRepo:
    """社交相关数据库操作"""

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

    # ─────────────────────────────── 叫醒 ────────────────────────────────
    def set_wake_up(self, uid: int, wake_time: str):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO wake_up VALUES (?,?)", (uid, wake_time))
            self.conn.commit()

    def get_all_wake_ups(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT uid, wake_time FROM wake_up")
            return c.fetchall()

    # ─────────────────────────────── 寻宝 ────────────────────────────────
    def inc_puzzle_score(self, uid: int) -> tuple:
        """
        尝试增加寻宝积分。每天最多计1次，连续7天凑齐7分可领奖。
        返回 (当前分数, 今日是否已计, 连续天数)
        """
        today = datetime.now(_CST).strftime("%Y-%m-%d")  # 【修复v21.47】使用北京时间
        try:
            with self.lock:
                c = self.conn.cursor()
                c.execute("INSERT OR IGNORE INTO puzzle_scores VALUES (?,0)", (uid,))
                # 检查今天是否已计分
                c.execute("SELECT 1 FROM puzzle_daily WHERE uid=? AND date=?", (uid, today))
                if c.fetchone():
                    # 今天已计分
                    c.execute("SELECT score FROM puzzle_scores WHERE uid=?", (uid,))
                    return (c.fetchone()[0], True, 0)
                # 今天未计分，加分
                c.execute("INSERT OR REPLACE INTO puzzle_daily VALUES (?,?,?)", (uid, today, int(time.time())))
                c.execute("UPDATE puzzle_scores SET score=score+1 WHERE uid=?", (uid,))
                c.execute("SELECT score FROM puzzle_scores WHERE uid=?", (uid,))
                score = c.fetchone()[0]
                # 计算连续天数（连续7天有记录）
                consecutive = self._calc_consecutive_days(uid)
                if score >= 7:
                    c.execute("UPDATE puzzle_scores SET score=0 WHERE uid=?", (uid,))
                    self.conn.commit()
                    return (7, False, consecutive)
                self.conn.commit()
                return (score, False, consecutive)
        except Exception as e:
            logger.error(f"寻宝积分操作失败 uid={uid}: {e}")
            try:
                from modules.auto_tasks import report_fault
                report_fault("数据库操作失败", f"寻宝积分操作失败 uid={uid}: {str(e)[:80]}", "⚠️")
            except Exception as fault_err:
                self._db._log_db_error("report_fault 调用", fault_err, "error", f"寻宝积分 uid={uid}")
            return (0, False, 0)

    def _calc_consecutive_days(self, uid: int) -> int:
        """计算用户连续签到天数（由调用方保证在lock内调用，不再重复获取锁）"""
        c = self.conn.cursor()
        c.execute("SELECT date FROM puzzle_daily WHERE uid=? ORDER BY date DESC", (uid,))
        dates = [row[0] for row in c.fetchall()]
        if not dates:
            return 0
        count = 1
        from datetime import datetime as dt
        for i in range(1, len(dates)):
            try:
                prev = dt.strptime(dates[i-1], "%Y-%m-%d")
                curr = dt.strptime(dates[i], "%Y-%m-%d")
                if (prev - curr).days == 1:
                    count += 1
                else:
                    break
            except Exception as e:
                self._db._log_db_error("_calc_consecutive_days 日期解析", e, "warning", f"uid={uid}")
                break
        return count

    # ─────────────────────────────── 购物车 ──────────────────────────────
    def set_cart(self, uid: int):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO cart_recovery VALUES (?,?)",
                             (uid, int(time.time())))
            self.conn.commit()

    def get_expired_carts(self, delay_seconds: int = 86400):
        cutoff = int(time.time()) - delay_seconds
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT uid FROM cart_recovery WHERE ts<?", (cutoff,))
            rows = [r[0] for r in c.fetchall()]
            if rows:
                # 【v4.3.2修复S-09】添加长度限制，防止IN子句过长
                rows = rows[:100]
                self.conn.execute(f"DELETE FROM cart_recovery WHERE uid IN ({','.join('?'*len(rows))})",
                                 rows)
                self.conn.commit()
            return rows

    # ─────────────────────────────── 转化漏斗（事件化） ───────────────────
    def log_conversion_event(self, uid: int, event: str, mode: str = ""):
        """event: touched | interested | consulted | paid"""
        with self.lock:
            self.conn.execute(
                "INSERT INTO conversion_events(uid, event, ts, mode) VALUES (?, ?, ?, ?)",
                (uid, event, int(time.time()), mode)
            )
            self.conn.commit()

    def get_user_consult_count(self, uid: int, window: int = 86400) -> int:
        """查询用户convert咨询次数（默认24小时内）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM conversion_events WHERE uid=? AND event='consulted' AND ts>?",
                (uid, int(time.time()) - window)
            )
            row = c.fetchone()
            return row[0] if row else 0

    def get_funnel_summary(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT
                COUNT(DISTINCT CASE WHEN event='touched'    THEN uid END),
                COUNT(DISTINCT CASE WHEN event='interested' THEN uid END),
                COUNT(DISTINCT CASE WHEN event='consulted'  THEN uid END),
                COUNT(DISTINCT CASE WHEN event='paid'       THEN uid END)
                FROM conversion_events""")
            return c.fetchone()

    # ─────────────────────────────── 反馈 ────────────────────────────────
    def record_feedback(self, bot_msg_id: int, chat_id: int, user_id: int, feedback: str) -> bool:
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT OR REPLACE INTO reply_feedback (bot_msg_id, chat_id, user_id, feedback, ts) VALUES (?, ?, ?, ?, ?)",
                    (bot_msg_id, chat_id, user_id, feedback, int(time.time()))
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"record_feedback error: {e}")
                return False

    def get_feedback_stats(self, days: int = 7) -> dict:
        with self.lock:
            try:
                cutoff = int(time.time()) - days * 86400
                c = self.conn.cursor()
                c.execute("SELECT feedback, COUNT(*) FROM reply_feedback WHERE ts >= ? GROUP BY feedback", (cutoff,))
                counts = {"like": 0, "dislike": 0}
                for row in c.fetchall():
                    if row[0] in counts:
                        counts[row[0]] = row[1]
                total = counts["like"] + counts["dislike"]
                rate = round(counts["like"] / total * 100, 1) if total > 0 else 0
                c.execute("SELECT COUNT(*) FROM reply_feedback WHERE ts >= ? AND feedback = 'dislike'", (cutoff,))
                recent_dislike = c.fetchone()[0]
                return {"like": counts["like"], "dislike": counts["dislike"], "total": total, "satisfaction_rate": rate, "recent_dislike": recent_dislike}
            except Exception as e:
                logger.error(f"get_feedback_stats error: {e}")
                return {"like": 0, "dislike": 0, "total": 0, "satisfaction_rate": 0, "recent_dislike": 0}

    def get_recent_feedback(self, limit: int = 20) -> list:
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("SELECT bot_msg_id, chat_id, user_id, feedback, ts FROM reply_feedback ORDER BY ts DESC LIMIT ?", (limit,))
                return [{"bot_msg_id": r[0], "chat_id": r[1], "user_id": r[2], "feedback": r[3], "ts": r[4]} for r in c.fetchall()]
            except Exception as e:
                logger.error(f"get_recent_feedback error: {e}")
                return []
