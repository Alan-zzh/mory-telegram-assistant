# -*- coding: utf-8 -*-
"""任务真实执行历史审计 Repo。

背景:
    task_log 是分布式锁表,任务执行后 DELETE 释放,基于它算"任务成功率"必然
    100% 失真。此 Repo 落地 task_execution_history 表,由 TaskTransactionManager
    在 __enter__/__exit__ 写入 running/success/failed/aborted 四态,
    /api/health/task-success-rate 读取真实成功率。

设计:
    - record_task_start  : __enter__ 中抢占成功后调用,返回自增 id
    - record_task_success: __exit__ 无异常时调用,补 end_ts + duration_ms
    - record_task_failure: __exit__ 有非 expected 异常时调用,记录 error_msg(前 500 字)
    - record_task_abort  : __exit__ 异常为 expected=True 时调用(主动中止)
    - get_success_rate   : 查询最近 N 天真实统计

    error_msg 截断到 500 字符避免日志爆炸;所有写入吞掉异常,绝不影响任务主链路。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Optional

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.task_exec_history")

# 错误信息截断长度,防止超大 traceback 把表撑爆
_MAX_ERROR_MSG_LENGTH = 500


class TaskExecHistoryRepo:
    """任务真实执行历史审计。"""

    def __init__(self, db: Any):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    def _ensure_schema(self) -> bool:
        """确认中央数据库已完成审计表初始化，不在请求路径写 DDL。"""
        with self.lock:
            try:
                self.conn.execute("SELECT 1 FROM task_execution_history LIMIT 1")
                return True
            except Exception as exc:
                logger.warning("任务执行审计 schema 未就绪，请先运行数据库初始化/迁移: %s", exc)
                return False

    def record_task_start(self, task_key: str) -> Optional[int]:
        """插入一条 running 记录,返回自增 id。

        失败时返回 None,绝不抛异常影响任务主链路。
        """
        now = int(time.time())
        today = datetime.now(_CST).strftime("%Y-%m-%d")
        with self.lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO task_execution_history "
                    "(task_key, exec_date, start_ts, status) VALUES (?, ?, ?, 'running')",
                    (str(task_key), today, now),
                )
                self.conn.commit()
                task_id = cur.lastrowid
                logger.info(f"📊 [task_exec] start task_id={task_id} key={task_key}")
                return task_id
            except Exception as exc:
                logger.warning(f"📊 [task_exec] record_task_start({task_key}) 失败: {exc}")
                return None

    def _finalize(self, task_id: Optional[int], status: str,
                  error_msg: Optional[str] = None, duration_ms: Optional[int] = None) -> bool:
        """统一更新终态。内部辅助方法,不暴露给 _REPO_METHOD_MAP。"""
        if not task_id:
            return False
        now = int(time.time())
        safe_msg = None
        if error_msg:
            safe_msg = str(error_msg)[:_MAX_ERROR_MSG_LENGTH]
        with self.lock:
            try:
                # 【P2-2 修复】增加 AND status='running' 状态守卫,
                # 防止重复 finalize(如 __exit__ 异常分支先记录 failed,
                # 后续僵尸清理又把同一记录改成 failed/aborted 造成状态混乱)。
                cur = self.conn.execute(
                    "UPDATE task_execution_history SET status=?, end_ts=?, error_msg=?, duration_ms=? "
                    "WHERE id=? AND status='running'",
                    (status, now, safe_msg, duration_ms, int(task_id)),
                )
                self.conn.commit()
                updated = cur.rowcount > 0
                logger.info(
                    f"📊 [task_exec] finalize id={task_id} status={status} "
                    f"duration_ms={duration_ms} updated={updated}"
                )
                return updated
            except Exception as exc:
                logger.warning(f"📊 [task_exec] _finalize(id={task_id}, status={status}) 失败: {exc}")
                return False

    def record_task_success(self, task_id: Optional[int], duration_ms: Optional[int] = None) -> bool:
        """更新为 success。"""
        return self._finalize(task_id, "success", error_msg=None, duration_ms=duration_ms)

    def record_task_failure(self, task_id: Optional[int], error_msg: Optional[str] = None,
                            duration_ms: Optional[int] = None) -> bool:
        """更新为 failed,记录 error_msg 前 500 字符。"""
        return self._finalize(task_id, "failed", error_msg=error_msg, duration_ms=duration_ms)

    def record_task_abort(self, task_id: Optional[int], reason: Optional[str] = None) -> bool:
        """更新为 aborted(主动中止,如任务被去重跳过、expected 异常)。"""
        return self._finalize(task_id, "aborted", error_msg=reason, duration_ms=None)

    def get_success_rate(self, days: int = 7) -> dict:
        """返回最近 N 天真实统计。

        语义:days=N 表示"包含今天在内的最近 N 天",即 cutoff_date = today - N days。
        例如 days=7 时,cutoff_date 为 7 天前的日期,查询 exec_date >= cutoff_date,
        实际覆盖 8 个自然日(含今天),但通常所说的"最近 7 天"即此语义。

        Returns:
            {
                "total": int,
                "success": int,
                "failed": int,
                "aborted": int,
                "running": int,        # 仍在 running 的(可能崩溃残留)
                "rate": float,         # 成功率 = success / (total - aborted) * 100
                "days": int,
            }
        """
        days = max(1, min(int(days or 7), 90))
        cutoff_date = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.lock:
            try:
                rows = self.conn.execute(
                    "SELECT status, COUNT(*) FROM task_execution_history "
                    "WHERE exec_date >= ? GROUP BY status",
                    (cutoff_date,),
                ).fetchall()
            except Exception as exc:
                logger.warning(f"📊 [task_exec] get_success_rate(days={days}) 失败: {exc}")
                return {
                    "total": 0, "success": 0, "failed": 0, "aborted": 0, "running": 0,
                    "rate": 0.0, "days": days,
                }

        counts = {row[0]: int(row[1]) for row in rows}
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        aborted = counts.get("aborted", 0)
        running = counts.get("running", 0)
        total = success + failed + aborted + running
        # 成功率 = success / (success + failed + running),aborted 是主动中止不计入分母
        denom = success + failed + running
        rate = round(success * 100.0 / denom, 2) if denom > 0 else 0.0
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "aborted": aborted,
            "running": running,
            "rate": rate,
            "days": days,
        }

    def cleanup_zombie_running(self, timeout_seconds: int = 1800) -> int:
        """将上个进程遗留的 running 记录终结，并同步释放任务锁。

        进程被 SIGKILL 时 task_execution_history 卡 running,无清理机制。
        timeout_seconds=0 用于新进程启动恢复：此时尚无本进程任务运行，数据库中
        所有 running 都属于已退出的旧进程，可安全立即终结。正值保留历史的超时清理语义。

        Args:
            timeout_seconds: 0 表示清理全部旧进程 running；正值表示超时阈值。
        Returns:
            受影响行数。
        """
        now = int(time.time())
        timeout_seconds = max(0, int(timeout_seconds or 0))
        cutoff_ts = now - timeout_seconds
        with self.lock:
            try:
                rows = self.conn.execute(
                    "SELECT id, task_key, exec_date, start_ts FROM task_execution_history "
                    "WHERE status='running' AND start_ts <= ?",
                    (cutoff_ts,),
                ).fetchall()
                reason = (
                    "process_restarted_before_completion"
                    if timeout_seconds == 0 else "process killed or timeout"
                )
                for task_id, task_key, exec_date, start_ts in rows:
                    self.conn.execute(
                        "UPDATE task_execution_history SET status='failed', end_ts=?, "
                        "error_msg=?, duration_ms=? WHERE id=? AND status='running'",
                        (now, reason, max(0, now - int(start_ts)) * 1000, int(task_id)),
                    )
                    self.conn.execute(
                        "DELETE FROM task_log WHERE task_key=? AND exec_date=?",
                        (task_key, exec_date),
                    )
                # claim 成功但 record_task_start 前崩溃：task_log 孤立日锁无 history
                orphan_logs = self.conn.execute(
                    "SELECT task_key, exec_date FROM task_log WHERE exec_date >= date('now', 'localtime', '-1 day') "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM task_execution_history h "
                    "  WHERE h.task_key = task_log.task_key AND h.exec_date = task_log.exec_date"
                    ")"
                ).fetchall()
                for task_key, exec_date in orphan_logs:
                    self.conn.execute(
                        "DELETE FROM task_log WHERE task_key=? AND exec_date=?",
                        (task_key, exec_date),
                    )
                self.conn.commit()
                affected = len(rows) + len(orphan_logs)
                if affected > 0:
                    logger.warning(
                        f"📊 [task_exec] cleanup_zombie_running: history_running={len(rows)} "
                        f"orphan_task_log={len(orphan_logs)} 已释放"
                    )
                return affected
            except Exception as exc:
                try:
                    self.conn.rollback()
                except Exception as rollback_exc:
                    logger.critical(
                        f"📊 [task_exec] cleanup_zombie_running 回滚失败: {rollback_exc}"
                    )
                logger.error(f"📊 [task_exec] cleanup_zombie_running 失败: {exc}")
                raise

    def cleanup_old_history(self, days: int = 90) -> int:
        """【P2-1】清理超过 N 天的历史记录,返回删除行数。

        Args:
            days: 保留天数,默认 90 天。
        Returns:
            删除行数。
        """
        days = max(1, int(days or 90))
        cutoff_date = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.lock:
            try:
                cur = self.conn.execute(
                    "DELETE FROM task_execution_history WHERE exec_date < ?",
                    (cutoff_date,),
                )
                self.conn.commit()
                deleted = cur.rowcount
                if deleted > 0:
                    logger.info(f"📊 [task_exec] cleanup_old_history: 删除 {deleted} 条超过 {days} 天的历史记录")
                return deleted
            except Exception as exc:
                logger.warning(f"📊 [task_exec] cleanup_old_history 失败: {exc}")
                return 0
