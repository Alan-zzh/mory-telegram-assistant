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
    admin_message = next(call for call in bot.sent if call[0] == 99)
    markup = admin_message[2].get("reply_markup")
    assert markup is not None
    assert markup.keyboard[0][0].text == "一键解封"
    assert markup.keyboard[0][0].callback_data == "ad_unban:42:-1001"


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


def test_restore_ad_user_removes_blacklists_and_restores_permissions():
    from modules.ad_enforcement import restore_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    ad_detector = type("AdDetector", (), {"cleared": [], "clear_user_tracking": lambda self, uid: self.cleared.append(uid)})()

    result = restore_ad_user(
        bot=bot,
        db=db,
        config={},
        chat_id=-1001,
        uid=42,
        actor_id=99,
        ad_detector=ad_detector,
    )

    assert result["code"] == 200
    executed_sql = [sql for sql, _ in db.conn.executed]
    assert any("DELETE FROM blacklist" in sql for sql in executed_sql)
    assert any("DELETE FROM global_blacklist" in sql for sql in executed_sql)
    assert any("DELETE FROM mute_records" in sql for sql in executed_sql)
    assert bot.restricted[-1][0:2] == (-1001, 42)
    permissions = bot.restricted[-1][2]["permissions"]
    assert permissions["can_send_messages"] is True
    assert permissions["can_react_to_messages"] is True
    assert result["data"]["tracking_cleared"] is True
    assert ad_detector.cleared == [42]


class _FetchOneResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row else []


class _LookupConn(_FakeConn):
    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "FROM group_members" in sql and params == ("knownuser",):
            return _FetchOneResult((4242,))
        if "display_name" in sql and params and not str(params[0]).startswith("%"):
            return _FetchOneResult((8383136504, "mmb3695", "萌萌逼"))
        return _FetchOneResult(None)


class _LookupDB(_FakeDB):
    def __init__(self):
        super().__init__()
        self.conn = _LookupConn()


class _ReplyBot(_FakeBot):
    def __init__(self):
        super().__init__()
        self.replies = []

    def reply_to(self, message, text, **kwargs):
        self.replies.append(text)


def test_handle_unban_command_accepts_numeric_id():
    from modules.ad_enforcement import handle_unban_command

    bot = _ReplyBot()
    db = _LookupDB()
    message = type("Msg", (), {
        "text": "/unban 42",
        "from_user": type("User", (), {"id": 99})(),
        "chat": type("Chat", (), {"id": -1001})(),
        "reply_to_message": None,
    })()

    assert handle_unban_command(bot, message, {"ADMIN_ID": 99}, db) is True
    assert any("已解封" in reply for reply in bot.replies)
    assert any("DELETE FROM global_blacklist" in sql for sql, _ in db.conn.executed)
    assert bot.restricted[-1][0:2] == (-1001, 42)


def test_handle_unban_command_accepts_username_from_group_member_cache():
    from modules.ad_enforcement import handle_unban_command

    bot = _ReplyBot()
    db = _LookupDB()
    message = type("Msg", (), {
        "text": "/unban @knownuser",
        "from_user": type("User", (), {"id": 99})(),
        "chat": type("Chat", (), {"id": -1001})(),
        "reply_to_message": None,
    })()

    assert handle_unban_command(bot, message, {"ADMIN_ID": 99}, db) is True
    assert any("@knownuser" in reply for reply in bot.replies)
    assert bot.restricted[-1][0:2] == (-1001, 4242)


def test_handle_unban_command_accepts_display_name_from_group_member_cache():
    from modules.ad_enforcement import handle_unban_command

    bot = _ReplyBot()
    db = _LookupDB()
    message = type("Msg", (), {
        "text": "/unban 萌萌逼",
        "from_user": type("User", (), {"id": 99})(),
        "chat": type("Chat", (), {"id": 8012433255})(),
        "reply_to_message": None,
    })()

    assert handle_unban_command(bot, message, {"ADMIN_ID": "99", "GROUP_ID": -1001}, db) is True
    assert bot.restricted[-1][0:2] == (-1001, 8383136504)


class _AmbiguousLookupResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _AmbiguousLookupConn(_FakeConn):
    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "FROM group_members" in sql and "display_name" in sql:
            return _AmbiguousLookupResult([
                (8383136504, "mmb3695", "萌萌逼"),
                (5852515255, "D9710", "萌萌逼"),
            ])
        return _AmbiguousLookupResult([])


class _AmbiguousLookupDB(_FakeDB):
    def __init__(self):
        super().__init__()
        self.conn = _AmbiguousLookupConn()


def test_handle_unban_command_refuses_ambiguous_display_name():
    from modules.ad_enforcement import handle_unban_command

    bot = _ReplyBot()
    db = _AmbiguousLookupDB()
    message = type("Msg", (), {
        "text": "/unban 萌萌逼",
        "from_user": type("User", (), {"id": 99})(),
        "chat": type("Chat", (), {"id": 8012433255})(),
        "reply_to_message": None,
    })()

    assert handle_unban_command(bot, message, {"ADMIN_ID": 99, "GROUP_ID": -1001}, db) is True
    assert bot.restricted == []
    assert any("8383136504" in reply and "5852515255" in reply for reply in bot.replies)
