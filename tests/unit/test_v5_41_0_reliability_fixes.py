# -*- coding: utf-8 -*-
"""【v5.41.0 全仓治理】可靠性修复回归测试。

覆盖：
1. core/helpers.atomic_write_json - 原子写 JSON（成功替换 / 无临时残留 / 失败不损坏原文件）
2. tasks/support/fault_reporter 去重状态原子落盘
3. core/mory_bot - Telegram 写操作遇到结果不确定错误时不盲重发、不降级补发

设计原则：不连真实 DB / 不连真实 Telegram / 每用例独立可单跑。
"""

import json
import os
import sys
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


# ── 3. Telegram 写入不盲重发 ─────────────────────────────────────────────

class _UncertainWriteTeleBot:
    """模拟请求超时：服务端可能已经送达，客户端无法安全重试。"""

    def __init__(self):
        self.reply_calls = 0
        self.photo_calls = 0
        self.fallback_calls = 0

    def reply_to(self, *args, **kwargs):
        import requests

        self.reply_calls += 1
        raise requests.exceptions.Timeout("response lost")

    def send_photo(self, *args, **kwargs):
        import requests

        self.photo_calls += 1
        raise requests.exceptions.ConnectionError("response lost")

    def send_message(self, *args, **kwargs):
        self.fallback_calls += 1
        raise AssertionError("不应对未知结果自动补发")

    def delete_message(self, *args, **kwargs):
        return True

    def get_me(self):
        return object()

    def send_chat_action(self, *args, **kwargs):
        return True


class _TrackDB:
    def __init__(self):
        self.tracked = []

    def track_reply(self, *args):
        self.tracked.append(args)

    def track_channel_message(self, *args):
        self.tracked.append(args)


def _message(chat_id=-1001):
    from types import SimpleNamespace

    return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=77)


def test_reply_without_track_does_not_retry_or_fallback_after_uncertain_write():
    from core.mory_bot import MoryBot

    telebot = _UncertainWriteTeleBot()
    result = MoryBot(telebot, _TrackDB(), {}).reply_without_track(_message(), "hello")

    assert result is None
    assert telebot.reply_calls == 1
    assert telebot.fallback_calls == 0


def test_reply_and_track_does_not_retry_uncertain_write(monkeypatch):
    from core.mory_bot import MoryBot
    from tasks.support import fault_reporter

    fault_reports = []
    monkeypatch.setattr(fault_reporter, "report_fault", lambda *args, **kwargs: fault_reports.append(args))
    telebot = _UncertainWriteTeleBot()
    db = _TrackDB()

    result = MoryBot(telebot, db, {}).reply_and_track(_message(), "hello")

    assert result is None
    assert telebot.reply_calls == 1
    assert telebot.fallback_calls == 0
    assert db.tracked == []
    assert len(fault_reports) == 1


def test_reply_photo_and_track_does_not_retry_uncertain_write():
    from core.mory_bot import MoryBot

    telebot = _UncertainWriteTeleBot()
    result = MoryBot(telebot, _TrackDB(), {}).reply_photo_and_track(_message(), b"image")

    assert result is None
    assert telebot.photo_calls == 1


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
