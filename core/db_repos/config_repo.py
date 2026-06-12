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
            logger.debug(f"📌 系统状态更新: {key}={value}")

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
        返回True表示抢占成功，False表示已被抢占（同次或历史执行）"""
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
                return False

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
                logger.warning(f"📋 [DB] is_task_executed_today({task_key}) 失败: {e}")
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
