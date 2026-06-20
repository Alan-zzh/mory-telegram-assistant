# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/write_queue.py  ·  SQLite 单线程写入队列（v5.23.0 P0-1）             ║
║                                                                            ║
║  功能：                                                                    ║
║    所有写操作（INSERT/UPDATE/DELETE）投递到内存队列，                       ║
║    由后台单线程 Worker 串行执行，彻底消除 database is locked。              ║
║                                                                            ║
║  原理：                                                                    ║
║    - SQLite 写锁是全库级别，多线程并发写必然竞争                            ║
║    - WAL 模式缓解读写并发，但写写并发仍会触发锁                             ║
║    - 单线程 Worker 保证任何时刻只有一个连接在写入                           ║
║                                                                            ║
║  使用：                                                                    ║
║    from core.write_queue import write_queue                                ║
║    write_queue.enqueue(conn, sql, params)                                  ║
║                                                                            ║
║  渐进式迁移：                                                              ║
║    高频写表（message_snapshots/reply_tracking/spam_track）优先迁移         ║
║    低频写表保持同步写（已有 busy_timeout 保护）                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import queue
import threading
import time
from typing import Any, Optional, Tuple

from core.logging_util import get_logger

logger = get_logger("write_queue")


class WriteQueueFullError(Exception):
    """[v5.25.0 阶段1-B] WriteQueue 队列满异常（核心写入专用）

    核心状态写入（加购/支付/funnel 转换）队列满时抛此异常，
    由上层捕获后返回友好降级文案，禁止回退同步写避免锁竞争。
    """
    pass


class _WriteTask:
    """单个写任务"""

    __slots__ = ("conn", "sql", "params", "callback", "future", "ts")

    def __init__(self, conn, sql: str, params: tuple, callback=None, future=None):
        self.conn = conn
        self.sql = sql
        self.params = params
        self.callback = callback
        self.future = future
        self.ts = time.time()


class _WriteResult:
    """写任务结果（用于同步等待）"""

    __slots__ = ("rowcount", "lastrowid", "error")

    def __init__(self):
        self.rowcount = 0
        self.lastrowid = 0
        self.error: Optional[Exception] = None


class WriteQueue:
    """
    SQLite 单线程写入队列管理器。

    设计要点：
    1. 全局单例 write_queue，所有模块共享
    2. 后台 Worker 线程串行执行写操作
    3. 支持同步等待（enqueue_and_wait）和异步投递（enqueue）
    4. 队列满时阻塞投递方，防止内存爆炸
    5. Worker 异常不会退出（捕获后继续下一个任务）
    """

    def __init__(self, max_size: int = 2000):
        self._queue: queue.Queue = queue.Queue(maxsize=max_size)
        self._worker: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        # 统计指标
        self._stats = {
            "total": 0,        # 总写入数
            "success": 0,      # 成功数
            "failed": 0,       # 失败数
            "pending": 0,      # 队列待处理数
            "last_error": "",  # 最近错误
            "last_error_ts": 0,
        }
        self._stats_lock = threading.Lock()

    def start(self):
        """启动 Worker 线程（在 main.py 启动时调用一次）"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker = threading.Thread(
                target=self._run_loop,
                name="DBWriteWorker",
                daemon=True,
            )
            self._worker.start()
            logger.info("✅ WriteQueue Worker 已启动（单线程串行写入）")

    def stop(self, timeout: float = 5.0):
        """停止 Worker 线程（在程序退出时调用）"""
        with self._lock:
            if not self._running:
                return
            self._running = False
            # 投递哨兵任务唤醒 Worker
            self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=timeout)
            logger.info("✅ WriteQueue Worker 已停止")

    def enqueue(self, conn, sql: str, params: tuple = (), callback=None, is_critical: bool = False) -> bool:
        """
        异步投递写操作（不等结果）。

        [v5.25.0 阶段1-B] 背压机制：
        - 队列满时禁止回退同步写（避免锁竞争死灰复燃）
        - 非关键写入（is_critical=False）：静默丢弃 + 低频警告日志
        - 核心写入（is_critical=True）：抛 WriteQueueFullError，由上层降级处理

        Args:
            conn: SQLite 连接（Worker 用此连接执行；若为代理自动解包取真实连接）
            sql: SQL 语句
            params: 参数元组
            callback: 可选回调函数，签名为 callback(result: _WriteResult)
            is_critical: 是否核心写入（True=队列满抛异常，False=队列满丢弃）

        Returns:
            True 投递成功，False 队列满（仅非核心写入）
        """
        # [v5.24.0] 代理解包：若传入 WriteQueueConnectionProxy，取真实连接
        real_conn = getattr(conn, "_real", conn)

        if not self._running:
            logger.warning("WriteQueue 未启动，回退同步写")
            try:
                cur = real_conn.execute(sql, params)
                real_conn.commit()
                if callback:
                    r = _WriteResult()
                    r.rowcount = cur.rowcount
                    r.lastrowid = cur.lastrowid
                    callback(r)
                return True
            except Exception as e:
                logger.error(f"同步写失败: {e} | SQL: {sql[:80]}")
                return False

        try:
            task = _WriteTask(real_conn, sql, params, callback)
            self._queue.put_nowait(task)
            with self._stats_lock:
                self._stats["pending"] = self._queue.qsize()
            return True
        except queue.Full:
            # [v5.25.0 阶段1-B] 背压分类降级
            with self._stats_lock:
                self._stats["failed"] += 1
                self._stats["last_error"] = "queue full"
                self._stats["last_error_ts"] = time.time()

            if is_critical:
                # 核心写入：抛异常，由上层返回降级文案
                logger.error(f"WriteQueue 满，核心写入被拒: {sql[:80]}")
                raise WriteQueueFullError(f"队列满，核心写入失败: {sql[:60]}")
            else:
                # 非关键写入：静默丢弃 + 低频警告（每 30s 最多一条）
                now = time.time()
                if now - self._stats.get("last_drop_warn_ts", 0) > 30:
                    logger.warning(f"WriteQueue 满（{self._queue.maxsize}），丢弃非关键写入: {sql[:80]}")
                    with self._stats_lock:
                        self._stats["last_drop_warn_ts"] = now
                return False

    def enqueue_and_wait(self, conn, sql: str, params: tuple = (), timeout: float = 10.0, is_critical: bool = True) -> _WriteResult:
        """
        同步投递写操作并等待结果。

        适用于需要立即拿到 lastrowid/rowcount 的场景。
        注意：不要在 Worker 线程内调用此方法（会死锁）。

        [v5.25.0 阶段1-B] 背压机制：
        - 队列满时禁止回退同步写（避免锁竞争）
        - 核心写入（默认）：队列满抛 WriteQueueFullError
        - 非核心写入：队列满返回 error 结果（静默降级）

        Args:
            conn: SQLite 连接
            sql: SQL 语句
            params: 参数元组
            timeout: 等待超时秒数
            is_critical: 是否核心写入（默认 True，因为走 enqueue_and_wait 的多为需要结果的核心写）

        Returns:
            _WriteResult 包含 rowcount/lastrowid/error
        """
        result = _WriteResult()
        future = threading.Event()
        future.result = result

        if not self._running:
            # 回退同步写（仅启动阶段，非背压场景）
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                result.rowcount = cur.rowcount
                result.lastrowid = cur.lastrowid
            except Exception as e:
                result.error = e
                logger.error(f"同步写失败: {e} | SQL: {sql[:80]}")
            return result

        task = _WriteTask(conn, sql, params, None, future)
        try:
            self._queue.put(task, timeout=timeout)
        except queue.Full:
            # [v5.25.0 阶段1-B] 背压：禁止回退同步写
            with self._stats_lock:
                self._stats["failed"] += 1
                self._stats["last_error"] = "queue full"
                self._stats["last_error_ts"] = time.time()

            if is_critical:
                logger.error(f"WriteQueue 投递超时，核心写入被拒: {sql[:80]}")
                raise WriteQueueFullError(f"队列满，核心写入失败: {sql[:60]}")
            else:
                result.error = TimeoutError(f"WriteQueue 投递超时（{timeout}s）")
                logger.warning(f"WriteQueue 投递超时，非关键写入丢弃: {sql[:80]}")
                return result

        # 等待 Worker 执行完成
        if not future.wait(timeout=timeout):
            result.error = TimeoutError(f"WriteQueue 执行超时（{timeout}s）")
            logger.error(f"WriteQueue 执行超时: {sql[:80]}")

        return result

    def get_stats(self) -> dict:
        """获取队列统计指标"""
        with self._stats_lock:
            stats = dict(self._stats)
            stats["pending"] = self._queue.qsize()
            return stats

    def _run_loop(self):
        """Worker 主循环"""
        logger.info("🔄 DBWriteWorker 开始消费队列")
        while self._running:
            try:
                task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if task is None:
                # 哨兵任务，退出
                logger.info("🔄 DBWriteWorker 收到停止信号")
                break

            try:
                self._execute_task(task)
                with self._stats_lock:
                    self._stats["success"] += 1
            except Exception as e:
                logger.error(f"WriteQueue 任务执行失败: {e} | SQL: {task.sql[:80]}")
                with self._stats_lock:
                    self._stats["failed"] += 1
                    self._stats["last_error"] = str(e)[:200]
                    self._stats["last_error_ts"] = time.time()
                if task.future:
                    task.future.result.error = e
                    task.future.set()
            finally:
                with self._stats_lock:
                    self._stats["total"] += 1
                    self._stats["pending"] = self._queue.qsize()
                self._queue.task_done()

        logger.info("🔄 DBWriteWorker 已退出")

    def _execute_task(self, task: _WriteTask):
        """执行单个写任务"""
        cur = task.conn.execute(task.sql, task.params)
        task.conn.commit()

        result = None
        if task.callback or task.future:
            result = _WriteResult()
            result.rowcount = cur.rowcount
            result.lastrowid = cur.lastrowid

        if task.callback:
            try:
                task.callback(result)
            except Exception as e:
                logger.debug(f"WriteQueue callback 异常: {e}")

        if task.future:
            task.future.result = result
            task.future.set()


# 全局单例
write_queue = WriteQueue(max_size=2000)
