# -*- coding: utf-8 -*-
"""
[Codex] P1 黑名单旧入口回归测试：不能只 return True，必须统一处置并清理消息。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeBot:
    def __init__(self):
        self.deleted = []
        self.restricted = []
        self._me = type("Me", (), {"id": 7})()

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True

    def get_me(self):
        return self._me


class _FakeConn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return []

    def commit(self):
        pass


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []
        self.marked = []

    def is_blacklisted(self, uid):
        return uid == 42

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_undeleted_messages(self, uid, chat_id=None, limit=2000):
        return [
            {"chat_id": -1001, "msg_id": 10, "deleted": 0},
            {"chat_id": -1001, "msg_id": 11, "deleted": 1},
        ]

    def mark_message_deleted(self, chat_id, msg_id):
        self.marked.append((chat_id, msg_id))
        return True


def test_check_blacklist_uses_unified_enforcement_and_cleans_history():
    from core.handlers.security_handlers import check_blacklist

    bot = _FakeBot()
    db = _FakeDB()
    msg = type("Msg", (), {"message_id": 99})()
    ctx = type("Ctx", (), {
        "bot": bot,
        "db": db,
        "config": {"ENABLE_MESSAGE_DELETION": True, "AD_CLEANUP_HISTORY_LIMIT": 2000},
    })()
    dctx = type("Dctx", (), {
        "ctx": ctx,
        "uid": 42,
        "uname": "广告号",
        "chat_id": -1001,
        "msg": msg,
        "is_group": True,
    })()

    assert check_blacklist(dctx) is True
    assert bot.deleted == [(-1001, 99), (-1001, 10), (-1001, 11)]
    assert len(bot.restricted) == 1
    assert db.blacklist == [(42, "黑名单拦截:广告号")]
    assert (-1001, 99) in db.marked
    assert any("global_blacklist" in sql for sql, _ in db.conn.executed)
