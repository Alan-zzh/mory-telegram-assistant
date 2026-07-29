# -*- coding: utf-8 -*-
"""TaskTransactionManager 单元测试 - 覆盖 5 个关键分支"""

import pytest
from unittest.mock import MagicMock, patch

from core.task_transaction import TaskTransactionManager


class _FakeDb:
    """轻量 mock DB，模拟 claim/release/history 全流程"""

    def __init__(self, claim_result=True, start_id=1, start_error=None):
        self.claimed = []
        self.released = []
        self.history = []  # [("start", key), ("success", id, ms), ("failure", id, msg), ("abort", id, reason)]
        self._claim_result = claim_result
        self._start_id = start_id
        self._start_error = start_error

    def claim_task(self, task_key):
        self.claimed.append(task_key)
        return self._claim_result

    def release_task(self, task_key):
        self.released.append(task_key)
        return True

    def record_task_start(self, task_key):
        if self._start_error:
            raise self._start_error
        self.history.append(("start", task_key))
        return self._start_id

    def record_task_success(self, history_id, duration_ms):
        self.history.append(("success", history_id, duration_ms))

    def record_task_failure(self, history_id, error_msg, duration_ms):
        self.history.append(("failure", history_id, error_msg))

    def record_task_abort(self, history_id, reason):
        self.history.append(("abort", history_id, reason))


# ─────────────────── 1. 正常成功路径 ───────────────────

def test_normal_success_path():
    """claim 成功 → 资源锁成功 → with 无异常 → 标记 success + 设内存锁"""
    db = _FakeDb()
    tx = TaskTransactionManager("ut_success", db, resources=[], min_interval_sec=0)
    confirm_mock = MagicMock()
    tx._confirm_task_done = confirm_mock

    with patch.object(tx, "_acquire_resource_locks", return_value=True):
        with tx:
            assert tx.claimed is True

    # 验证 success 记录
    success_calls = [h for h in db.history if h[0] == "success"]
    assert len(success_calls) == 1
    assert success_calls[0][1] == 1  # history_id
    # 验证内存锁已设置
    confirm_mock.assert_called_once()


# ─────────────────── 2. 任务抛异常路径 ───────────────────

def test_task_raises_exception():
    """claim 成功 → with 抛异常 → 标记 failure + release_task"""
    db = _FakeDb()
    tx = TaskTransactionManager("ut_raise", db, resources=[], min_interval_sec=0)

    with patch.object(tx, "_acquire_resource_locks", return_value=True):
        with pytest.raises(ValueError, match="test error"):
            with tx:
                raise ValueError("test error")

    # 验证 failure 记录
    failure_calls = [h for h in db.history if h[0] == "failure"]
    assert len(failure_calls) == 1
    assert "test error" in failure_calls[0][2]
    # 验证 release_task 被调用
    assert db.released == ["ut_raise"]


# ─────────────────── 3. 资源锁获取失败路径 ───────────────────

def test_resource_lock_failure():
    """claim 成功 → 资源锁失败 → _claimed=False → 不标记 success/failure"""
    db = _FakeDb()
    tx = TaskTransactionManager("ut_lockfail", db, resources=["ai"], min_interval_sec=0)

    with patch.object(tx, "_acquire_resource_locks", return_value=False):
        with tx:
            pass  # 用户应检查 tx.claimed 并 return

    # _claimed 被重置为 False
    assert tx.claimed is False
    # 不应有 success / failure 记录
    assert not any(h[0] == "success" for h in db.history)
    assert not any(h[0] == "failure" for h in db.history)
    # claim 成功后 release_task 应被调用（资源锁失败时回滚）
    assert db.released == ["ut_lockfail"]
    # 应记录 abort（_exec_history_id 已设置）
    abort_calls = [h for h in db.history if h[0] == "abort"]
    assert len(abort_calls) == 1


# ─────────────────── 4. record_task_start 失败路径 ───────────────────

def test_record_task_start_failure():
    """claim 成功 → record_task_start 异常 → _exec_history_id=None → 不设内存锁"""
    db = _FakeDb(start_error=RuntimeError("db error"))
    tx = TaskTransactionManager("ut_startfail", db, resources=[], min_interval_sec=0)
    confirm_mock = MagicMock()
    tx._confirm_task_done = confirm_mock

    with patch.object(tx, "_acquire_resource_locks", return_value=True):
        with tx:
            assert tx.claimed is True

    # _exec_history_id 为 None
    assert tx._exec_history_id is None
    # 不调用 _confirm_task_done（不设内存锁，允许重试）
    confirm_mock.assert_not_called()
    # 不调用 record_task_success（_exec_history_id 为 None 时跳过）
    assert not any(h[0] == "success" for h in db.history)


# ─────────────────── 5. claim 失败路径 ───────────────────

def test_claim_failure():
    """claim_task 返回 False → claimed=False → with 块跳过 → 不标记"""
    db = _FakeDb(claim_result=False)
    tx = TaskTransactionManager("ut_claimfail", db, resources=[], min_interval_sec=0)

    with tx:
        pass  # claim 失败，用户应检查 tx.claimed 并 return

    # claimed 为 False
    assert tx.claimed is False
    # 不调用 claim_task 之外的任何 record 方法
    assert not any(h[0] == "success" for h in db.history)
    assert not any(h[0] == "failure" for h in db.history)
    assert not any(h[0] == "start" for h in db.history)
    # claim 失败不应调用 release_task
    assert db.released == []
