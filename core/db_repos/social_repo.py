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
        self._fsm = None  # 延迟初始化 FunnelStateMachine

    @property
    def fsm(self):
        """延迟初始化漏斗状态机（避免循环导入）"""
        if self._fsm is None:
            from core.funnel_state_machine import FunnelStateMachine
            self._fsm = FunnelStateMachine(self._db)
        return self._fsm

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

    # ─────────────────────────────── 购物车（兼容旧接口 + 状态机集成）──
    def set_cart(self, uid: int, is_memory_assisted: bool = False):
        """
        将用户标记为购物车状态。
        同时写入旧表 cart_recovery（兼容）和 funnel_state 状态机，
        并初始化挽回时间线（15分钟后触发第一次挽回）。

        【TRAE SOLO CN v5.18.3审计修复】converted 用户复购时允许重新进入 carted，
        状态机 TRANSITION_MAP 已支持 converted→carted 流转。
        【阶段3-A】is_memory_assisted 透传给 funnel_state.transition 用于记忆归因。
        """
        with self.lock:
            # 旧表兼容
            self.conn.execute("INSERT OR REPLACE INTO cart_recovery VALUES (?,?)",
                             (uid, int(time.time())))
            self.conn.commit()
        # 状态机：转换到 carted（converted 用户复购时也允许，TRANSITION_MAP 已支持）
        if self.fsm.transition(uid, "carted", is_memory_assisted=is_memory_assisted):
            # 初始化挽回时间线：15分钟后第一次触发
            self.init_cart_recovery(uid)

    def get_expired_carts(self, delay_seconds: int = 86400):
        """
        获取超时未成交的购物车用户（兼容旧接口）。
        同时从旧表删除记录。
        """
        cutoff = int(time.time()) - delay_seconds
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT uid FROM cart_recovery WHERE ts<?", (cutoff,))
            rows = [r[0] for r in c.fetchall()]
            if rows:
                rows = rows[:100]
                self.conn.execute(f"DELETE FROM cart_recovery WHERE uid IN ({','.join('?'*len(rows))})",
                                 rows)
                self.conn.commit()
            return rows

    # ─────────────────────────────── 购物车挽回（新接口 - 时间衰减调度）──

    def init_cart_recovery(self, uid: int):
        """
        初始化购物车挽回时间线。
        设置 stage=0，并在 15分钟后触发第一次挽回。
        只在用户首次进入 carted 状态时调用。
        """
        now_ts = int(time.time())
        first_trigger = now_ts + 900  # 15分钟后
        return self.fsm.set_recovery_stage(uid, 0, first_trigger)

    def advance_recovery_stage(self, uid: int, stage: int) -> bool:
        """
        推进挽回阶段并设置下次触发时间。
        stage=1 → 2小时后触发
        stage=2 → 24小时后触发
        stage=3 → 终态，不再触发
        """
        now_ts = int(time.time())
        intervals = {1: 7200, 2: 86400}  # 2小时, 24小时
        next_ts = now_ts + intervals.get(stage, 999999999)
        return self.fsm.set_recovery_stage(uid, stage, next_ts)

    def get_pending_cart_recoveries(self, limit: int = 20) -> list:
        """
        获取当前需要触发挽回的用户列表。
        返回 [(uid, recovery_stage), ...]
        """
        return self.fsm.get_pending_recoveries()[:limit]

    def cancel_cart_recovery(self, uid: int):
        """用户已转化，取消所有挽回任务"""
        self.fsm.cancel_recovery(uid)

    # ─────────────────────────────── 转化漏斗（事件化 - 纯日志，状态由状态机管理）──
    def log_conversion_event(self, uid: int, event: str, mode: str = ""):
        """
        写入转化漏斗事件日志（仅记录，不改变状态机状态）。
        状态流转由 set_cart() / transition() 等显式方法控制。
        event: touched | interested | consulted | paid
        """
        with self.lock:
            self.conn.execute(
                "INSERT INTO conversion_events(uid, event, ts, mode) VALUES (?, ?, ?, ?)",
                (uid, event, int(time.time()), mode)
            )
            self.conn.commit()

    def log_paid(self, uid: int, value: float = 0, chat_id: int = 0, mode: str = "",
                 is_memory_assisted: bool = False):
        """
        记录支付事件：写入日志 + 状态机转换到 converted + 取消挽回。
        这是唯一应触发 converted 状态的入口。

        【阶段3-A】is_memory_assisted 透传给 funnel_state.transition 用于记忆归因。
        """
        # 事件日志
        self.log_conversion_event(uid, "paid", mode)
        # 写入 conversions 表（金额追踪）
        with self.lock:
            self.conn.execute(
                "INSERT INTO conversions(uid, event, value, chat_id, ts) VALUES (?, ?, ?, ?, ?)",
                (uid, "paid", value, chat_id, int(time.time()))
            )
            self.conn.commit()
        # 状态机：转换到 converted + 取消挽回
        if self.fsm.transition(uid, "converted", mode, is_memory_assisted=is_memory_assisted):
            self.cancel_cart_recovery(uid)
            logger.info(f"💰 用户转化: uid={uid} value={value}")

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
