# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/db_connection_proxy.py  ·  SQLite 连接代理（v5.24.0 阶段1-A）       ║
║                                                                            ║
║  功能：                                                                    ║
║    零侵入拦截 conn.execute / conn.cursor，写操作自动走 WriteQueue，        ║
║    读操作直接执行。所有 Repo 代码无需修改，自动全量化。                    ║
║                                                                            ║
║  原理：                                                                    ║
║    - 包装 DB 主连接，代理 execute/executemany/cursor                        ║
║    - 写操作（INSERT/UPDATE/DELETE/ALTER/CREATE/DROP/REPLACE）走队列        ║
║    - 读操作（SELECT/PRAGMA/EXPLAIN/DESC/SHOW）直接执行                     ║
║    - WriteQueue 未启动时回退同步执行（启动阶段安全）                       ║
║    - 伪 cursor 提供 rowcount/lastrowid，满足写操作返回值需求              ║
║                                                                            ║
║  事务说明：                                                                ║
║    队列化后每条写操作独立 commit，多语句事务的原子性降级为顺序执行。       ║
║    现有代码的多语句事务多为 INSERT OR IGNORE + UPDATE，拆开安全。          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import threading
from typing import Any, Optional

from core.logging_util import get_logger

logger = get_logger("db_proxy")

# 写操作 SQL 前缀（不区分大小写）
_WRITE_PREFIXES = (
    "INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP",
    "REPLACE", "MERGE", "TRUNCATE",
)
# 读操作 SQL 前缀（直接执行，不走队列）
_READ_PREFIXES = ("SELECT", "PRAGMA", "EXPLAIN", "DESC", "DESCRIBE", "SHOW", "WITH")

# [v5.25.0 阶段1-B] 核心表清单：这些表的写入是核心业务状态，队列满时抛异常而非丢弃
# 非核心表（日志/埋点/分析）队列满时静默丢弃
_CRITICAL_TABLES = (
    "user_profiles",      # 用户画像（核心）
    "funnel_state",       # 转化漏斗状态（核心）
    "conversion_events",  # 转化事件（核心）
    "reply_tracking",     # 回复追踪（中等核心，但高频，归非核心避免背压误杀）
)
# 实际核心表（队列满抛异常）
_CRITICAL_ONLY = ("user_profiles", "funnel_state", "conversion_events")


def _is_write_sql(sql: str) -> bool:
    """判断 SQL 是否为写操作"""
    if not sql:
        return False
    s = sql.strip().lstrip("(").strip().upper()
    # WITH ... SELECT 是读，WITH ... UPDATE/INSERT 是写（CTE DML）
    if s.startswith("WITH"):
        # 简单判断：包含 INSERT/UPDATE/DELETE/REPLACE 视为写
        return any(kw in s for kw in ("INSERT", "UPDATE", "DELETE", "REPLACE"))
    return s.startswith(_WRITE_PREFIXES)


def _is_critical_write(sql: str) -> bool:
    """[v5.25.0 阶段1-B] 判断写操作是否为核心业务状态写入

    核心表（user_profiles/funnel_state/conversion_events）的写入队列满时抛异常，
    由上层返回降级文案；非核心表队列满时静默丢弃。
    """
    if not sql:
        return False
    s = sql.upper()
    return any(table.upper() in s for table in _CRITICAL_ONLY)


class _FakeCursor:
    """写操作的伪 cursor，提供 rowcount/lastrowid，不支持 fetch"""

    __slots__ = ("rowcount", "lastrowid", "_error")

    def __init__(self, result):
        if result and result.error is None:
            self.rowcount = result.rowcount
            self.lastrowid = result.lastrowid
        else:
            self.rowcount = -1
            self.lastrowid = -1
        self._error = result.error if result else None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def fetchmany(self, size=None):
        return []

    def close(self):
        pass


class WriteQueueCursorProxy:
    """cursor 代理：写操作走队列，读操作直接执行

    [v5.25.0 修复] execute 在真实 cursor 上执行读操作，确保 fetchone/fetchall
    从同一 cursor 取数据；写操作走连接代理的队列。
    """

    def __init__(self, real_cursor, conn_proxy):
        self._real = real_cursor
        self._conn = conn_proxy

    def execute(self, sql, params=()):
        # 读操作：在真实 cursor 上执行，确保 fetchone 从同一 cursor 取
        if not _is_write_sql(sql):
            return self._real.execute(sql, params)
        # 写操作：走连接代理的队列
        return self._conn.execute(sql, params)

    def executemany(self, sql, params_seq):
        if not _is_write_sql(sql):
            return self._real.executemany(sql, params_seq)
        return self._conn.executemany(sql, params_seq)

    def fetchone(self):
        return self._real.fetchone()

    def fetchall(self):
        return self._real.fetchall()

    def fetchmany(self, size=None):
        return self._real.fetchmany(size) if size else self._real.fetchmany()

    @property
    def rowcount(self):
        return self._real.rowcount

    @property
    def lastrowid(self):
        return self._real.lastrowid

    @property
    def description(self):
        return self._real.description

    def close(self):
        self._real.close()

    def __iter__(self):
        return iter(self._real)


class WriteQueueConnectionProxy:
    """
    SQLite 连接代理：拦截写操作走 WriteQueue，读操作直接执行。
    零侵入：替换 DB.conn 后，所有 Repo 自动全量化。
    """

    def __init__(self, real_conn):
        self._real = real_conn

    def execute(self, sql, params=()):
        """拦截 execute：写走队列，读直接执行"""
        if _is_write_sql(sql):
            return self._write_via_queue(sql, params)
        return self._real.execute(sql, params)

    def executemany(self, sql, params_seq):
        """拦截 executemany：批量写走队列"""
        if _is_write_sql(sql):
            from core.write_queue import write_queue
            if not write_queue._running:
                return self._real.executemany(sql, params_seq)
            # 批量写逐条入队（保持串行）
            for params in params_seq:
                write_queue.enqueue(self._real, sql, params)
            return self._real.cursor()  # 返回空 cursor
        return self._real.executemany(sql, params_seq)

    def cursor(self):
        """返回 cursor 代理"""
        return WriteQueueCursorProxy(self._real.cursor(), self)

    def commit(self):
        """透传 commit（Worker 已 commit，此处 no-op 兼容）"""
        # Worker 每次 execute 后已 commit，这里不需要再 commit
        # 但为了兼容显式事务，仍然透传
        try:
            self._real.commit()
        except Exception as e:
            logger.debug(f"proxy commit 异常: {e}")

    def rollback(self):
        """透传 rollback"""
        try:
            self._real.rollback()
        except Exception as e:
            logger.debug(f"proxy rollback 异常: {e}")

    def close(self):
        self._real.close()

    def __getattr__(self, name):
        """其他属性/方法透传到真实连接"""
        return getattr(self._real, name)

    def _write_via_queue(self, sql, params):
        """写操作通过 WriteQueue 执行

        [v5.25.0 阶段1-B] 背压机制：
        - 核心表写入：队列满抛 WriteQueueFullError，由上层返回降级文案
        - 非核心表写入：队列满返回空 cursor（静默丢弃）
        - 禁止回退同步写（避免锁竞争死灰复燃）
        """
        from core.write_queue import write_queue, WriteQueueFullError
        if not write_queue._running:
            # 队列未启动（启动阶段），回退同步执行
            return self._real.execute(sql, params)

        is_critical = _is_critical_write(sql)
        try:
            result = write_queue.enqueue_and_wait(
                self._real, sql, params, timeout=10.0, is_critical=is_critical
            )
        except WriteQueueFullError:
            # 核心写入队列满：抛异常给上层处理（返回降级文案）
            raise

        if result.error is not None:
            # 非核心写入被丢弃（result.error = TimeoutError）或执行失败
            logger.debug(f"代理写降级: {result.error} | SQL: {sql[:80]}")
            return _FakeCursor(result)
        return _FakeCursor(result)
