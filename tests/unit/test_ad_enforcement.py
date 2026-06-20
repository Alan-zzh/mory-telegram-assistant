# -*- coding: utf-8 -*-
"""
[Codex] 广告处置策略测试：广告账号不踢人，只永久禁言、删消息、双黑名单。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeMessage:
    def __init__(self):
        self.message_id = 66
        self.chat = type("Chat", (), {"id": -1001})()
        self.from_user = type("User", (), {"id": 42, "first_name": "广告号"})()
        self.text = "看我简介"


class _FakeBot:
    def __init__(self):
        self.deleted = []
        self.restricted = []
        self.sent = []
        self.ban_calls = []
        self.kick_calls = []
        self._me = type("Me", (), {"id": 7})()

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True

    def ban_chat_member(self, *args, **kwargs):
        self.ban_calls.append((args, kwargs))

    def kick_chat_member(self, *args, **kwargs):
        self.kick_calls.append((args, kwargs))

    def get_me(self):
        return self._me

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))


class _FakeConn:
    def __init__(self):
        self.executed = []
        self.commits = 0

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return []

    def commit(self):
        self.commits += 1


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []
        self.user_messages = [
            {"chat_id": -1001, "msg_id": 60, "deleted": 0},
            {"chat_id": -1001, "msg_id": 61, "deleted": 1},
        ]
        self.marked = []

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_messages(self, uid, chat_id=None, limit=100):
        return self.user_messages

    def mark_message_deleted(self, chat_id, msg_id):
        self.marked.append((chat_id, msg_id))
        return True


def test_enforce_ad_user_mutes_deletes_and_never_kicks_or_bans():
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    msg = _FakeMessage()

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "ADMIN_ID": 99},
        chat_id=-1001,
        uid=42,
        uname="广告号",
        reason="[Codex] 单测广告",
        message=msg,
        current_msg_id=66,
        notify_admin=True,
    )

    assert result["code"] == 200
    assert bot.deleted == [(-1001, 66), (-1001, 60), (-1001, 61)]
    assert len(bot.restricted) == 1
    assert bot.restricted[0][0:2] == (-1001, 42)
    assert bot.restricted[0][2]["permissions"]["can_react_to_messages"] is False
    assert bot.restricted[0][2]["permissions"]["can_send_paid_media"] is False
    assert bot.ban_calls == []
    assert bot.kick_calls == []
    assert db.blacklist == [(42, "[Codex] 单测广告")]
    assert any("global_blacklist" in sql for sql, _ in db.conn.executed)
    assert (-1001, 66) in db.marked
    assert (-1001, 60) in db.marked
    assert (-1001, 61) in db.marked
    assert any(call[0] == 99 for call in bot.sent)


def test_enforce_ad_user_keeps_mute_and_blacklist_when_deletion_disabled():
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": False},
        chat_id=-1001,
        uid=42,
        uname="广告号",
        reason="[Codex] 删除关闭",
        current_msg_id=66,
    )

    assert result["code"] == 200
    assert bot.deleted == []
    assert len(bot.restricted) == 1
    assert result["data"]["reactions_cleaned"] is False
    assert db.blacklist == [(42, "[Codex] 删除关闭")]
    assert bot.ban_calls == []
    assert bot.kick_calls == []


def test_enforce_ad_user_reports_reaction_cleanup(monkeypatch):
    from modules import ad_enforcement
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    monkeypatch.setattr(ad_enforcement, "delete_all_message_reactions_compat", lambda *args, **kwargs: True)

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": False, "AD_CLEANUP_REACTIONS": True},
        chat_id=-1001,
        uid=42,
        uname="广告号",
        reason="[Codex] 清反应",
        current_msg_id=66,
    )

    assert result["data"]["reactions_cleaned"] is True
