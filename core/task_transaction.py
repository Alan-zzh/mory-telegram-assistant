"""
core/task_transaction.py · 任务事务管理器

将数据库抢占 + ResourceManager资源锁合并为原子事务，
用 with 语句替代手动 try/finally 的 _try_claim_and_lock / _release_task / _confirm_task_done 三段式。

用法：
    # 启动时绑定 ResourceManager
    TaskTransactionManager.bind(rm)

    # 任务中使用
    with TaskTransactionManager("mystic_morning", db, resources=['bot']) as tx:
        if not tx.claimed:
            return
        # ... 执行任务逻辑 ...
    # 退出 with 时自动：成功→confirm，异常→release，锁全部释放
"""

import time
import threading
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.resource_manager import ResourceManager

logger = get_logger("task_transaction")

_CST = timezone(timedelta(hours=8))

_last_task_run = {}
_task_lock = threading.Lock()

_rm_instance = None


class TaskTransactionManager:
    """
    任务事务管理器 - 上下文管理器，封装「抢占→加锁→执行→确认/释放」全流程

    流程：
        __enter__:
            1. 内存锁检查（_last_task_run）
            2. 数据库原子抢占（db.claim_task）
            3. ResourceManager 资源锁（按字母序获取，防死锁）
        __exit__:
            1. 释放 ResourceManager 资源锁（逆序）
            2. 无异常 → _confirm_task_done（设内存锁）
            3. 有异常 → _release_task（删数据库锁，允许重试）
    """

    def __init__(self, task_name, db, resources=None, min_interval_sec=7200):
        """
        Args:
            task_name: 任务标识（对应 task_log.task_key）
            db: 数据库实例（需有 claim_task 方法）
            resources: 需要锁定的资源名列表，如 ['ai', 'bot']，传 None 或空列表则不加资源锁
            min_interval_sec: 同一任务两次成功执行的最小间隔秒数
        """
        self.task_name = task_name
        self.db = db
        self.resources = sorted(resources) if resources else []
        self.min_interval_sec = min_interval_sec
        self._claimed = False
        self._acquired_locks = []

    @staticmethod
    def bind(rm):
        """绑定全局 ResourceManager 实例（启动时调用一次）"""
        global _rm_instance
        _rm_instance = rm

    @property
    def claimed(self):
        return self._claimed

    def __enter__(self):
        if not self._check_memory_lock():
            return self

        if not self._try_claim_db():
            return self

        if not self._acquire_resource_locks():
            self._release_task()
            return self

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release_resource_locks()

        # 【v5.31.2 P0 修复】claimed=False 时不设置内存锁
        # 之前即使 claim_task 失败（claimed=False），只要 with 块无异常就会调用 _confirm_task_done，
        # 导致内存锁被错误设置，可能影响后续任务调度。
        if not self._claimed:
            return False

        if exc_type is None:
            self._confirm_task_done()
        else:
            self._release_task()
            if getattr(exc_val, "expected", False):
                logger.info(f"ℹ️ [{self.task_name}] 任务正常中止，已释放数据库锁: {exc_val}")
            else:
                logger.warning(f"⚠️ [{self.task_name}] 事务异常，已释放数据库锁: {exc_val}")

        return False

    def _check_memory_lock(self) -> bool:
        now = int(time.time())
        with _task_lock:
            last = _last_task_run.get(self.task_name, 0)
            if now - last < self.min_interval_sec:
                logger.info(
                    f"⏳ [{self.task_name}] 内存锁跳过，距上次成功{now - last}秒 < {self.min_interval_sec}秒"
                )
                return False
        return True

    def _try_claim_db(self) -> bool:
        try:
            result = self.db.claim_task(self.task_name)
            if not result:
                logger.info(f"🔒 [{self.task_name}] 数据库锁拦截（今日已执行或被其他线程抢占）")
                return False
            logger.info(f"🔓 [{self.task_name}] 原子抢占成功")
            self._claimed = True
            return True
        except Exception as e:
            # 【TRAE SOLO CN v5.18.3审计修复】异常时 abort，绝不放行，防止重复播发
            logger.error(f"❌ [{self.task_name}] claim_task异常，abort任务: {e}")
            return False

    def _acquire_resource_locks(self) -> bool:
        if not self.resources:
            return True

        rm = _rm_instance
        if rm is None:
            logger.warning(f"⚠️ [{self.task_name}] ResourceManager未绑定，跳过资源锁")
            return True

        sorted_names = sorted(self.resources)
        for name in sorted_names:
            lock = rm._locks.get(name)
            if lock is None:
                logger.error(f"❌ [{self.task_name}] 未知资源: {name}")
                for acquired_lock in self._acquired_locks:
                    acquired_lock.release()
                self._acquired_locks.clear()
                return False
            if not lock.acquire(timeout=30.0):
                logger.warning(f"⚠️ [{self.task_name}] 获取资源 {name} 锁超时")
                for acquired_lock in self._acquired_locks:
                    acquired_lock.release()
                self._acquired_locks.clear()
                return False
            self._acquired_locks.append(lock)

        logger.debug(f"🔒 [{self.task_name}] 已获取资源锁: {sorted_names}")
        return True

    def _release_resource_locks(self):
        for lock in reversed(self._acquired_locks):
            try:
                lock.release()
            except Exception as e:
                # 【v5.31.2 修复】资源锁释放失败会导致其他任务长期饥饿，必须 warning 可见
                logger.warning(f"🔓 [{self.task_name}] 资源锁释放失败: {e}")
        if self._acquired_locks:
            logger.debug(f"🔓 [{self.task_name}] 已释放资源锁")
        self._acquired_locks.clear()

    def _confirm_task_done(self):
        now = int(time.time())
        with _task_lock:
            _last_task_run[self.task_name] = now
        logger.info(f"🔒 [{self.task_name}] 内存锁已设置，时间戳={now}")

    def _release_task(self):
        """【v5.31.2 修复】释放数据库任务锁

        之前直接走 self.db.conn.execute + commit，绕过 Repo 层的锁管理，
        在 WriteQueueConnectionProxy 下会出现 'cannot commit - no transaction is active'
        导致 DELETE 没生效，task_log 残留锁，后续重试被 claim_task 拦截。

        修复方案：
        1. 走 Repo 层 self.db.release_task（已注册，自带 thread lock）
        2. 失败时回退到直接 SQL，但用独立的 raw connection 避开 WriteQueue
        3. 都失败则记录 CRITICAL 让上层感知
        """
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        released = False

        # 方案 1：走 Repo 层
        try:
            released = self.db.release_task(self.task_name)
            if released:
                logger.info(f"🔓 [{self.task_name}] 数据库锁已释放（Repo层），允许重试")
                return
        except Exception as e:
            logger.warning(f"⚠️ [{self.task_name}] release_task(Repo层)异常: {e}")

        # 方案 2：直接 SQL 兜底（绕过 WriteQueue，用底层真实连接）
        # WriteQueueConnectionProxy 下 self.db.conn.execute 的 DELETE 可能因队列满静默丢弃，
        # 因此取 _real_conn 直接执行，保证 DELETE 真正落库。
        try:
            from core.database import _db_lock as db_lock
            real_conn = getattr(self.db, '_real_conn', None) or getattr(self.db, 'conn', None)
            with db_lock:
                cur = real_conn.execute(
                    "DELETE FROM task_log WHERE task_key=? AND exec_date=?",
                    (self.task_name, today),
                )
                real_conn.commit()
                if cur.rowcount > 0:
                    released = True
            if released:
                logger.info(f"🔓 [{self.task_name}] 数据库锁已释放（直连兜底），允许重试")
            else:
                logger.warning(f"⚠️ [{self.task_name}] 直连兜底未删除任何行（可能已被其他流程清理）")
        except Exception as e:
            logger.critical(
                f"🚨 [{self.task_name}] 释放数据库锁完全失败，task_log 可能残留: {e}。"
                f"需手动 DELETE FROM task_log WHERE task_key='{self.task_name}' AND exec_date='{today}'"
            )
