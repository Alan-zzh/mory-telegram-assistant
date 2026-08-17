# -*- coding: utf-8 -*-
"""群管功能域数据操作"""
import time
from datetime import datetime, timedelta

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.groups")


class GroupRepo:
    """群管相关数据库操作"""

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

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.2.3】群数据统计
    # ═══════════════════════════════════════════════════════════════════════════

    def record_group_join(self, chat_id: int = 0, user_id: int = 0):
        """记录用户入群（带user_id幂等保护）"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            c = self.conn.cursor()
            # 【v4.9.5】幂等性保护：同一用户同一天多次入群只记一次
            if user_id:
                c.execute("SELECT 1 FROM group_join_log WHERE date=? AND chat_id=? AND user_id=?", (today, chat_id, user_id))
                if c.fetchone():
                    logger.debug(f"📊 入群去重: uid={user_id} chat_id={chat_id} date={today}")
                    return
                c.execute("INSERT OR IGNORE INTO group_join_log (date, chat_id, user_id, ts) VALUES (?,?,?,?)",
                         (today, chat_id, user_id, int(time.time())))
            c.execute("SELECT joined_count FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET joined_count=joined_count+1, net_count=net_count+1 WHERE date=? AND chat_id=?", (today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, chat_id, created_at) VALUES (?,1,0,1,?,?)",
                         (today, chat_id, int(time.time())))
            self.conn.commit()
            logger.debug(f"📊 记录入群: chat_id={chat_id} date={today}")

    def record_group_left(self, chat_id: int = 0, user_id: int = 0):
        """记录用户离群（带user_id幂等保护）"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            c = self.conn.cursor()
            # 【v4.9.5】幂等性保护：同一用户同一天多次离群只记一次
            if user_id:
                c.execute("SELECT 1 FROM group_left_log WHERE date=? AND chat_id=? AND user_id=?", (today, chat_id, user_id))
                if c.fetchone():
                    logger.debug(f"📊 离群去重: uid={user_id} chat_id={chat_id} date={today}")
                    return
                c.execute("INSERT OR IGNORE INTO group_left_log (date, chat_id, user_id, ts) VALUES (?,?,?,?)",
                         (today, chat_id, user_id, int(time.time())))
            c.execute("SELECT left_count FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET left_count=left_count+1, net_count=net_count-1 WHERE date=? AND chat_id=?", (today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, chat_id, created_at) VALUES (?,0,1,-1,?,?)",
                         (today, chat_id, int(time.time())))
            self.conn.commit()
            logger.debug(f"📊 记录离群: chat_id={chat_id} date={today}")

    def update_group_total_members(self, total: int, chat_id: int = 0):
        """更新群成员总数"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id FROM group_stats WHERE date=? AND chat_id=?", (today, chat_id))
            row = c.fetchone()
            if row:
                c.execute("UPDATE group_stats SET total_members=? WHERE date=? AND chat_id=?", (total, today, chat_id))
            else:
                c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, total_members, chat_id, created_at) VALUES (?,0,0,0,?,?,?)",
                         (today, total, chat_id, int(time.time())))
            self.conn.commit()

    def get_group_stats(self, days: int = 7) -> list:
        """获取最近N天的群统计"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT date, joined_count, left_count, net_count, total_members
                         FROM group_stats ORDER BY date DESC LIMIT ?""", (days,))
            return c.fetchall()

    def get_group_stats_by_date(self, target_date: str = None) -> list:
        """获取指定日期的群统计"""
        if not target_date:
            target_date = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT date, chat_id, joined_count, left_count, net_count, total_members
                         FROM group_stats WHERE date = ?""", (target_date,))
            return c.fetchall()

    def get_group_stats_by_chat_id(self, target_date: str, chat_id: int) -> dict:
        """【v4.5.36新增】获取指定日期+chat_id的群统计"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT joined_count, left_count, net_count, total_members
                         FROM group_stats WHERE date=? AND chat_id=?""", (target_date, chat_id))
            row = c.fetchone()
            if row:
                return {"joined": row[0] or 0, "left": row[1] or 0, "net": row[2] or 0, "total": row[3] or 0}
            return {"joined": 0, "left": 0, "net": 0, "total": 0}

    def get_weekly_group_stats(self, start_date: str, end_date: str, chat_id: int = 0) -> dict:
        """获取指定日期范围的群统计汇总【v4.5.36修复】chat_id参数化，不再硬编码0"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT COALESCE(SUM(joined_count),0), COALESCE(SUM(left_count),0),
                         COALESCE(SUM(net_count),0), AVG(total_members)
                         FROM group_stats WHERE date>=? AND date<=? AND chat_id=?""",
                     (start_date, end_date, chat_id))
            row = c.fetchone()
            if row:
                return {"joined": row[0], "left": row[1], "net": row[2], "avg_members": int(row[3] or 0)}
            return {"joined": 0, "left": 0, "net": 0, "avg_members": 0}

    def get_weekly_channel_member_stats(self, chat_id: int, start_date: str, end_date: str) -> dict:
        """获取指定频道在日期范围内的成员数变化"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT MIN(total_members), MAX(total_members), AVG(total_members)
                         FROM group_stats WHERE chat_id=? AND date>=? AND date<=?""",
                     (chat_id, start_date, end_date))
            row = c.fetchone()
            if row and row[2]:
                return {"min": row[0] or 0, "max": row[1] or 0, "avg": int(row[2])}
            return {"min": 0, "max": 0, "avg": 0}

    def calibrate_group_stats(self, chat_id: int, current_count: int):
        """【v5.3.1修复】成员数校准：对比API实时人数与昨日记录，修正漏记的入群/离群数"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT total_members FROM group_stats WHERE chat_id=? AND date=? ORDER BY date DESC LIMIT 1",
                     (chat_id, yesterday))
            row = c.fetchone()
            yesterday_total = row[0] if row and row[0] else 0

            if yesterday_total <= 0:
                return

            c.execute("SELECT joined_count, left_count, net_count FROM group_stats WHERE chat_id=? AND date=?", (chat_id, today))
            today_row = c.fetchone()
            event_joined = today_row[0] if today_row else 0
            event_left = today_row[1] if today_row else 0
            event_net = today_row[2] if today_row else 0

            actual_net = current_count - yesterday_total
            delta = actual_net - event_net

            if abs(delta) > 1:
                if today_row:
                    # 拆分修正：正差值=多记入群，负差值=多记离群
                    if delta > 0:
                        c.execute("UPDATE group_stats SET joined_count=joined_count+?, net_count=net_count+? WHERE date=? AND chat_id=?",
                                 (delta, delta, today, chat_id))
                    else:
                        c.execute("UPDATE group_stats SET left_count=left_count+?, net_count=net_count+? WHERE date=? AND chat_id=?",
                                 (abs(delta), delta, today, chat_id))
                else:
                    c.execute("INSERT INTO group_stats (date, joined_count, left_count, net_count, total_members, chat_id, created_at) VALUES (?,?,?,?,?,?,?)",
                             (today, max(delta, 0), max(-delta, 0), delta, current_count, chat_id, int(time.time())))
                self.conn.commit()
                logger.info(f"📊 校准: chat_id={chat_id} 事件入群={event_joined}/离群={event_left} 实际净增={actual_net} 修正={delta:+d}")

    def get_group_total_members_latest(self, chat_id: int = 0) -> int:
        """获取群成员总数（取最近一条记录的total_members）"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT total_members FROM group_stats WHERE chat_id=? ORDER BY date DESC LIMIT 1", (chat_id,))
            row = c.fetchone()
            return row[0] if row and row[0] else 0

    # ─────────────────────────────── 禁言 ────────────────────────────────
    def mute_user(self, uid: int, chat_id: int, minutes: int, reason: str = "违反群规"):
        until = int(time.time()) + minutes * 60
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO mute_records VALUES (?,?,?,?)",
                             (uid, chat_id, until, reason))
            self.conn.commit()

    def is_muted(self, uid: int, chat_id: int = 0) -> bool:
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT mute_until FROM mute_records WHERE uid=? AND chat_id=?", (uid, chat_id))
            row = c.fetchone()
            if row:
                if row[0] > int(time.time()):
                    return True
                self.conn.execute("DELETE FROM mute_records WHERE uid=? AND chat_id=?", (uid, chat_id))
                self.conn.commit()
            return False

    # ─────────────────────────────── 黑名单 ──────────────────────────────
    def blacklist_add(self, uid: int, reason: str = "垃圾信息"):
        with self.lock:
            self.conn.execute("INSERT OR IGNORE INTO blacklist VALUES (?,?,?)",
                             (uid, reason, int(time.time())))
            self.conn.commit()

    def blacklist_remove(self, uid: int):
        """从黑名单移除用户（用于自助解封）"""
        with self.lock:
            self.conn.execute("DELETE FROM blacklist WHERE uid=?", (uid,))
            self.conn.commit()

    def snapshot_message(self, chat_id: int, msg_id: int, user_id: int, text: str, ts: int = None) -> bool:
        """
        [TRAE SOLO CN] v5.15.3 新增：消息追踪快照
        AGENTS.md 教训 #17 落实：所有进入消息处理流程的消息都入 message_snapshots 表
        这是删除历史消息的前提（删消息必须先知道 msg_id）
        反模式：之前 P1 拦截只 return True 不记 msg_id → 18:36 教白嫖消息删不掉
        """
        import time as _t
        if ts is None:
            ts = int(_t.time())
        try:
            with self.lock:
                self.conn.execute(
                    "INSERT OR IGNORE INTO message_snapshots (chat_id, msg_id, user_id, text, ts) VALUES (?,?,?,?,?)",
                    (chat_id, msg_id, user_id, (text or "")[:200], ts)
                )
                self.conn.commit()
            return True
        except Exception as e:
            # 【v5.31.2 修复】广告治理关键路径，失败必须告警，否则下游 mark_message_deleted 拿不到 msg_id
            logger.warning(f"snapshot_message 失败 chat_id={chat_id} msg_id={msg_id}: {e}")
            return False

    def mark_message_deleted(self, chat_id: int, msg_id: int) -> bool:
        """[TRAE SOLO CN] v5.15.3 新增：标记消息已删除（用于追溯审计）"""
        try:
            with self.lock:
                cursor = self.conn.execute(
                    "UPDATE message_snapshots SET deleted=1 WHERE chat_id=? AND msg_id=?",
                    (chat_id, msg_id)
                )
                self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            # 【v5.31.2 修复】广告治理审计路径，失败必须告警
            logger.warning(f"mark_message_deleted 失败 chat_id={chat_id} msg_id={msg_id}: {e}")
            return False

    def queue_keyword_message_delete(
        self,
        chat_id: int,
        message_id: int,
        user_id: int,
        text: str,
        keyword: str,
        due_at: int,
    ) -> bool:
        """登记关键词命中消息的到期删除状态；同一消息重复投递保持幂等。"""
        with self.lock:
            self.conn.execute(
                """INSERT INTO message_snapshots (
                       chat_id, msg_id, user_id, text, ts,
                       auto_delete_due_at, auto_delete_status,
                       auto_delete_keyword, auto_delete_attempts, auto_delete_error
                   ) VALUES (?,?,?,?,? ,?,'pending',?,0,'')
                   ON CONFLICT(chat_id, msg_id) DO UPDATE SET
                       auto_delete_due_at=excluded.auto_delete_due_at,
                       auto_delete_status='pending',
                       auto_delete_keyword=excluded.auto_delete_keyword,
                       auto_delete_attempts=0,
                       auto_delete_error=''""",
                (
                    int(chat_id),
                    int(message_id),
                    int(user_id),
                    (text or "")[:200],
                    int(time.time()),
                    int(due_at),
                    (keyword or "")[:100],
                ),
            )
            self.conn.commit()
        return True

    def get_due_keyword_message_deletes(
        self,
        now_ts: int,
        limit: int = 100,
        max_attempts: int = 5,
    ) -> list[dict]:
        """读取到期且仍可重试的关键词待删消息。"""
        with self.lock:
            rows = self.conn.execute(
                """SELECT chat_id, msg_id, user_id, auto_delete_keyword,
                          auto_delete_due_at, auto_delete_attempts
                   FROM message_snapshots
                   WHERE auto_delete_status='pending'
                     AND auto_delete_due_at>0
                     AND auto_delete_due_at<=?
                     AND auto_delete_attempts<?
                   ORDER BY auto_delete_due_at ASC
                   LIMIT ?""",
                (int(now_ts), max(1, int(max_attempts)), max(1, min(500, int(limit)))),
            ).fetchall()
        return [
            {
                "chat_id": row[0],
                "message_id": row[1],
                "user_id": row[2],
                "keyword": row[3],
                "due_at": row[4],
                "attempts": row[5],
            }
            for row in rows
        ]

    def resolve_keyword_message_delete(
        self,
        chat_id: int,
        message_id: int,
        *,
        success: bool,
        error: str = "",
        max_attempts: int = 5,
    ) -> str:
        """固化单条删除回执；失败达到上限后转为 failed，不包装成成功。"""
        with self.lock:
            if success:
                cursor = self.conn.execute(
                    """UPDATE message_snapshots
                       SET auto_delete_status='deleted', deleted=1, auto_delete_error=''
                       WHERE chat_id=? AND msg_id=?""",
                    (int(chat_id), int(message_id)),
                )
                self.conn.commit()
                return "deleted" if cursor.rowcount else "missing"

            row = self.conn.execute(
                """SELECT auto_delete_attempts FROM message_snapshots
                   WHERE chat_id=? AND msg_id=?""",
                (int(chat_id), int(message_id)),
            ).fetchone()
            if row is None:
                return "missing"
            attempts = int(row[0] or 0) + 1
            status = "failed" if attempts >= max(1, int(max_attempts)) else "pending"
            self.conn.execute(
                """UPDATE message_snapshots
                   SET auto_delete_status=?, auto_delete_attempts=?, auto_delete_error=?
                   WHERE chat_id=? AND msg_id=?""",
                (status, attempts, (error or "")[:300], int(chat_id), int(message_id)),
            )
            self.conn.commit()
            return status

    def get_keyword_message_delete_state(self, chat_id: int, message_id: int) -> dict | None:
        """读取单条待删/已删状态，供测试与生产业务回执核对。"""
        with self.lock:
            row = self.conn.execute(
                """SELECT auto_delete_due_at, auto_delete_status, auto_delete_keyword,
                          auto_delete_attempts, auto_delete_error, deleted
                   FROM message_snapshots WHERE chat_id=? AND msg_id=?""",
                (int(chat_id), int(message_id)),
            ).fetchone()
        if row is None:
            return None
        return {
            "due_at": row[0],
            "status": row[1],
            "keyword": row[2],
            "attempts": row[3],
            "error": row[4],
            "deleted": row[5],
        }

    def mark_message_ad(self, chat_id: int, msg_id: int) -> bool:
        """固化逐条广告判定；删除是否成功由 deleted 字段独立表达。"""
        try:
            with self.lock:
                cursor = self.conn.execute(
                    "UPDATE message_snapshots SET is_ad=1 WHERE chat_id=? AND msg_id=?",
                    (chat_id, msg_id),
                )
                self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.warning(f"mark_message_ad 失败 chat_id={chat_id} msg_id={msg_id}: {e}")
            return False

    def get_user_messages(self, user_id: int, chat_id: int = None, limit: int = 100) -> list:
        """[TRAE SOLO CN] v5.15.3 新增：查询用户历史消息（用于追溯删除）"""
        try:
            with self.lock:
                if chat_id:
                    rows = self.conn.execute(
                        "SELECT chat_id, msg_id, text, ts, deleted FROM message_snapshots WHERE user_id=? AND chat_id=? ORDER BY ts DESC LIMIT ?",
                        (user_id, chat_id, limit)
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT chat_id, msg_id, text, ts, deleted FROM message_snapshots WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                        (user_id, limit)
                    ).fetchall()
            return [{"chat_id": r[0], "msg_id": r[1], "text": r[2], "ts": r[3], "deleted": r[4]} for r in rows]
        except Exception as e:
            # 【v5.31.2 修复】追溯删除路径，失败必须告警，否则广告消息残留无人感知
            logger.warning(f"get_user_messages 失败 user_id={user_id} chat_id={chat_id}: {e}")
            return []

    def get_user_undeleted_messages(self, user_id: int, chat_id: int = None, limit: int = 2000) -> list:
        """
        [Codex] 查询广告处置要重试清理的用户消息。

        注意：这里故意不按 deleted=0 过滤。历史版本曾在 Telegram 删除失败时也标记
        deleted=1，导致群里实际残留的广告消息后续被跳过；广告处置时必须按快照重试。
        """
        return self.get_user_messages(user_id, chat_id=chat_id, limit=limit)

    def get_user_ad_messages(self, user_id: int, chat_id: int = None, limit: int = 2000) -> list:
        """只返回已逐条确认为广告的快照，供治理链安全重试删除。"""
        try:
            with self.lock:
                if chat_id:
                    rows = self.conn.execute(
                        "SELECT chat_id, msg_id, text, ts, deleted FROM message_snapshots "
                        "WHERE user_id=? AND chat_id=? AND is_ad=1 ORDER BY ts DESC LIMIT ?",
                        (user_id, chat_id, limit),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        "SELECT chat_id, msg_id, text, ts, deleted FROM message_snapshots "
                        "WHERE user_id=? AND is_ad=1 ORDER BY ts DESC LIMIT ?",
                        (user_id, limit),
                    ).fetchall()
            return [
                {"chat_id": r[0], "msg_id": r[1], "text": r[2], "ts": r[3], "deleted": r[4]}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"get_user_ad_messages 失败 user_id={user_id} chat_id={chat_id}: {e}")
            return []

    def is_blacklisted(self, uid: int) -> bool:
        with self.lock:
            c = self.conn.cursor()
            # 先查 blacklist 表
            c.execute("SELECT 1 FROM blacklist WHERE uid=?", (uid,))
            if c.fetchone() is not None:
                return True
            # 再查 global_blacklist 表（广告封禁专用，表可能不存在需保护）
            try:
                c.execute("SELECT 1 FROM global_blacklist WHERE user_id=?", (uid,))
                if c.fetchone() is not None:
                    return True
            except Exception as e:
                logger.debug(f"global_blacklist查询异常: {e}")  # global_blacklist 表不存在时静默跳过
            return False

    # ─────────────────────────────── 反刷 ────────────────────────────────
    def check_spam(self, uid: int, limit: int, window: int = 60) -> bool:
        """返回True代表触发刷屏阈值"""
        now = int(time.time())
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT msg_count, window_start FROM spam_track WHERE uid=?", (uid,))
            row = c.fetchone()
            if not row or now - row[1] > window:
                self.conn.execute("INSERT OR REPLACE INTO spam_track VALUES (?,1,?)", (uid, now))
                self.conn.commit()
                return False
            count = row[0] + 1
            self.conn.execute("UPDATE spam_track SET msg_count=? WHERE uid=?", (count, uid))
            self.conn.commit()
            return count >= limit

    # ─────────────────────────────── 频道成员快照 ────────────────────────
    def record_channel_member_snapshot(self, chat_id: int, member_count: int, snapshot_date: str = None) -> bool:
        """【v4.9.6新增】记录频道成员数快照（每小时调用一次）"""
        if not snapshot_date:
            snapshot_date = datetime.now(_CST).strftime("%Y-%m-%d-%H")
        try:
            with self.lock:
                ts = int(time.time())
                self.conn.execute(
                    "INSERT OR REPLACE INTO channel_member_snapshot (chat_id, member_count, snapshot_date, created_at) VALUES (?,?,?,?)",
                    (chat_id, member_count, snapshot_date, ts)
                )
                self.conn.commit()
            return True
        except Exception as e:
            logger.warning(f"record_channel_member_snapshot失败: chat_id={chat_id} err={e}")
            return False

    def get_channel_member_changes(self, chat_id: int, start_date: str, end_date: str) -> dict:
        """【v4.9.6新增】获取频道在日期范围内的成员变化（新增/离开）

        Args:
            chat_id: 频道ID
            start_date: 开始日期（如 "2026-05-20"）
            end_date: 结束日期（如 "2026-05-21"）

        Returns:
            {"joined": int, "left": int, "start_count": int, "end_count": int}
        """
        with self.lock:
            c = self.conn.cursor()
            # 获取开始日期最早的快照（作为基准）
            c.execute("""SELECT member_count FROM channel_member_snapshot
                         WHERE chat_id=? AND snapshot_date LIKE ? ORDER BY snapshot_date ASC LIMIT 1""",
                     (chat_id, f"{start_date}%"))
            start_row = c.fetchone()
            start_count = start_row[0] if start_row else 0

            # 获取结束日期最晚的快照（作为当前）
            c.execute("""SELECT member_count FROM channel_member_snapshot
                         WHERE chat_id=? AND snapshot_date LIKE ? ORDER BY snapshot_date DESC LIMIT 1""",
                     (chat_id, f"{end_date}%"))
            end_row = c.fetchone()
            end_count = end_row[0] if end_row else 0

            # 如果开始日期没有快照，用结束日期的前一个可用快照
            if start_count == 0 and end_count > 0:
                c.execute("""SELECT member_count FROM channel_member_snapshot
                             WHERE chat_id=? AND snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1""",
                         (chat_id, start_date))
                prev_row = c.fetchone()
                start_count = prev_row[0] if prev_row else 0

        # 计算变化：正数=新增，负数=离开
        diff = end_count - start_count
        if diff >= 0:
            return {"joined": diff, "left": 0, "start_count": start_count, "end_count": end_count}
        else:
            return {"joined": 0, "left": abs(diff), "start_count": start_count, "end_count": end_count}

    # [TRAE SOLO CN] v5.8.1 新增：群成员追踪（渐进式构建完整成员列表）

    def upsert_group_member(self, uid: int, chat_id: int, username: str = "",
                            display_name: str = "", bio: str = "", status: str = "member"):
        now = int(time.time())
        with self.lock:
            self.conn.execute("""
                INSERT INTO group_members (uid, chat_id, username, display_name, bio, status, first_seen, last_checked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid, chat_id) DO UPDATE SET
                    username=excluded.username,
                    display_name=excluded.display_name,
                    bio=excluded.bio,
                    status=excluded.status,
                    last_checked=excluded.last_checked
            """, (uid, chat_id, username, display_name, bio, status, now, now))
            self.conn.commit()

    def remove_group_member(self, uid: int, chat_id: int):
        with self.lock:
            self.conn.execute("DELETE FROM group_members WHERE uid=? AND chat_id=?", (uid, chat_id))
            self.conn.commit()

    def get_group_member_count(self, chat_id: int) -> int:
        with self.lock:
            row = self.conn.execute("SELECT COUNT(*) FROM group_members WHERE chat_id=?", (chat_id,)).fetchone()
            return row[0] if row else 0

    def get_all_group_member_ids(self, chat_id: int) -> list:
        with self.lock:
            rows = self.conn.execute("SELECT uid FROM group_members WHERE chat_id=? AND status != 'left'", (chat_id,)).fetchall()
            return [r[0] for r in rows]

    def get_channel_weekly_member_changes(self, chat_id: int, start_date: str, end_date: str) -> dict:
        """【v4.9.6新增】获取频道在周报日期范围内的成员变化

        Args:
            chat_id: 频道ID
            start_date: 周报开始日期
            end_date: 周报结束日期

        Returns:
            {"joined": int, "left": int, "start_count": int, "end_count": int}
        """
        return self.get_channel_member_changes(chat_id, start_date, end_date)

    def get_channel_monthly_member_changes(self, chat_id: int, month_date: str) -> dict:
        """【v4.9.6新增】获取频道月报的成员变化
        month_date 格式: "2026-05"

        Returns:
            {"joined": int, "left": int, "start_count": int, "end_count": int}
        """
        # 取该月1号的快照和月末快照
        start_date = f"{month_date}-01"
        # 计算月末日期
        parts = month_date.split("-")
        year, month = int(parts[0]), int(parts[1])
        if month == 12:
            end_date = f"{year + 1}-01-01"
        else:
            end_date = f"{year}-{month + 1:02d}-01"

        with self.lock:
            c = self.conn.cursor()
            c.execute("""SELECT member_count FROM channel_member_snapshot
                         WHERE chat_id=? AND snapshot_date LIKE ? ORDER BY snapshot_date ASC LIMIT 1""",
                     (chat_id, f"{start_date}%"))
            start_row = c.fetchone()
            start_count = start_row[0] if start_row else 0

            c.execute("""SELECT member_count FROM channel_member_snapshot
                         WHERE chat_id=? AND snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1""",
                     (chat_id, end_date))
            end_row = c.fetchone()
            end_count = end_row[0] if end_row else 0

        diff = end_count - start_count
        if diff >= 0:
            return {"joined": diff, "left": 0, "start_count": start_count, "end_count": end_count}
        else:
            return {"joined": 0, "left": abs(diff), "start_count": start_count, "end_count": end_count}
