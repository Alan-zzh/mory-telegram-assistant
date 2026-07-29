# -*- coding: utf-8 -*-
"""
core/write_queue.py  ·  写队列兼容层（v5.32.0 降级）

历史：v5.23.0 引入单线程写入队列 + DBConnectionProxy 4 层抽象，
      用于消除 SQLite "database is locked"。

现状：v5.32.0 重构判定该抽象超出场景需要（单 VPS 群组助手并发量低），
      WAL + busy_timeout=30s + synchronous=NORMAL 已足够。
      WriteQueueConnectionProxy 已移除，本模块保留为空壳兼容层：
      - start()/stop() 为 no-op
      - get_stats() 返回零值（监控代码 alert_rules/db_migration_monitor/metrics 依赖）
      - enqueue/enqueue_and_wait 抛 RuntimeError 提示已废弃
"""


class WriteQueueFullError(Exception):
    """保留异常类兼容（不再抛出）"""
    pass


class _WriteQueueCompat:
    """写队列空壳兼容层（监控代码依赖 get_stats()）"""

    def __init__(self, max_size: int = 2000):
        self._max_size = max_size
        self._running = False

    def start(self):
        """no-op（兼容 main.py 调用）"""
        self._running = True

    def stop(self, timeout: float = 5.0):
        """no-op（兼容 main.py 停机调用）"""
        self._running = False

    def get_stats(self) -> dict:
        """返回零值统计（监控代码依赖）"""
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "pending": 0,
            "last_error": "",
            "last_error_ts": 0,
        }

    def enqueue(self, *args, **kwargs):
        raise RuntimeError(
            "WriteQueue 已于 v5.32.0 降级，请直接使用 db.conn.execute()。"
            "如需异步写，请用 threading.Thread 自行管理。"
        )

    def enqueue_and_wait(self, *args, **kwargs):
        raise RuntimeError(
            "WriteQueue 已于 v5.32.0 降级，请直接使用 db.conn.execute()。"
        )

    def enqueue_batch(self, *args, **kwargs):
        raise RuntimeError(
            "WriteQueue 已于 v5.32.0 降级，请直接使用 db.conn.executemany()。"
        )


# 全局单例（兼容旧代码 import）
write_queue = _WriteQueueCompat(max_size=2000)
