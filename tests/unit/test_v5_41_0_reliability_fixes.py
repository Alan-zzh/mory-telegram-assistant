# -*- coding: utf-8 -*-
"""【v5.41.0 全仓治理】可靠性修复回归测试。

覆盖：
1. core/helpers.atomic_write_json - 原子写 JSON（成功替换 / 无临时残留 / 失败不损坏原文件）
2. tasks/support/fault_reporter 去重状态原子落盘
3. core/mory_bot._send_with_network_retry - 瞬态网络错误重试一次 / API 语义错误不重试

设计原则：不连真实 DB / 不连真实 Telegram / 每用例独立可单跑。
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ── 1. atomic_write_json ──────────────────────────────────────────────────

def test_atomic_write_json_creates_and_replaces(tmp_path):
    from core.helpers import atomic_write_json

    target = tmp_path / "state.json"
    atomic_write_json(str(target), {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}

    atomic_write_json(str(target), {"a": 2}, indent=2)
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert "\n" in target.read_text(encoding="utf-8")


def test_atomic_write_json_leaves_no_tmp_residue(tmp_path):
    from core.helpers import atomic_write_json

    target = tmp_path / "state.json"
    atomic_write_json(str(target), {"ok": True})

    residues = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp_")]
    assert residues == []


def test_atomic_write_json_failure_keeps_original_intact(tmp_path, monkeypatch):
    """写入中途崩溃（模拟 os.replace 前抛错）时，原文件必须完好无损。"""
    import json as _json

    import core.helpers as helpers

    target = tmp_path / "state.json"
    target.write_text('{"original": true}', encoding="utf-8")

    def broken_dump(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(_json, "dump", broken_dump)

    with pytest.raises(RuntimeError):
        helpers.atomic_write_json(str(target), {"new": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}


# ── 2. fault_reporter 原子落盘 ────────────────────────────────────────────

def test_fault_reporter_dedup_state_saved_atomically(tmp_path, monkeypatch):
    """去重状态文件必须是合法 JSON（旧实现写一半崩溃会产生半截文件）。

    FaultReporter 是单例且状态文件为类常量，这里 monkeypatch 路径指向 tmp。
    """
    from tasks.support import fault_reporter as fr

    state_file = tmp_path / "fault_dedup_state.json"
    monkeypatch.setattr(fr.FaultReporter, "_DEDUP_STATE_FILE", str(state_file))
    reporter = fr.FaultReporter()
    reporter._last_alert = {"⚠️_cat": 1234567890}
    reporter._save_dedup_state()

    assert json.loads(state_file.read_text(encoding="utf-8")) == {"⚠️_cat": 1234567890}


# ── 3. Telegram 发送瞬态网络重试 ─────────────────────────────────────────

class _FlakyBot:
    """前 N 次调用抛瞬态网络错误，之后成功。"""

    def __init__(self, transient_failures: int):
        self.transient_failures = transient_failures
        self.calls = 0

    def __call__(self, *args, **kwargs):
        import requests

        self.calls += 1
        if self.calls <= self.transient_failures:
            raise requests.exceptions.ConnectionError("connection reset")
        return MagicMock(message_id=42)


class _ApiSemanticError(Exception):
    """模拟 ApiTelegramException（API 语义错误，绝不可重试）。"""


def test_send_retry_recovers_after_transient_network_error():
    from core.mory_bot import _send_with_network_retry

    flaky = _FlakyBot(transient_failures=1)
    sent = _send_with_network_retry(flaky, "chat", "text")

    assert sent is not None
    assert flaky.calls == 2


def test_send_retry_gives_up_after_second_transient_failure(monkeypatch):
    from core import mory_bot

    monkeypatch.setattr(mory_bot.time, "sleep", lambda *_: None)
    flaky = _FlakyBot(transient_failures=99)

    with pytest.raises(Exception):
        mory_bot._send_with_network_retry(flaky, "chat", "text")
    assert flaky.calls == 2


def test_send_retry_never_retries_api_semantic_errors():
    """4xx 类语义错误（如消息已删除）重试只会重复失败或重复发送，禁止重试。"""
    calls = {"n": 0}

    def semantic_fail(*args, **kwargs):
        calls["n"] += 1
        raise _ApiSemanticError("message to be replied not found")

    with pytest.raises(_ApiSemanticError):
        from core.mory_bot import _send_with_network_retry
        _send_with_network_retry(semantic_fail, "chat", "text")

    assert calls["n"] == 1


# ── 4. pypinyin 正式依赖（v5.41.0 删手写映射表回退）─────────────────────

def test_pinyin_util_covers_chars_beyond_old_handmade_table():
    """旧手写表只有82字；pypinyin 必须覆盖任意汉字（如穿帮变体常用字）。"""
    from core.pinyin_util import text_to_pinyin_silent

    # 旧表未收录的字：'骗'、'假'、'真'
    result = text_to_pinyin_silent("我是人工智能")
    assert result == "wo shi ren gong zhi neng"
    assert text_to_pinyin_silent("") == ""
    assert all(
        ch == " " or ch.isascii()
        for ch in text_to_pinyin_silent("骗假真人机混合")
    )
