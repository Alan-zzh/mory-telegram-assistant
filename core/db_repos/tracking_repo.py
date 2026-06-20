# -*- coding: utf-8 -*-
"""追踪功能域数据操作"""
import time
from datetime import datetime

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.tracking")


class TrackingRepo:
    """追踪相关数据库操作"""

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

    # ─────────────────────────────── 阅后即焚 ────────────────────────────
    def track_reply(self, bot_msg_id: int, chat_id: int, user_msg_id: int):
        """记录机器人回复，追踪原消息是否被删（复合主键：bot_msg_id+chat_id）

        [v5.24.0] 改回标准模式，由 WriteQueueConnectionProxy 自动拦截走队列
        """
        if not bot_msg_id or not chat_id or not user_msg_id:
            logger.error(f"📌 track_reply参数无效: bot={bot_msg_id} chat={chat_id} user={user_msg_id}")
            return

        ts = int(time.time())
        try:
            with self.lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO reply_tracking (bot_msg_id, chat_id, user_msg_id, ts, replied) VALUES (?,?,?,?,0)",
                    (bot_msg_id, chat_id, user_msg_id, ts),
                )
                self.conn.commit()
            logger.debug(f"📌 阅后即焚追踪：bot={bot_msg_id} chat={chat_id} user={user_msg_id} ts={ts}")
        except Exception as e:
            logger.error(f"📌 阅后即焚追踪失败：{e}")
            try:
                from modules.auto_tasks import report_fault
                report_fault("阅后即焚追踪失败", f"bot_msg={bot_msg_id} chat={chat_id}: {str(e)[:80]}", "⚠️")
            except Exception as fault_err:
                self._db._log_db_error("report_fault 调用", fault_err, "error", f"阅后即焚 bot_msg={bot_msg_id}")

    def track_bot_message(self, chat_id: int, bot_msg_id: int):
        """[TRAE SOLO CN] 追踪Bot主动消息（新闻/问候等），24小时TTL后自动删除

        与track_reply不同：user_msg_id=0表示无用户触发，replied=1表示不需要等用户回复
        [v5.24.0] 改回标准模式，由 WriteQueueConnectionProxy 自动拦截走队列
        """
        ts = int(time.time())
        try:
            with self.lock:
                self.conn.execute(
                    "INSERT OR REPLACE INTO reply_tracking (bot_msg_id, chat_id, user_msg_id, ts, replied) VALUES (?,?,?,?,1)",
                    (bot_msg_id, chat_id, 0, ts),
                )
                self.conn.commit()
            logger.debug(f"📌 Bot主动消息追踪：bot={bot_msg_id} chat={chat_id} ts={ts}")
        except Exception as e:
            logger.error(f"📌 Bot主动消息追踪失败：{e}")

    def mark_replied(self, bot_msg_id: int, chat_id: int = 0):
        """用户回复了机器人的消息，标记为已回复（不自动删除）"""
        with self.lock:
            if chat_id:
                self.conn.execute("UPDATE reply_tracking SET replied=1 WHERE bot_msg_id=? AND chat_id=?",
                                 (bot_msg_id, chat_id))
            else:
                self.conn.execute("UPDATE reply_tracking SET replied=1 WHERE bot_msg_id=?",
                                 (bot_msg_id,))
            self.conn.commit()

    def get_replies_to(self, user_msg_id: int, chat_id: int):
        """获取机器人对某条消息的所有回复（用于消息被删时同步删除）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, replied FROM reply_tracking
                         WHERE user_msg_id=? AND chat_id=?""", (user_msg_id, chat_id))
            return c.fetchall()

    def get_recent_unreplied(self, min_age: int = 300, max_age: int = 1800, limit: int = 10):
        """获取最近未回复的消息（用于探测用户是否删消息）

        Args:
            min_age: 最小存活秒数（默认5分钟，避免探测刚发的消息）
            max_age: 最大存活秒数（默认30分钟）
            limit: 最多返回条数（防止一次探测太多）
        """
        now = int(time.time())
        since = now - max_age
        until = now - min_age
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts BETWEEN ? AND ? AND user_msg_id>0 AND replied=0
                         ORDER BY ts ASC LIMIT ?""", (since, until, limit))
            return c.fetchall()

    def get_orphan_messages(self, window: int = 1800):
        """返回超过window秒未被回复的孤儿消息 + 超时的Bot主动消息。

        两类消息：
        1. 用户触发的Bot回复：replied=0且user_msg_id>0 → 用户未回复的孤儿
        2. Bot主动消息：replied=1且user_msg_id=0 → 超过TTL的定时消息
        用户回复了机器人的消息(replied=1且user_msg_id>0)获得豁免，不应被清理。

        【v5.12.4变更】窗口从 86400 缩到 1800（30分钟，用户决策）。
        防止孤儿消息长时间堆积在群中影响体验。
        """
        cutoff = int(time.time()) - window
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts<? AND (
                             (user_msg_id>0 AND replied=0)
                             OR
                             (user_msg_id=0 AND replied=1)
                         )""", (cutoff,))
            return c.fetchall()

    def get_unreplied_messages(self):
        """返回所有未被回复的机器人消息（不限时间，用于清群无人理）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE replied=0""")
            return c.fetchall()

    def get_ignored_messages(self, min_age: int = 1800):
        """智能判断「真正无人理」的消息：
        - replied=0（没人显式回复）
        - 且消息已存在超过 min_age 秒（默认30分钟，避免误删刚发的）
        - 返回 (bot_msg_id, chat_id, user_msg_id)
        """
        cutoff = int(time.time()) - min_age
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE replied=0 AND ts<?""", (cutoff,))
            return c.fetchall()

    def get_all_tracked_messages(self, window: int = 86400):
        """返回窗口内的所有追踪消息（不限replied状态，用于清全部回复）"""
        now = int(time.time())
        since = now - window
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts>?""", (since,))
            return c.fetchall()

    def get_unconfirmed_messages(self, window: int = 86400):
        """返回window时间内未被回复的追踪消息（探测原消息是否还在）。

        【审查修复v21.47】
        - 窗口从1小时扩大到24小时，修复23小时探测盲区
        - 按时间倒序，确保优先探测新消息
        - 尊重"豁免保护"：只有replied=0的消息才需要探测
        """
        now = int(time.time())
        since = now - window
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                         WHERE ts>? AND user_msg_id>0 AND replied=0 ORDER BY ts DESC""", (since,))
            return c.fetchall()

    def delete_tracked(self, bot_msg_id: int, chat_id: int = 0):
        """删除阅后即焚追踪记录"""
        with self.lock:
            if chat_id:
                self.conn.execute("DELETE FROM reply_tracking WHERE bot_msg_id=? AND chat_id=?", (bot_msg_id, chat_id))
            else:
                self.conn.execute("DELETE FROM reply_tracking WHERE bot_msg_id=?", (bot_msg_id,))
            self.conn.commit()

    def get_tracking_stats(self):
        """获取追踪统计"""
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM reply_tracking")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM reply_tracking WHERE replied=0")
        unreplied = c.fetchone()[0]
        return total, unreplied

    def cleanup_old_records(self, cutoff: int):
        """清理过期的追踪记录（线程安全）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM reply_tracking WHERE ts < ?", (cutoff,))
            deleted_track = c.rowcount
            c.execute("DELETE FROM spam_track WHERE COALESCE(window_start,0) < ?", (cutoff,))
            deleted_spam = c.rowcount
            c.execute("DELETE FROM puzzle_daily WHERE ts < ?", (cutoff,))
            deleted_puzzle = c.rowcount
            self.conn.commit()
        return deleted_track, deleted_spam, deleted_puzzle

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.2.3】频道内容追踪
    # ═══════════════════════════════════════════════════════════════════════════

    def track_channel_message(self, chat_id: int, message_id: int, content_type: str = "text"):
        """记录机器人发的频道/群消息，用于追踪浏览量"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO channel_tracking
                         (chat_id, message_id, content_type, posted_at, initial_views, current_views, last_checked_at)
                         VALUES (?,?,?,?,0,0,?)""",
                     (chat_id, message_id, content_type, int(time.time()), int(time.time())))
            self.conn.commit()

    def update_channel_views(self, chat_id: int, message_id: int, views: int):
        """更新消息浏览量"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""UPDATE channel_tracking SET current_views=?, last_checked_at=?
                         WHERE chat_id=? AND message_id=?""",
                     (views, int(time.time()), chat_id, message_id))
            self.conn.commit()

    def get_channel_tracking(self, chat_id: int = 0, limit: int = 20) -> list:
        """获取频道内容表现数据"""
        c = self.conn.cursor()
        if chat_id:
            c.execute("""SELECT chat_id, message_id, content_type, posted_at, current_views
                         FROM channel_tracking WHERE chat_id=? ORDER BY posted_at DESC LIMIT ?""",
                     (chat_id, limit))
        else:
            c.execute("""SELECT chat_id, message_id, content_type, posted_at, current_views
                         FROM channel_tracking ORDER BY posted_at DESC LIMIT ?""", (limit,))
        return c.fetchall()

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v5.12.0】孤儿播报追踪（升级播报30S删、早安午安晚安链式互删）
    # ═══════════════════════════════════════════════════════════════════════════

    def track_broadcast(self, chat_id: int, category: str, msg_id: int):
        """[Trae CN] 记录一条孤儿播报（升级/早安/午安/晚安/自定义）

        复合主键 (chat_id, category) → 同一群同类型只保留最新一条
        用于：
        1. 孤儿播报：30秒后由调度器删除
        2. 早安/午安/晚安互删：发新问候前查上一条并删除
        """
        with self.lock:
            try:
                ts = int(time.time())
                self.conn.execute(
                    "INSERT OR REPLACE INTO broadcast_tracking (chat_id, category, msg_id, ts) VALUES (?,?,?,?)",
                    (chat_id, category, msg_id, ts),
                )
                self.conn.commit()
                logger.info(f"📌 孤儿播报追踪：chat={chat_id} category={category} msg={msg_id}")
            except Exception as e:
                logger.error(f"📌 孤儿播报追踪失败：{e}")

    def get_last_broadcast(self, chat_id: int, category: str):
        """[Trae CN] 获取某群某类播报的最新一条 (msg_id, ts)，无则返回 None

        用于：
        1. 链式互删：发新问候前先查到上一条问候并删除
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                "SELECT msg_id, ts FROM broadcast_tracking WHERE chat_id=? AND category=? ORDER BY ts DESC LIMIT 1",
                (chat_id, category),
            )
            row = c.fetchone()
            return (row[0], row[1]) if row else None

    def delete_broadcast(self, chat_id: int, category: str):
        """[Trae CN] 删除某群某类播报的追踪记录（消息已删除后清理用）"""
        with self.lock:
            try:
                self.conn.execute(
                    "DELETE FROM broadcast_tracking WHERE chat_id=? AND category=?",
                    (chat_id, category),
                )
                self.conn.commit()
            except Exception as e:
                logger.error(f"📌 删除播报追踪失败：{e}")

    def cleanup_old_broadcasts(self, before_ts: int) -> int:
        """[Trae CN] 清理指定时间戳之前的播报追踪记录（防止表膨胀），返回删除行数"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM broadcast_tracking WHERE ts<?", (before_ts,))
            deleted = c.rowcount
            self.conn.commit()
            return deleted

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v5.12.0】孤儿清理日志（_job_burn_orphan 每次执行写一行）
    # ═══════════════════════════════════════════════════════════════════════════

    def log_orphan_cleanup(self, found_count: int, deleted_count: int,
                           skipped_count: int = 0, error: str = None,
                           trigger: str = "scheduled") -> int:
        """[Trae CN v5.12.0] 记录一次孤儿清理执行结果

        Args:
            found_count: 本次发现的孤儿消息数
            deleted_count: 实际删除成功的条数
            skipped_count: 跳过删除的条数（如开关关闭 / 权限不足）
            error: 异常信息，None=无错误
            trigger: 触发方式（scheduled / manual / force）

        Returns:
            新插入行的 id
        """
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO orphan_cleanup_log
                   (run_at, found_count, deleted_count, skipped_count, error, trigger)
                   VALUES (?,?,?,?,?,?)""",
                (int(time.time()), int(found_count), int(deleted_count),
                 int(skipped_count), error, trigger),
            )
            self.conn.commit()
            return cur.lastrowid

    def get_last_orphan_cleanup(self) -> dict:
        """[Trae CN v5.12.0] 获取最近一次孤儿清理记录（字典格式），无则返回 None"""
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                """SELECT id, run_at, found_count, deleted_count, skipped_count, error, trigger
                   FROM orphan_cleanup_log ORDER BY run_at DESC LIMIT 1"""
            )
            row = c.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "run_at": row[1],
                "found_count": row[2],
                "deleted_count": row[3],
                "skipped_count": row[4],
                "error": row[5],
                "trigger": row[6],
            }

    def get_orphan_cleanup_history(self, limit: int = 20) -> list:
        """[Trae CN v5.12.0] 获取最近 N 条孤儿清理历史（用于 Dashboard 历史曲线）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                """SELECT id, run_at, found_count, deleted_count, skipped_count, error, trigger
                   FROM orphan_cleanup_log ORDER BY run_at DESC LIMIT ?""",
                (limit,),
            )
            rows = c.fetchall()
            return [
                {
                    "id": r[0],
                    "run_at": r[1],
                    "found_count": r[2],
                    "deleted_count": r[3],
                    "skipped_count": r[4],
                    "error": r[5],
                    "trigger": r[6],
                }
                for r in rows
            ]

    def get_orphan_stats(self) -> dict:
        """[Trae CN v5.12.0] 一站式孤儿统计（用于 Dashboard /api/orphan/stats）

        Returns:
            {
                "tracked_count": int,           # reply_tracking 总记录数
                "bot_msg_count": int,           # Bot主动消息数
                "unreplied_count": int,         # 用户未回复数
                "orphan_24h_count": int,        # 24h 超时孤儿数（v5.12.0 旧窗口，向后兼容）
                "orphan_30m_count": int,        # 30分钟超时孤儿数（v5.12.4 新窗口）
                "last_cleanup": dict|None,      # 最近一次清理
            }
        """
        now = int(time.time())
        cutoff_24h = now - 86400
        cutoff_30m = now - 1800
        with self.lock:
            c = self.conn.cursor()
            stats = {}
            c.execute("SELECT COUNT(*) FROM reply_tracking")
            stats["tracked_count"] = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM reply_tracking WHERE user_msg_id=0 AND replied=1")
            stats["bot_msg_count"] = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM reply_tracking WHERE user_msg_id>0 AND replied=0")
            stats["unreplied_count"] = c.fetchone()[0]
            c.execute(
                """SELECT COUNT(*) FROM reply_tracking WHERE ts<? AND (
                       (user_msg_id>0 AND replied=0)
                       OR (user_msg_id=0 AND replied=1))""",
                (cutoff_24h,),
            )
            stats["orphan_24h_count"] = c.fetchone()[0]
            # [v5.12.4] 30分钟窗口（用户决策）
            c.execute(
                """SELECT COUNT(*) FROM reply_tracking WHERE ts<? AND (
                       (user_msg_id>0 AND replied=0)
                       OR (user_msg_id=0 AND replied=1))""",
                (cutoff_30m,),
            )
            stats["orphan_30m_count"] = c.fetchone()[0]
            stats["last_cleanup"] = None  # 避免嵌套锁
        stats["last_cleanup"] = self.get_last_orphan_cleanup()
        return stats

    # ═══════════════════════════════════════════════════════════════════════════
    # [v5.14.0] 商业搭讪事件日志（Bot 主动搭讪用户记录 + 转化追踪）
    # ═══════════════════════════════════════════════════════════════════════════

    def log_proactive_engage(self, uid: int, chat_id: int, uname: str,
                              msg: str, matched_keyword: str,
                              reply_text: str = "") -> int:
        """[v5.14.0] 记录一次商业搭讪事件

        Args:
            uid: 被搭讪用户ID
            chat_id: 群ID
            uname: 用户名
            msg: 触发搭讪的原始消息
            matched_keyword: 命中的商业关键词
            reply_text: Bot 发送的搭讪回复

        Returns:
            新插入行的 id
        """
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO proactive_engage_log
                   (uid, chat_id, uname, msg, matched_keyword, reply_text, ts, converted)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (int(uid), int(chat_id), str(uname)[:64], str(msg)[:500],
                 str(matched_keyword)[:64], str(reply_text)[:500], int(time.time())),
            )
            self.conn.commit()
            return cur.lastrowid

    def get_recent_engages(self, limit: int = 50, uid: int = 0) -> list:
        """[v5.14.0] 获取最近 N 条搭讪记录

        Args:
            limit: 最多返回条数
            uid: 指定用户ID，0=所有用户

        Returns:
            列表，每项 {id, uid, chat_id, uname, msg, matched_keyword, reply_text, ts, converted, ts_str}
        """
        with self.lock:
            c = self.conn.cursor()
            if uid > 0:
                c.execute(
                    """SELECT id, uid, chat_id, uname, msg, matched_keyword, reply_text, ts, converted
                       FROM proactive_engage_log WHERE uid=? ORDER BY ts DESC LIMIT ?""",
                    (uid, limit),
                )
            else:
                c.execute(
                    """SELECT id, uid, chat_id, uname, msg, matched_keyword, reply_text, ts, converted
                       FROM proactive_engage_log ORDER BY ts DESC LIMIT ?""",
                    (limit,),
                )
            rows = c.fetchall()
            return [
                {
                    "id": r[0],
                    "uid": r[1],
                    "chat_id": r[2],
                    "uname": r[3],
                    "msg": r[4],
                    "matched_keyword": r[5],
                    "reply_text": r[6],
                    "ts": r[7],
                    "converted": r[8],
                }
                for r in rows
            ]

    def get_engaged_stats(self) -> dict:
        """[v5.14.0] 搭讪统计一站式查询

        Returns:
            {
                "total_count": int,            # 累计搭讪次数
                "today_count": int,            # 今日搭讪次数
                "converted_count": int,        # 累计转化（24h内下单）
                "conversion_rate": float,      # 转化率（百分比）
            }
        """
        with self.lock:
            c = self.conn.cursor()
            # 累计
            c.execute("SELECT COUNT(*) FROM proactive_engage_log")
            total = c.fetchone()[0]
            # 今日（按本地CST 0点为分界）
            today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            c.execute("SELECT COUNT(*) FROM proactive_engage_log WHERE ts>=?", (today_start,))
            today = c.fetchone()[0]
            # 转化数（24h内下单的搭讪用户）
            c.execute("SELECT COUNT(*) FROM proactive_engage_log WHERE converted=1")
            converted = c.fetchone()[0]
            rate = (converted / total * 100) if total > 0 else 0.0
            return {
                "total_count": total,
                "today_count": today,
                "converted_count": converted,
                "conversion_rate": round(rate, 2),
            }

    def get_channel_stats_summary(self) -> dict:
        """获取频道统计摘要"""
        c = self.conn.cursor()
        # 【v4.3.2修复S-02】每次execute后立即保存fetchone结果，不重复调用
        c.execute("SELECT COUNT(*) FROM channel_tracking")
        row = c.fetchone()
        total_posts = row[0] if row else 0
        # 总浏览量
        c.execute("SELECT COALESCE(SUM(current_views),0) FROM channel_tracking")
        row = c.fetchone()
        total_views = row[0] if row else 0
        # 今日发布数
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM channel_tracking WHERE date(posted_at, 'unixepoch', '+8 hours')=?", (today,))
        row = c.fetchone()
        today_posts = row[0] if row else 0
        # 平均浏览量
        avg_views = total_views // max(total_posts, 1)
        return {
            "total_posts": total_posts,
            "total_views": total_views,
            "today_posts": today_posts,
            "avg_views": avg_views
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.5.25】日报增强查询
    # ═══════════════════════════════════════════════════════════════════════════

    def get_daily_active_users(self, date_str: str = None, chat_id: int = 0) -> int:
        """【v4.17.0修复】获取指定日期发言活跃用户数（从speech_daily表统计，而非reply_tracking）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        c = self.conn.cursor()
        if chat_id:
            c.execute("SELECT COUNT(DISTINCT uid) FROM speech_daily WHERE date=? AND chat_id=?",
                     (date_str, chat_id))
        else:
            c.execute("SELECT COUNT(DISTINCT uid) FROM speech_daily WHERE date=?",
                     (date_str,))
        row = c.fetchone()
        return row[0] if row else 0

    def get_daily_bot_messages(self, date_str: str = None) -> int:
        """获取指定日期Bot发送的消息数（从channel_tracking表）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        c = self.conn.cursor()
        c.execute("SELECT COUNT(*) FROM channel_tracking WHERE date(posted_at, 'unixepoch', '+8 hours')=?", (date_str,))
        row = c.fetchone()
        return row[0] if row else 0

    def get_daily_replies(self, date_str: str = None) -> int:
        """获取指定日期用户回复Bot消息数（从reply_tracking表）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        c = self.conn.cursor()
        day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c.execute("SELECT COUNT(*) FROM reply_tracking WHERE ts>=? AND ts<? AND replied=1", (day_start, day_end))
        row = c.fetchone()
        return row[0] if row else 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.9.5新增】频道原生内容管理
    # ═══════════════════════════════════════════════════════════════════════════

    def track_channel_post(self, chat_id: int, message_id: int, posted_at: int, views: int = 0, forwards: int = 0, content_type: str = "text"):
        """记录频道原生内容（非Bot发送的消息）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""INSERT OR IGNORE INTO channel_posts
                         (chat_id, message_id, posted_at, views, forwards, content_type)
                         VALUES (?,?,?,?,?,?)""",
                     (chat_id, message_id, posted_at, views, forwards, content_type))
            self.conn.commit()

    def update_channel_post_views(self, chat_id: int, message_id: int, views: int, forwards: int = 0):
        """更新频道原生内容的浏览量"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""UPDATE channel_posts SET views=?, forwards=?
                         WHERE chat_id=? AND message_id=?""",
                     (views, forwards, chat_id, message_id))
            self.conn.commit()

    def get_channel_post_stats(self, chat_id: int, date_str: str = None) -> dict:
        """获取频道原生内容统计"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c = self.conn.cursor()
        c.execute("""SELECT COUNT(*), COALESCE(SUM(views),0), COALESCE(SUM(forwards),0)
                     FROM channel_posts WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, day_start, day_end))
        row = c.fetchone()
        if row:
            return {"posts": row[0], "views": row[1], "forwards": row[2], "avg_views": row[1] // max(row[0], 1)}
        return {"posts": 0, "views": 0, "forwards": 0, "avg_views": 0}

    def get_channel_recent_posts(self, chat_id: int, limit: int = 10) -> list:
        """【v4.9.7新增】获取频道最近N条帖子（用于浏览量刷新）"""
        c = self.conn.cursor()
        c.execute("""SELECT message_id, views, forwards FROM channel_posts
                     WHERE chat_id=? ORDER BY posted_at DESC LIMIT ?""",
                 (chat_id, limit))
        rows = c.fetchall()
        return [{"message_id": r[0], "views": r[1], "forwards": r[2]} for r in rows]

    def get_channel_top_posts(self, chat_id: int, date_str: str = None, threshold: float = 2.0) -> int:
        """【v4.9.7新增】获取频道指定日期浏览量超过均值*threshold的爆款帖数"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c = self.conn.cursor()
        # 先算平均浏览量
        c.execute("""SELECT COALESCE(AVG(views),0) FROM channel_posts
                     WHERE chat_id=? AND posted_at>=? AND posted_at<? AND views>0""",
                 (chat_id, day_start, day_end))
        avg_views = c.fetchone()[0]
        if avg_views <= 0:
            return 0
        # 再算超过阈值的帖子数
        c.execute("""SELECT COUNT(*) FROM channel_posts
                     WHERE chat_id=? AND posted_at>=? AND posted_at<? AND views>?""",
                 (chat_id, day_start, day_end, avg_views * threshold))
        count = c.fetchone()[0]
        return count

    def get_channel_avg_views(self, chat_id: int, date_str: str = None) -> float:
        """【v4.9.7新增】获取频道指定日期的平均浏览量"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c = self.conn.cursor()
        c.execute("""SELECT COALESCE(AVG(views),0) FROM channel_posts
                     WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, day_start, day_end))
        row = c.fetchone()
        return row[0] if row else 0.0

    def get_channel_posts_in_range(self, chat_id: int, start_ts: int, end_ts: int) -> dict:
        """【v4.9.5修复】获取频道在时间范围内的发帖和浏览量统计（包含原生内容+Bot消息）"""
        c = self.conn.cursor()
        # Bot消息
        c.execute("""SELECT COUNT(*), COALESCE(SUM(current_views),0)
                     FROM channel_tracking WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, start_ts, end_ts))
        bot_row = c.fetchone()
        # 频道原生内容
        c.execute("""SELECT COUNT(*), COALESCE(SUM(views),0)
                     FROM channel_posts WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, start_ts, end_ts))
        native_row = c.fetchone()
        total_posts = (bot_row[0] if bot_row else 0) + (native_row[0] if native_row else 0)
        total_views = (bot_row[1] if bot_row else 0) + (native_row[1] if native_row else 0)
        return {"posts": total_posts, "views": total_views, "avg_views": total_views // max(total_posts, 1)}

    def get_channel_daily_stats(self, chat_id: int, date_str: str = None) -> dict:
        """【v4.9.5修复】获取频道指定日期的发帖和浏览量统计（包含原生内容+Bot消息）"""
        if not date_str:
            date_str = datetime.now(_CST).strftime("%Y-%m-%d")
        day_start = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
        day_end = day_start + 86400
        c = self.conn.cursor()
        # Bot消息
        c.execute("""SELECT COUNT(*), COALESCE(SUM(current_views),0)
                     FROM channel_tracking WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, day_start, day_end))
        bot_row = c.fetchone()
        # 频道原生内容
        c.execute("""SELECT COUNT(*), COALESCE(SUM(views),0)
                     FROM channel_posts WHERE chat_id=? AND posted_at>=? AND posted_at<?""",
                 (chat_id, day_start, day_end))
        native_row = c.fetchone()
        total_posts = (bot_row[0] if bot_row else 0) + (native_row[0] if native_row else 0)
        total_views = (bot_row[1] if bot_row else 0) + (native_row[1] if native_row else 0)
        return {"posts": total_posts, "views": total_views, "avg_views": total_views // max(total_posts, 1)}
