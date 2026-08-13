# -*- coding: utf-8 -*-
"""配置功能域数据操作"""
import time
from datetime import datetime, timedelta

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.config")


class ConfigRepo:
    """配置相关数据库操作"""

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

    # ─────────────────────────────── 系统动态状态 ─────────────────────────
    def get_system_state(self, key: str, default=None):
        """
        获取系统动态状态（从数据库读取，替代 config.json 中的动态字段）。

        Args:
            key: 状态键名
            default: 默认值（不存在时返回）

        Returns:
            状态值（字符串），或 default

        使用场景：
            - CURRENT_MODEL_INDEX: 当前使用的模型索引
            - IMAGE_POOL: 图片池缓存
            - VOICE_POOL: 语音池缓存
            - _LAST_LEAK_WEEK: 上次背刺泄密的周号
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT value FROM system_states WHERE key=?", (key,))
            row = c.fetchone()
            if row:
                return row[0]
            return default

    def set_system_state(self, key: str, value):
        """
        设置系统动态状态（写入数据库，不修改 config.json）。

        Args:
            key: 状态键名
            value: 状态值（会自动转为字符串存储）
        """
        with self.lock:
            ts = int(time.time())
            self.conn.execute(
                "INSERT OR REPLACE INTO system_states (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), ts)
            )
            self.conn.commit()
            # 日志脱敏：只记录键+类型/长度，禁止明文值进入 DEBUG（防止长 list/dict/意外 token 落盘）
            _v = value
            if _v is None:
                _safe = "None"
            elif isinstance(_v, str):
                _safe = f"str(len={len(_v)})"
            elif isinstance(_v, (list, dict, tuple, set)):
                _safe = f"{type(_v).__name__}(len={len(_v)})"
            else:
                _safe = type(_v).__name__
            logger.debug(f"📌 系统状态更新: {key}=<{_safe}>")

    def has_onboarding_delivery(self, uid: int, chat_id: int, surface: str) -> bool:
        """查询某用户在某聊天表面的欢迎卡是否已真实送达。"""
        with self.lock:
            row = self.conn.execute(
                """SELECT 1 FROM onboarding_deliveries
                   WHERE uid=? AND chat_id=? AND surface=? AND status='delivered'
                   LIMIT 1""",
                (int(uid), int(chat_id), str(surface)),
            ).fetchone()
            return row is not None

    def claim_onboarding_delivery(self, uid: int, chat_id: int, surface: str) -> bool:
        """原子抢占欢迎卡发送权；两分钟无完成的 pending 允许恢复重试。"""
        now = int(time.time())
        stale_before = now - 120
        with self.lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO onboarding_deliveries
                   (uid, chat_id, surface, status, claimed_at, delivered_at)
                   VALUES (?, ?, ?, 'pending', ?, NULL)""",
                (int(uid), int(chat_id), str(surface), now),
            )
            if cur.rowcount > 0:
                self.conn.commit()
                return True
            cur = self.conn.execute(
                """UPDATE onboarding_deliveries
                   SET claimed_at=?
                   WHERE uid=? AND chat_id=? AND surface=?
                     AND status='pending' AND claimed_at<?""",
                (now, int(uid), int(chat_id), str(surface), stale_before),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def complete_onboarding_delivery(self, uid: int, chat_id: int, surface: str) -> bool:
        """仅在 Telegram 返回消息回执后把首次欢迎标为 delivered。"""
        now = int(time.time())
        with self.lock:
            cur = self.conn.execute(
                """UPDATE onboarding_deliveries
                   SET status='delivered', delivered_at=?
                   WHERE uid=? AND chat_id=? AND surface=? AND status='pending'""",
                (now, int(uid), int(chat_id), str(surface)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def release_onboarding_delivery(self, uid: int, chat_id: int, surface: str) -> bool:
        """发送未成功时释放 pending，使下一次 @ 可以重新尝试。"""
        with self.lock:
            cur = self.conn.execute(
                """DELETE FROM onboarding_deliveries
                   WHERE uid=? AND chat_id=? AND surface=? AND status='pending'""",
                (int(uid), int(chat_id), str(surface)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.4.9新增】关键词自动回复系统
    # ═══════════════════════════════════════════════════════════════════════════

    def add_keyword_trigger(self, keyword: str, reply_text: str, reply_type: str = "static", action_type: str = ""):
        """添加关键词触发规则"""
        with self.lock:
            ts = int(time.time())
            c = self.conn.cursor()
            c.execute("""
                INSERT INTO keyword_triggers (keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
            """, (keyword, reply_text, reply_type, action_type, ts, ts))
            self.conn.commit()
            logger.info(f"🔑 添加关键词触发: {keyword}")

    def get_all_keyword_triggers(self) -> list:
        """获取所有启用的关键词触发规则"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("""
                SELECT id, keyword, reply_text, reply_type, action_type, enabled, created_at, updated_at
                FROM keyword_triggers
                WHERE enabled = 1
                ORDER BY id DESC
            """)
            rows = c.fetchall()
            return [
                {
                    "id": r[0],
                    "keyword": r[1],
                    "reply_text": r[2],
                    "reply_type": r[3],
                    "action_type": r[4],
                    "enabled": r[5],
                    "created_at": r[6],
                    "updated_at": r[7]
                }
                for r in rows
            ]

    def delete_keyword_trigger(self, trigger_id: int):
        """删除关键词触发规则"""
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM keyword_triggers WHERE id = ?", (trigger_id,))
            self.conn.commit()
            logger.info(f"🔑 删除关键词触发: id={trigger_id}")

    def update_keyword_trigger(self, trigger_id: int, **kwargs):
        """更新关键词触发规则"""
        with self.lock:
            ts = int(time.time())
            c = self.conn.cursor()
            allowed_fields = ["keyword", "reply_text", "reply_type", "action_type", "enabled"]
            set_clause = []
            params = []
            for field, value in kwargs.items():
                if field in allowed_fields:
                    set_clause.append(f"{field} = ?")
                    params.append(value)
            if not set_clause:
                return
            set_clause.append("updated_at = ?")
            params.extend([ts, trigger_id])
            sql = f"UPDATE keyword_triggers SET {', '.join(set_clause)} WHERE id = ?"
            c.execute(sql, params)
            self.conn.commit()
            logger.info(f"🔑 更新关键词触发: id={trigger_id}")

    def match_keyword_trigger(self, text: str) -> list:
        """
        匹配关键词触发规则（返回匹配到的所有规则，按优先级排序）

        Args:
            text: 用户输入的文本

        Returns:
            [{"id": int, "keyword": str, ...}]
        """
        text_lower = text.lower()
        # 直接调用get_all_keyword_triggers（它自己获取锁，避免死锁）
        all_triggers = self.get_all_keyword_triggers()
        matched = []
        for trigger in all_triggers:
            if trigger["keyword"].lower() in text_lower:
                matched.append(trigger)
        return matched

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v4.3.9】任务执行日志（持久化去重）
    # ═══════════════════════════════════════════════════════════════════════════

    def claim_task(self, task_key: str) -> bool:
        """【v4.5.32→v4.7.0】数据库级原子抢占：跨进程防重核心防线
        纯INSERT OR IGNORE + UNIQUE索引，无SELECT（SELECT会引入竞态窗口）
        SQLite的UNIQUE约束保证跨进程原子性：后到者插入被拒绝
        返回True表示抢占成功，False仅表示已被抢占（同次或历史执行）。
        数据库错误必须向上抛出，禁止伪装成正常去重。"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        ts = time.time()
        with self.lock:
            try:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO task_log (task_key, exec_date, exec_ts) VALUES (?, ?, ?)",
                    (task_key, today, ts)
                )
                self.conn.commit()
                result = cur.rowcount > 0
                logger.info(f"📋 [DB] claim_task({task_key}, {today}) rowcount={cur.rowcount} result={result}")
                return result
            except Exception as e:
                logger.warning(f"📋 [DB] claim_task({task_key}) 失败: {e}")
                try:
                    from modules.auto_tasks import report_fault
                    report_fault("数据库任务抢占失败", f"claim_task({task_key})异常: {str(e)[:100]}", "⚠️")
                except Exception as fault_err:
                    self._db._log_db_error("report_fault 调用", fault_err, "error", f"task_key={task_key}")
                raise

    def is_task_executed_today(self, task_key: str) -> bool:
        """查询任务今日是否已执行"""
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            try:
                row = self.conn.execute(
                    "SELECT 1 FROM task_log WHERE task_key=? AND exec_date=? LIMIT 1",
                    (task_key, today)
                ).fetchone()
                result = row is not None
                logger.info(f"📋 [DB] is_task_executed_today({task_key}, {today}) = {result}")
                return result
            except Exception as e:
                logger.error(f"📋 [DB] is_task_executed_today({task_key}) 失败: {e}")
                raise

    def release_task(self, task_key: str) -> bool:
        """【v5.31.0 修复 Bug A】释放数据库任务锁，允许重试

        之前 scheduled_broadcast.py 6 处调用 db.release_task(task_key) 全部失效，
        因为 DB.__getattr__ 抛 AttributeError 被静默吞掉，导致发送失败时
        task_log 残留，后续重试被 claim_task 拦截。

        task_log 是锁表而不是执行历史；释放时按 task_key 清掉残留锁，避免
        任务跨午夜或旧锁遗留时只删“今天”而永远无法重试。

        Returns:
            True 表示删除了至少 1 行，False 表示无删除或异常
        """
        with self.lock:
            try:
                cur = self.conn.execute(
                    "DELETE FROM task_log WHERE task_key=?",
                    (task_key,)
                )
                self.conn.commit()
                deleted = cur.rowcount > 0
                logger.info(f"📋 [DB] release_task({task_key}) deleted={cur.rowcount}")
                return deleted
            except Exception as e:
                logger.warning(f"📋 [DB] release_task({task_key}) 失败: {e}")
                return False

    def cleanup_old_task_log(self, days: int = 7):
        """清理超过N天的任务执行记录"""
        cutoff = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.lock:
            try:
                cur = self.conn.execute("DELETE FROM task_log WHERE exec_date < ?", (cutoff,))
                self.conn.commit()
                if cur.rowcount > 0:
                    logger.info(f"🧹 清理{cur.rowcount}条过期task_log记录(>{days}天)")
            except Exception as e:
                logger.warning(f"cleanup_old_task_log失败: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 【v5.31.2 新增】健康审计支持方法（_job_proactive_audit / _compute_health_score 调用）
    # ═══════════════════════════════════════════════════════════════════════════

    def check_integrity(self) -> str:
        """执行 PRAGMA integrity_check，返回完整性检查结果字符串

        PRAGMA 为读操作，直接在原生 SQLite 连接上执行（v5.32.0 起无 WriteQueueConnectionProxy）。

        Returns:
            "ok" 表示完整性正常；否则返回错误描述字符串；异常时返回 "error: ..."
        """
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute("PRAGMA integrity_check")
                row = c.fetchone()
                result = row[0] if row else "unknown"
                logger.debug(f"📋 [DB] check_integrity() = {result}")
                return result
            except Exception as e:
                logger.warning(f"📋 [DB] check_integrity 失败: {e}")
                return f"error: {e}"

    def get_recent_task_logs(self, hours: int = 24) -> list:
        """获取最近 N 小时的任务执行记录

        task_log 表记录已抢占的任务：失败的会被 release_task 删除，
        因此留存的记录代表已成功执行的任务（status 标记为 "success"）。

        Args:
            hours: 查询时间窗口（小时），默认 24

        Returns:
            [{"task_key": str, "exec_date": str, "exec_ts": float, "status": "success"}]
            异常时返回空列表
        """
        cutoff = time.time() - hours * 3600
        with self.lock:
            try:
                c = self.conn.cursor()
                c.execute(
                    "SELECT task_key, exec_date, exec_ts FROM task_log WHERE exec_ts >= ? ORDER BY exec_ts DESC",
                    (cutoff,)
                )
                rows = c.fetchall()
                return [
                    {
                        "task_key": r[0],
                        "exec_date": r[1],
                        "exec_ts": r[2],
                        "status": "success",
                    }
                    for r in rows
                ]
            except Exception as e:
                logger.warning(f"📋 [DB] get_recent_task_logs(hours={hours}) 失败: {e}")
                return []
