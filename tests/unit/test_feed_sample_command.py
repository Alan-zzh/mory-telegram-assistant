# -*- coding: utf-8 -*-
"""风格样本投喂命令单测（v5.38.26 Agent G）。

覆盖：
- _parse_feed_scene：显式/中文别名/缺省/非法场景
- _parse_and_feed_pairs：两行一组配对、user:/mory: 前缀配对、孤儿行计数
- 安全校验拒绝：敏感词（保证/包过/限时福利）、长度越界
- 入库只生成 pending（create_reply_style_sample 返回 ok 即视为已入待审队列）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from modules.admin_cmds import _parse_and_feed_pairs, _parse_feed_scene


# ---------------------------------------------------------------------------
# 场景解析
# ---------------------------------------------------------------------------

def test_parse_feed_scene_defaults_to_chat():
    assert _parse_feed_scene("用户问你好呀 | 你好呀") == ("chat", "")


def test_parse_feed_scene_explicit_and_alias():
    assert _parse_feed_scene("场景:greeting 早呀 | 早呀") == ("greeting", "")
    assert _parse_feed_scene("场景：搭讪 想了解下 | 可以呀") == ("engage", "")
    assert _parse_feed_scene("场景:播报 今日播报 | 好的") == ("broadcast", "")


def test_parse_feed_scene_rejects_unknown():
    scene, err = _parse_feed_scene("场景:恋爱 在吗 | 在呀")
    assert scene == ""
    assert "不支持" in err


# ---------------------------------------------------------------------------
# 批量解析：两行一组 / 前缀配对 / 孤儿行
# ---------------------------------------------------------------------------

class _FakeFeedDB:
    """记录 create_reply_style_sample 调用的假 db。"""

    def __init__(self):
        self.calls = []

    def create_reply_style_sample(self, text, label="", created_by="", scene="chat",
                                  user_text="", mory_text=""):
        ok = bool(user_text and mory_text and scene in (
            "chat", "greeting", "engage", "faq", "broadcast"))
        self.calls.append({"ok": ok, "scene": scene, "user": user_text, "mory": mory_text})
        return {"ok": ok, "id": len(self.calls)}


def test_pair_parse_two_lines_per_group():
    db = _FakeFeedDB()
    content = "用户第一句\nMory第一句\n用户第二句\nMory第二句"
    ok_count, orphan, errors = _parse_and_feed_pairs(db, content, "chat", "admin")
    assert ok_count == 2
    assert orphan == 0
    assert errors == []
    assert db.calls[0]["user"] == "用户第一句"
    assert db.calls[1]["mory"] == "Mory第二句"


def test_pair_parse_prefix_format():
    db = _FakeFeedDB()
    content = "user:在吗，今天忙不忙\nmory:还行，你呢，今天有没有什么想聊的\nuser:你们这边多少钱\nmory:先看看预览再聊价格，心里有数不着急。"
    ok_count, orphan, _ = _parse_and_feed_pairs(db, content, "chat", "admin")
    assert ok_count == 2
    assert orphan == 0


def test_pair_parse_orphan_lines_counted():
    db = _FakeFeedDB()
    content = "只有一句没配对\nuser:第二组用户\nmory:第二组回复\n结尾孤儿"
    ok_count, orphan, _ = _parse_and_feed_pairs(db, content, "chat", "admin")
    assert ok_count == 1
    assert orphan == 2


def test_safety_rejects_sensitive_claims():
    from core.db_repos.reply_evolution_repo import validate_feed_sample_safety

    ok, reason = validate_feed_sample_safety("这个能保证成功吗", "保证没问题，包过就行")
    assert not ok
    assert reason  # 通用拒绝文案非空

    ok, reason = validate_feed_sample_safety("有什么福利可以领", "限时福利，只有今天有")
    assert not ok

    ok, reason = validate_feed_sample_safety("你们这边怎么样", "内容都在预览里，自己看就行。")
    assert ok


def test_safety_rejects_out_of_range_length():
    from core.db_repos.reply_evolution_repo import validate_feed_sample_safety

    ok, reason = validate_feed_sample_safety("短", "也是短")
    assert not ok

    ok, reason = validate_feed_sample_safety("长" * 600, "回复" * 600)
    assert not ok


def test_feed_only_creates_pending_via_db():
    """投喂链路只调 create_reply_style_sample，且不带任何启用/审核动作。"""
    db = _FakeFeedDB()
    content = "user:想看看你们的内容\nmory:预览里都有，你自己看看合不合口味。"
    _parse_and_feed_pairs(db, content, "greeting", "admin")
    assert len(db.calls) == 1
    assert db.calls[0]["scene"] == "greeting"
    assert db.calls[0]["ok"] is True
