# -*- coding: utf-8 -*-
"""TaskGuard 单元测试 - 覆盖并发告警/去重/抢占失败告警"""

from unittest.mock import MagicMock

import pytest

from tasks.support.task_guard import TaskGuard


@pytest.fixture
def guard():
    """每个测试重置单例状态，避免交叉污染"""
    g = TaskGuard()
    g._call_history.clear()
    g._claim_fail_count.clear()
    g._alerted.clear()
    return g


# ─────────────────── 1. 5 分钟内 2 次调用触发告警 ───────────────────

def test_record_call_triggers_alert_on_two_calls(guard):
    """同一任务 5 分钟内被调用 ≥2 次 → 触发告警"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_call("task_a")  # 第 1 次：count=1，不告警
    guard.record_call("task_a")  # 第 2 次：count=2，触发告警

    alert_mock.assert_called_once()
    msg = alert_mock.call_args[0][0]
    assert "task_a" in msg
    assert "2" in msg  # 被调用次数


# ─────────────────── 2. 同一分钟内多次调用只告警一次（去重） ───────────────────

def test_record_call_dedup_within_same_minute(guard):
    """同一分钟内多次调用 → 仅告警一次（alert_key 按分钟去重）"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_call("task_b")  # count=1，不告警
    guard.record_call("task_b")  # count=2，告警（alert_key 加入 _alerted）
    guard.record_call("task_b")  # count=3，alert_key 已存在 → 不重复告警

    alert_mock.assert_called_once()


# ─────────────────── 3. 连续 3 次抢占失败触发告警 ───────────────────

def test_record_claim_fail_triggers_alert_on_three(guard):
    """连续 3 次抢占失败 → 触发告警 + 计数重置"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_claim_fail("task_c", "lock_timeout")  # count=1
    guard.record_claim_fail("task_c", "lock_timeout")  # count=2
    guard.record_claim_fail("task_c", "lock_timeout")  # count=3 → 告警 + 重置

    alert_mock.assert_called_once()
    msg = alert_mock.call_args[0][0]
    assert "task_c" in msg
    assert "3" in msg  # 连续失败次数
    # 告警后计数重置为 0
    assert guard._claim_fail_count.get("task_c", 0) == 0


def test_record_claim_fail_dedup_same_hour(guard):
    """同一小时内再次达到阈值 → alert_key 去重，不重复告警"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    # 前 3 次触发第一次告警
    for _ in range(3):
        guard.record_claim_fail("task_d", "fail")

    # 再 3 次（同一小时内，alert_key 相同）→ 不重复告警
    for _ in range(3):
        guard.record_claim_fail("task_d", "fail")

    alert_mock.assert_called_once()


# ─────────────────── 4. record_claim_ok 重置失败计数 ───────────────────

def test_record_claim_ok_resets_count(guard):
    """record_claim_ok 重置计数 → 后续 2 次失败不触发告警（需 3 次）"""
    alert_mock = MagicMock()
    guard._send_alert = alert_mock

    guard.record_claim_fail("task_e", "fail")  # count=1
    guard.record_claim_fail("task_e", "fail")  # count=2
    guard.record_claim_ok("task_e")            # 重置 → count=0
    guard.record_claim_fail("task_e", "fail")  # count=1

    alert_mock.assert_not_called()
