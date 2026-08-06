# -*- coding: utf-8 -*-
"""运行时样本读取：管理员确认放行样本跳过二次敏感词校验（v5.38.29）。"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.db_repos.reply_evolution_repo import ReplyEvolutionRepo


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeDB:
    lock = _FakeLock()

    def __init__(self, conn):
        self.conn = conn


def _make_repo() -> ReplyEvolutionRepo:
    conn = sqlite3.connect(":memory:")
    repo = ReplyEvolutionRepo(_FakeDB(conn))
    repo._ensure_schema()
    return repo


def _insert(repo, label, style_text, scene, note):
    now = int(time.time())
    repo.conn.execute(
        "INSERT INTO reply_style_samples "
        "(label, style_text, status, enabled, created_by, scene, created_at, review_note) "
        "VALUES (?, ?, 'approved', 1, 'admin', ?, ?, ?)",
        (label, style_text, scene, now, note),
    )
    repo.conn.commit()


def test_approved_override_samples_skip_second_validation():
    """管理员确认放行（review_note 含关键词）的样本即使含业务词也能被运行时读取。"""
    repo = _make_repo()
    _insert(repo, "a", "用户：多少钱\nMory：视频独家订制，去自助下单", "chat", "用户确认预设直接启用")
    _insert(repo, "b", "用户：好孤独\nMory：至臻全享，保证你不孤独", "chat", "管理员确认放行")
    active = repo.get_approved_reply_style_samples(limit=3, scene="chat")
    assert len(active) == 2  # 含"独家/保证"但被放行


def test_plain_samples_still_second_validated():
    """普通样本（无放行标注）仍须通过二次敏感词校验。"""
    repo = _make_repo()
    _insert(repo, "c", "用户：你好\nMory：你好呀，想聊什么？", "chat", "")
    _insert(repo, "d", "用户：问价\nMory：保证最低价包过", "chat", "")  # 敏感词，应被过滤
    active = repo.get_approved_reply_style_samples(limit=3, scene="chat")
    assert len(active) == 1
    assert "你好呀" in active[0]
