# -*- coding: utf-8 -*-
"""启动追溯扫描的防误删回归测试。"""

import json
import sqlite3
from types import SimpleNamespace

from core.bot_initializer import _get_latest_snapshot_message_id
from modules.ad_detector import AdDetector


class _ProtectedContentBot:
    def __init__(self):
        self.deleted = []

    def forward_message(self, *args, **kwargs):
        raise RuntimeError("Bad Request: message can't be forwarded because of protected content")

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))
        return True


class _AlreadyAbsentBot(_ProtectedContentBot):
    def delete_message(self, chat_id, message_id):
        raise RuntimeError("Bad Request: message to delete not found")


def _make_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        """CREATE TABLE message_snapshots (
            chat_id INTEGER,
            msg_id INTEGER,
            user_id INTEGER,
            text TEXT,
            ts INTEGER,
            is_ad INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            PRIMARY KEY(chat_id, msg_id)
        )"""
    )
    return SimpleNamespace(conn=conn)


def _scan(detector, bot, chat_id=-1001, start=1, end=200, deletion_enabled=True):
    return detector.retroactive_scan(
        bot,
        chat_id,
        start,
        end,
        admin_id=999,
        config={"ENABLE_MESSAGE_DELETION": deletion_enabled},
    )


def test_protected_group_never_bulk_deletes_without_tracking_evidence():
    """保护内容群没有逐条证据时，不得按消息 ID 范围盲删。"""
    detector = AdDetector(config={}, db=_make_db())
    bot = _ProtectedContentBot()

    result = _scan(detector, bot)

    assert result["mode"] == "database"
    assert result["deleted"] == 0
    assert result["ads_found"] == 0
    assert bot.deleted == []


def test_clean_subscription_question_is_tracked_but_never_deleted():
    """截图原文“怎么订阅”即使被追踪，score=0 也必须安全跳过。"""
    db = _make_db()
    detector = AdDetector(config={}, db=db)
    detector.track_suspicious_user(
        user_id=8766496147,
        msg_id=61890,
        chat_id=-1001,
        text="怎么订阅",
        score=0,
        is_ad=False,
    )
    bot = _ProtectedContentBot()

    result = _scan(detector, bot, start=61800, end=61900)

    assert result["scanned"] == 1
    assert result["skipped"] == 1
    assert result["ads_found"] == 0
    assert result["deleted"] == 0
    assert bot.deleted == []
    assert result["details"][0]["reason"] == "unconfirmed_ad_evidence"

    stored = db.conn.execute(
        "SELECT messages FROM ad_suspicious_users WHERE user_id=?",
        (8766496147,),
    ).fetchone()
    assert json.loads(stored[0])[0]["is_ad"] is False


def test_explicit_confirmed_ad_can_still_be_deleted():
    """显式确认的广告保留正常追溯删除能力。"""
    detector = AdDetector(config={}, db=_make_db())
    detector.track_suspicious_user(
        user_id=123,
        msg_id=88,
        chat_id=-1001,
        text="加我微信日赚千元",
        score=0,
        is_ad=True,
        direct_message_is_ad=True,
    )
    bot = _ProtectedContentBot()

    result = _scan(detector, bot, start=80, end=90, deletion_enabled=False)

    assert result["ads_found"] == 1
    assert result["deleted"] == 1
    assert bot.deleted == [(-1001, 88)]


def test_legacy_high_score_ad_can_still_be_deleted():
    """旧记录没有 is_ad 字段时，单条评分达到阈值仍视为明确证据。"""
    db = _make_db()
    detector = AdDetector(config={}, db=db)
    detector.track_suspicious_user(
        user_id=456,
        msg_id=99,
        chat_id=-1001,
        text="加我微信",
        score=3,
        direct_message_score=3,
    )
    messages = json.loads(
        db.conn.execute(
            "SELECT messages FROM ad_suspicious_users WHERE user_id=?",
            (456,),
        ).fetchone()[0]
    )
    messages[0].pop("is_ad", None)
    db.conn.execute(
        "UPDATE ad_suspicious_users SET messages=? WHERE user_id=?",
        (json.dumps(messages, ensure_ascii=False), 456),
    )
    db.conn.commit()
    detector.suspicious_users["456"]["messages"][0].pop("is_ad", None)
    bot = _ProtectedContentBot()

    result = _scan(detector, bot, start=90, end=100)

    assert result["ads_found"] == 1
    assert result["deleted"] == 1
    assert bot.deleted == [(-1001, 99)]


def test_already_absent_confirmed_ad_is_resolved_not_failed():
    detector = AdDetector(config={}, db=_make_db())
    detector.track_suspicious_user(
        user_id=789,
        msg_id=77,
        chat_id=-1001,
        text="广告",
        score=3,
        direct_message_score=3,
    )
    result = _scan(detector, _AlreadyAbsentBot(), start=70, end=80, deletion_enabled=False)

    assert result["ads_found"] == 1
    assert result["deleted"] == 0
    assert result["not_found"] == 1
    assert result["failed"] == 0
    assert result["details"][0]["resolved"] is True


def test_latest_snapshot_id_is_read_without_group_probe():
    db = _make_db()
    db.conn.executemany(
        "INSERT INTO message_snapshots(chat_id, msg_id, user_id, text, ts) VALUES (?,?,?,?,?)",
        [
            (-1001, 10, 1, "a", 1),
            (-1001, 18, 2, "b", 2),
            (-2002, 30, 3, "c", 3),
        ],
    )
    db.conn.commit()

    assert _get_latest_snapshot_message_id(db, -1001) == 18
    assert _get_latest_snapshot_message_id(db, -3003) == 0
