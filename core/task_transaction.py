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
        # 【v5.38.9】真实任务执行历史审计:抢占成功后写入 running,退出时更新 success/failed/aborted
        # task_log 是分布式锁表(执行后 DELETE),无法算成功率,改用 task_execution_history 表
        self._exec_history_id = None
        self._exec_start_ts = 0.0

    @staticmethod
    def bind(rm):
        """绑定全局 ResourceManager 实例（启动时调用一次）"""
        global _rm_instance
        _rm_instance = rm

    @property
    def claimed(self):
        return self._claimed

    def __enter__(self):
        # 【v5.38.9】记录任务开始时间戳(高精度),用于 __exit__ 计算 duration_ms
        self._exec_start_ts = time.time()

        if not self._check_memory_lock():
            return self

        if not self._try_claim_db():
            return self

        if not self._acquire_resource_locks():
            self._release_task()
            # 【P0-2 修复】资源锁失败时必须重置 _claimed = False,
            # 否则 __exit__ 仍走 success 分支(_confirm_task_done 设内存锁),
            # 导致任务被错误标记为已完成,无法重试。
            # claimed property 直接返回 self._claimed,无需单独同步。
            self._claimed = False
            return self

        # 【P1-4 注释】claim_task 和 record_task_start 各自计算 today,
        # 理论上存在毫秒级跨天风险(claim_task 用 23:59:59.xxx,
        # record_task_start 用 00:00:00.xxx)。但实际影响极小:
        # task_log 用 UNIQUE(task_key, exec_date) 拦截,跨天时会写入两条记录
        # (claim_task 写 today,record_task_start 写 tomorrow),不影响防重;
        # task_execution_history 只是审计表,跨天统计偏差最多 1 条。
        # 真正需要解决时,应将 today 作为参数传入两个方法(避免影响其他调用方)。
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release_resource_locks()

        # 【v5.38.9】计算 duration_ms(毫秒),用于真实成功率统计
        # _exec_start_ts 在 __enter__ 入口已捕获;若未抢占成功则为 0,duration_ms 留空
        duration_ms = None
        if self._exec_start_ts > 0:
            duration_ms = int((time.time() - self._exec_start_ts) * 1000)

        # 【v5.31.2 P0 修复】claimed=False 时不设置内存锁
        # 之前即使 claim_task 失败（claimed=False），只要 with 块无异常就会调用 _confirm_task_done，
        # 导致内存锁被错误设置，可能影响后续任务调度。
        if not self._claimed:
            # 未抢占成功但已写入 running 记录(极少数:_try_claim_db 成功后 _acquire_resource_locks 失败),
            # 此处 _release_task 会回滚 task_log,但 task_execution_history 应标记为 aborted
            self._record_exec_abort_safe(str(exc_val) if exc_val else "resource_lock_failed")
            return False

        if exc_type is None:
            # 【P0-3 修复】如果 _exec_history_id is None(record_task_start 失败),
            # 不调用 _confirm_task_done(不设置内存锁),让任务可重试。
            # 否则内存锁被设置后,任务在 min_interval_sec 内无法重试,
            # 而 task_execution_history 漏统计(running 记录未写入)。
            if self._exec_history_id is not None:
                self._confirm_task_done()
            else:
                logger.warning(
                    f"⚠️ [{self.task_name}] _exec_history_id is None(审计表未写入),"
                    f"跳过 _confirm_task_done 以允许任务重试"
                )
            self._record_exec_success_safe(duration_ms)
        else:
            # 【P1-3 修复】调整顺序:先 _record_exec_failure_safe(记录失败状态),
            # 再 _release_task(释放 task_log)。这样即使 _release_task 失败,
            # 审计表已记录失败,避免出现"任务失败但审计表卡 running"的脏数据。
            if getattr(exc_val, "expected", False):
                logger.info(f"ℹ️ [{self.task_name}] 任务正常中止: {exc_val}")
                self._record_exec_abort_safe(str(exc_val))
            else:
                logger.warning(f"⚠️ [{self.task_name}] 事务异常: {exc_val}")
                self._record_exec_failure_safe(str(exc_val), duration_ms)
            self._release_task()
            logger.info(f"🔓 [{self.task_name}] 数据库锁已释放(异常分支)")

        return False

    # ─────────────────── v5.38.9 task_execution_history 写入辅助 ───────────────────
    # 所有写入吞掉异常,绝不影响任务主链路;error_msg 在 Repo 层已截断到 500 字符

    def _record_exec_success_safe(self, duration_ms):
        if not self._exec_history_id:
            # 【P0-3 修复】record_task_start 失败时审计表未写入,记录 WARNING 便于排查
            logger.warning(f"⚠️ [{self.task_name}] _record_exec_success 跳过: _exec_history_id is None(审计表未写入)")
            return
        try:
            self.db.record_task_success(self._exec_history_id, duration_ms)
        except Exception as e:
            logger.warning(f"⚠️ [{self.task_name}] record_task_success 失败(忽略): {e}")

    def _record_exec_failure_safe(self, error_msg, duration_ms):
        if not self._exec_history_id:
            # 【P0-3 修复】record_task_start 失败时审计表未写入,记录 WARNING 便于排查
            logger.warning(f"⚠️ [{self.task_name}] _record_exec_failure 跳过: _exec_history_id is None(审计表未写入)")
            return
        try:
            self.db.record_task_failure(self._exec_history_id, error_msg, duration_ms)
        except Exception as e:
            logger.warning(f"⚠️ [{self.task_name}] record_task_failure 失败(忽略): {e}")

    def _record_exec_abort_safe(self, reason):
        if not self._exec_history_id:
            # 【P0-3 修复】record_task_start 失败时审计表未写入,记录 WARNING 便于排查
            logger.warning(f"⚠️ [{self.task_name}] _record_exec_abort 跳过: _exec_history_id is None(审计表未写入)")
            return
        try:
            self.db.record_task_abort(self._exec_history_id, reason)
        except Exception as e:
            logger.warning(f"⚠️ [{self.task_name}] record_task_abort 失败(忽略): {e}")

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
            # 【v5.38.9】抢占成功后写入 task_execution_history(running),
            # 失败时只 warning 不抛,绝不影响任务主链路
            try:
                self._exec_history_id = self.db.record_task_start(self.task_name)
            except Exception as e:
                logger.warning(f"⚠️ [{self.task_name}] record_task_start 失败(忽略): {e}")
                self._exec_history_id = None
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
        # 【P1-1 修复】同时删除今天和昨天的记录,处理跨天边界:
        # 任务在 23:59:59 claim_task 写入 today,00:00:01 release 时 today 已变,
        # DELETE WHERE exec_date=today 找不到旧记录,导致 task_log 残留锁。
        try:
            from core.database import _db_lock as db_lock
            real_conn = getattr(self.db, '_real_conn', None) or getattr(self.db, 'conn', None)
            today = datetime.now(_CST).strftime("%Y-%m-%d")
            yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
            with db_lock:
                cur = real_conn.execute(
                    "DELETE FROM task_log WHERE task_key=? AND exec_date IN (?, ?)",
                    (self.task_name, today, yesterday),
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
                f"需手动 DELETE FROM task_log WHERE task_key='{self.task_name}'"
            )
            # 【P1-NEW-11】尝试通知运维，三级回退全部失败时任务会永久锁死
            try:
                from tasks.support.fault_reporter import get_fault_reporter
                reporter = get_fault_reporter()
                if reporter:
                    reporter.report(
                        "task_lock_stuck",
                        f"任务 {self.task_name} 释放数据库锁完全失败，task_log 残留，需人工干预",
                        severity="🚨",
                    )
            except Exception:
                pass  # 通知失败不加重原问题
