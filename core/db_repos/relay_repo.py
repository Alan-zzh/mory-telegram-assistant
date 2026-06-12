# -*- coding: utf-8 -*-
"""中继会话数据操作"""
import time
from core.logging_util import get_logger

logger = get_logger("db.relay")


class RelayRepo:
    """中继会话相关数据库操作"""

    def __init__(self, db):
        """db: DB实例，通过 db.conn 和 db.lock 访问连接和锁"""
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    def save_session(self, admin_chat_id: int, admin_msg_id: int,
                     user_id: int, user_chat_id: int, source_type: str = 'private') -> int:
        """保存一条中继会话记录

        Args:
            admin_chat_id: 管理员chat ID
            admin_msg_id: 转发到管理员端的消息ID
            user_id: 原始用户ID
            user_chat_id: 原始chat ID（私聊=用户ID，群聊=群ID）
            source_type: 来源类型 'private' 或 'group'

        Returns:
            新插入行的 id
        """
        with self.lock:
            try:
                ts = int(time.time())
                cur = self.conn.cursor()
                cur.execute(
                    """INSERT INTO relay_sessions
                       (admin_chat_id, admin_msg_id, user_id, user_chat_id, source_type, ts)
                       VALUES (?,?,?,?,?,?)""",
                    (int(admin_chat_id), int(admin_msg_id), int(user_id),
                     int(user_chat_id), source_type, ts),
                )
                self.conn.commit()
                logger.debug(f"📌 中继会话记录：admin_msg={admin_msg_id} user={user_id} type={source_type}")
                return cur.lastrowid
            except Exception as e:
                logger.error(f"📌 中继会话记录失败：{e}")
                return 0

    def find_by_admin_msg(self, admin_chat_id: int, admin_msg_id: int) -> dict:
        """通过管理员端消息ID查找原始用户信息

        Args:
            admin_chat_id: 管理员chat ID
            admin_msg_id: 管理员端的消息ID

        Returns:
            dict: {user_id, user_chat_id, source_type} 或 None
        """
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                """SELECT user_id, user_chat_id, source_type
                   FROM relay_sessions
                   WHERE admin_chat_id=? AND admin_msg_id=?
                   ORDER BY ts DESC LIMIT 1""",
                (int(admin_chat_id), int(admin_msg_id)),
            )
            row = c.fetchone()
            if row:
                return {
                    "user_id": row[0],
                    "user_chat_id": row[1],
                    "source_type": row[2],
                }
            return None

    def clean_expired(self, max_age: int = 86400) -> int:
        """清理过期的中继会话记录

        Args:
            max_age: 最大存活秒数（默认24小时）

        Returns:
            删除的行数
        """
        cutoff = int(time.time()) - max_age
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM relay_sessions WHERE ts<?", (cutoff,))
            deleted = c.rowcount
            self.conn.commit()
            if deleted > 0:
                logger.info(f"📌 清理过期中继会话：{deleted}条")
            return deleted
