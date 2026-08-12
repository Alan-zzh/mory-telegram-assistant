# -*- coding: utf-8 -*-
"""彩票灰产首条命中必须落到真实 SQLite 的统一处置状态。"""

import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _Bot:
    def __init__(self):
        self.deleted = []
        self.restricted = []

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True

    def get_me(self):
        return SimpleNamespace(id=7)

    def get_chat_member(self, chat_id, uid):
        return SimpleNamespace(status="member")

    def get_chat(self, uid):
        return SimpleNamespace(bio="")


class _SQLiteDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE blacklist (uid INTEGER PRIMARY KEY, reason TEXT);
            CREATE TABLE global_blacklist (
                user_id INTEGER PRIMARY KEY, reason TEXT, added_by INTEGER, added_at TEXT
            );
            CREATE TABLE mute_records (uid INTEGER, chat_id INTEGER, mute_until INTEGER, reason TEXT);
        """)

    def is_blacklisted(self, uid):
        return False

    def blacklist_add(self, uid, reason):
        self.conn.execute("INSERT OR REPLACE INTO blacklist (uid, reason) VALUES (?, ?)", (uid, reason))
        self.conn.commit()

    def get_user_undeleted_messages(self, uid, chat_id=None, limit=2000):
        return []

    def mark_message_deleted(self, chat_id, msg_id):
        return True

    def upsert_group_member(self, *args):
        pass


@pytest.mark.parametrize(
    "text",
    [
        "新澳门六叔公单子有量，有庄收吗？",
        "新澳六彩盒单子有量找庄合作",
        "女大一枚，有户外露出小癖好,露 Q裙 1093995052 可以约哦 BFG",
        "Q裙 1102445053 开课｜00后新下海｜自带科室·配合听话 kwPb",
    ],
)
def test_production_ad_first_message_persists_unified_enforcement_state_in_sqlite(monkeypatch, text):
    """生产广告原文首条：删消息、永久限制、双黑名单，且不遗留追踪记录。"""
    from core.handlers.security_handlers import check_ad_detection
    from modules.ad_detector import AdDetector

    bot = _Bot()
    db = _SQLiteDB()
    uid = 123
    chat_id = -1001
    message = SimpleNamespace(
        message_id=99,
        from_user=SimpleNamespace(
            id=uid, first_name="广告", last_name="账号", username="aduser", is_bot=False,
        ),
        chat=SimpleNamespace(id=chat_id),
        text=text,
        forward_origin=None,
        forward_from_chat=None,
        forward_date=None,
        photo=None,
        sticker=None,
        media_group_id=None,
        web_page=None,
        entities=None,
    )
    detector = AdDetector(config={}, db=db)
    monkeypatch.setattr(detector, "_check_cas", lambda _uid: (False, ""))
    monkeypatch.setattr(detector, "_check_spb", lambda _uid: (0.0, False))
    context = SimpleNamespace(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "AD_WHITELIST": {"user_ids": []}},
        ad_detector=detector,
        keyword_manager=SimpleNamespace(get_ad_keywords=lambda: []),
    )
    dctx = SimpleNamespace(
        ctx=context,
        uid=uid,
        uname="广告账号",
        chat_id=chat_id,
        msg=message,
        text=text,
        is_group=True,
        is_priv=False,
    )

    assert check_ad_detection(dctx) is True
    assert bot.deleted == [(chat_id, 99)]
    assert len(bot.restricted) == 1
    assert db.conn.execute("SELECT uid FROM blacklist WHERE uid=?", (uid,)).fetchone() == (uid,)
    assert db.conn.execute("SELECT user_id FROM global_blacklist WHERE user_id=?", (uid,)).fetchone() == (uid,)
    assert db.conn.execute(
        "SELECT mute_until FROM mute_records WHERE uid=? AND chat_id=?", (uid, chat_id)
    ).fetchone() == (0,)
    assert detector.get_user_tracking(uid)["message_count"] == 0
    assert db.conn.execute("SELECT user_id FROM ad_suspicious_users WHERE user_id=?", (uid,)).fetchone() is None
