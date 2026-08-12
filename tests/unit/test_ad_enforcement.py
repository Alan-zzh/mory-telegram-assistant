# -*- coding: utf-8 -*-
"""
[Codex] 广告处置策略测试：广告账号不踢人，只永久禁言、删消息、双黑名单。
"""

import os
import sqlite3
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeMessage:
    def __init__(self):
        self.message_id = 66
        self.chat = type("Chat", (), {"id": -1001})()
        self.from_user = type("User", (), {"id": 42, "first_name": "广告号"})()
        self.text = "看我简介"


class _Member:
    status = "member"


class _FakeBot:
    def __init__(self):
        self.deleted = []
        self.restricted = []
        self.sent = []
        self.ban_calls = []
        self.kick_calls = []
        self._me = type("Me", (), {"id": 7})()

    # 模拟真实 bot：get_chat_member 查询成功且为普通成员（非管理）
    def get_chat_member(self, chat_id, uid):
        return _Member()

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


class _FalseDeleteBot(_FakeBot):
    def delete_message(self, chat_id, msg_id):
        return False


class _FalseRestrictBot(_FakeBot):
    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return False


class _FakeConn:
    def __init__(self):
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if sql.lstrip().upper().startswith("SELECT COUNT"):
            return type("Result", (), {"fetchone": lambda self: (0,)})()
        return type("Result", (), {"fetchone": lambda self: None})()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []
        self.user_messages = [
            {"chat_id": -1001, "msg_id": 60, "deleted": 0},
            {"chat_id": -1001, "msg_id": 61, "deleted": 1},
        ]
        self.marked = []
        self.ad_marked = []

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_ad_messages(self, uid, chat_id=None, limit=2000):
        return self.user_messages

    def mark_message_deleted(self, chat_id, msg_id):
        self.marked.append((chat_id, msg_id))
        return True

    def mark_message_ad(self, chat_id, msg_id):
        self.ad_marked.append((chat_id, msg_id))
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
        current_message_is_ad=True,
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
    assert any("INTO blacklist" in sql for sql, _ in db.conn.executed)
    assert any("global_blacklist" in sql for sql, _ in db.conn.executed)
    assert (-1001, 66) in db.marked
    assert (-1001, 60) in db.marked
    assert (-1001, 61) in db.marked
    assert db.ad_marked == [(-1001, 66)]
    assert result["data"]["evidence_persisted"] is True
    assert any(call[0] == 99 for call in bot.sent)
    admin_message = next(call for call in bot.sent if call[0] == 99)
    markup = admin_message[2].get("reply_markup")
    assert markup is not None
    assert markup.keyboard[0][0].text == "一键解封"
    assert markup.keyboard[0][0].callback_data == "ad_unban:42:-1001"


def test_enforce_ad_user_deletes_confirmed_ads_when_general_deletion_disabled():
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
        current_message_is_ad=True,
    )

    assert result["code"] == 200
    assert bot.deleted == [(-1001, 66), (-1001, 60), (-1001, 61)]
    assert len(bot.restricted) == 1
    assert db.ad_marked == [(-1001, 66)]
    assert result["data"]["evidence_persisted"] is True
    assert result["data"]["reactions_cleaned"] is False
    assert any("INTO blacklist" in sql for sql, _ in db.conn.executed)
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


def test_blacklist_reblock_deletes_current_but_does_not_falsify_message_evidence():
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    db.user_messages = []

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": False},
        chat_id=-1001,
        uid=42,
        reason="黑名单拦截",
        current_msg_id=77,
        current_message_is_ad=False,
        notify_admin=False,
    )

    assert bot.deleted == [(-1001, 77)]
    assert db.ad_marked == []
    assert result["data"]["evidence_persisted"] is False


def test_delete_false_never_marks_snapshot_deleted():
    from modules.ad_enforcement import enforce_ad_user

    bot = _FalseDeleteBot()
    db = _FakeDB()
    db.user_messages = []
    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": False},
        chat_id=-1001,
        uid=42,
        current_msg_id=78,
        current_message_is_ad=True,
        notify_admin=False,
    )

    assert result["data"]["deleted_count"] == 0
    assert db.ad_marked == [(-1001, 78)]
    assert db.marked == []


def test_repeated_spam_cleanup_deletes_group_without_ad_punishment():
    from modules.ad_enforcement import delete_repeated_spam_messages

    bot = _FakeBot()
    db = _FakeDB()
    result = delete_repeated_spam_messages(bot, db, [
        {"chat_id": -1001, "msg_id": 10},
        {"chat_id": -1001, "msg_id": 11},
        {"chat_id": -1001, "msg_id": 12},
    ])

    assert result["handled"] is True
    assert result["deleted_count"] == 3
    assert result["failed_count"] == 0
    assert bot.deleted == [(-1001, 10), (-1001, 11), (-1001, 12)]
    assert db.marked == [(-1001, 10), (-1001, 11), (-1001, 12)]
    assert db.ad_marked == []
    assert bot.restricted == []
    assert db.blacklist == []


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
    assert result["data"]["persistence_verified"] is True
    assert result["data"]["permission_verified"] is True
    assert ad_detector.cleared == [42]


def test_restore_ad_user_fails_closed_when_telegram_restore_returns_false():
    from modules.ad_enforcement import restore_ad_user

    result = restore_ad_user(
        bot=_FalseRestrictBot(),
        db=_FakeDB(),
        config={},
        chat_id=-1001,
        uid=42,
        actor_id=99,
    )

    assert result["code"] == 500
    assert result["msg"] == "restore_not_verified"
    assert result["data"]["permission_verified"] is False


def test_ad_state_transaction_rolls_back_all_tables_on_partial_failure():
    from modules.ad_enforcement import _persist_ad_state

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE mute_records (uid INTEGER PRIMARY KEY, chat_id INTEGER, mute_until INTEGER, reason TEXT);
        CREATE TABLE global_blacklist (user_id INTEGER PRIMARY KEY, reason TEXT, added_by INTEGER, added_at TEXT);
        CREATE TABLE blacklist (uid INTEGER PRIMARY KEY, reason TEXT, date INTEGER);
        CREATE TRIGGER reject_local_blacklist BEFORE INSERT ON blacklist
        BEGIN SELECT RAISE(ABORT, 'forced local blacklist failure'); END;
        """
    )
    db = type("Db", (), {"conn": conn, "lock": threading.RLock()})()

    assert _persist_ad_state(_FakeBot(), db, -1001, 42, "test", muted=True) is False
    assert conn.execute("SELECT COUNT(*) FROM mute_records").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM global_blacklist").fetchone() == (0,)
    assert conn.execute("SELECT COUNT(*) FROM blacklist").fetchone() == (0,)


def test_ungban_never_falls_back_to_unverified_local_delete(monkeypatch):
    from modules.global_blacklist import handle_ungban

    class Db:
        removed = []

        @staticmethod
        def is_blacklisted(_uid):
            return True

        @classmethod
        def blacklist_remove(cls, uid):
            cls.removed.append(uid)

    bot = _ReplyBot()
    message = SimpleNamespace(
        text="/ungban 42",
        from_user=SimpleNamespace(id=99),
        chat=SimpleNamespace(id=-1001),
        reply_to_message=None,
        entities=[],
    )
    monkeypatch.setattr(
        "modules.ad_enforcement.restore_ad_user",
        lambda **_kwargs: {"code": 500, "data": {"blacklist_removed": True}},
    )

    handle_ungban(bot, message, {"ADMIN_ID": 99}, Db())

    assert Db.removed == []
    assert any("未完全成功" in reply for reply in bot.replies)


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
        return super().execute(sql, params)


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


class _AdminMember:
    status = "administrator"


class _AdminBot(_FakeBot):
    def get_chat_member(self, chat_id, uid):
        return _AdminMember()


def test_enforce_ad_user_skips_admin_and_creator_entirely():
    from modules.ad_enforcement import enforce_ad_user

    bot = _AdminBot()
    db = _FakeDB()

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "ADMIN_ID": 99},
        chat_id=-1001,
        uid=42,
        uname="管理",
        reason="资料广告检测",
        current_msg_id=66,
        current_message_is_ad=True,
        notify_admin=True,
    )

    assert result["code"] == 200
    assert result["data"]["skipped_reason"] == "admin_or_creator"
    assert bot.deleted == []
    assert bot.restricted == []
    assert db.blacklist == []
    assert db.ad_marked == []
    assert db.marked == []
    assert not any(call[0] == 99 for call in bot.sent)
    assert bot.ban_calls == []
    assert bot.kick_calls == []


# ──【v5.38.22 阶段3】任务14/15/16/17 新增单测────────────────────


def test_enforce_ad_user_skips_config_admin_before_network_query():
    """任务14：ADMIN_IDS 命中 → 零网络前置豁免：不删消息/不禁言/不写黑名单。

    使用无 get_chat_member 方法的 _FakeBot：若配置豁免未前置，会 AttributeError 失败。
    """
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "ADMIN_IDS": [42], "ADMIN_ID": 99},
        chat_id=-1001,
        uid=42,
        uname="管理员",
        reason="资料广告检测",
        current_msg_id=66,
        current_message_is_ad=True,
        notify_admin=True,
    )

    assert result["code"] == 200
    assert result["msg"] == "skipped_admin"
    assert result["data"]["skipped_reason"] == "admin_or_creator"
    assert bot.deleted == []
    assert bot.restricted == []
    assert db.blacklist == []
    assert db.ad_marked == []
    assert db.marked == []
    assert not any(call[0] == 99 for call in bot.sent)


def test_enforce_ad_user_skips_config_admin_id_single_value():
    """任务14：ADMIN_ID 单值命中同样豁免（_admin_ids 合并 ADMIN_IDS/ADMIN_ID）。"""
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()
    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ADMIN_ID": 42},
        chat_id=-1001,
        uid=42,
        reason="资料广告检测",
        current_msg_id=66,
        current_message_is_ad=True,
    )

    assert result["data"]["skipped_reason"] == "admin_or_creator"
    assert bot.deleted == []
    assert bot.restricted == []
    assert db.blacklist == []
    assert db.ad_marked == []
    assert db.marked == []


def test_enforce_ad_user_skips_irreversible_when_admin_query_fails(monkeypatch):
    """任务15：get_chat_member 抛异常 → 保留证据+通知人工复核，跳过不可逆惩罚。"""
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot()
    db = _FakeDB()

    def _query_failed(chat_id, uid):
        raise Exception("network down")

    monkeypatch.setattr(bot, "get_chat_member", _query_failed)

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "ADMIN_ID": 99},
        chat_id=-1001,
        uid=42,
        uname="可疑号",
        reason="广告检测",
        current_msg_id=66,
        current_message_is_ad=True,
        notify_admin=True,
    )

    assert result["code"] == 200
    assert result["msg"] == "skipped_admin"
    assert result["data"]["skipped_reason"] == "admin_query_failed"
    # 证据持久化动作已执行（审计真值写入 db），返回结构同豁免分支（evidence_persisted=False）
    assert db.ad_marked == [(-1001, 66)]
    # 不可逆惩罚全部跳过
    assert bot.deleted == []
    assert bot.restricted == []
    assert db.blacklist == []
    assert db.marked == []
    # 通知管理员人工复核
    assert any(call[0] == 99 for call in bot.sent)
    assert bot.ban_calls == []
    assert bot.kick_calls == []


class _PendingDB:
    """启动追溯测试：内存 sqlite，模拟 message_snapshots 表。"""

    def __init__(self):
        import sqlite3

        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.executescript(
            """
            CREATE TABLE message_snapshots (
                chat_id INTEGER, msg_id INTEGER, user_id INTEGER, text TEXT, ts INTEGER,
                is_ad INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
                PRIMARY KEY(chat_id, msg_id)
            );
            """
        )
        self.conn.commit()

    def mark_message_ad(self, chat_id, msg_id):
        cur = self.conn.execute(
            "UPDATE message_snapshots SET is_ad=1 WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_message_deleted(self, chat_id, msg_id):
        cur = self.conn.execute(
            "UPDATE message_snapshots SET deleted=1 WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_user_ad_messages(self, uid, chat_id=None, limit=2000):
        return []

    def blacklist_add(self, uid, reason):
        pass


class _PendingBot:
    """启动追溯测试 bot：记录删除/禁言/报告发送。"""

    def __init__(self):
        self.deleted = []
        self.restricted = []
        self.sent = []

    def delete_message(self, chat_id, msg_id):
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid))
        return True

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def test_startup_traceback_skipped_admin_not_counted_as_failed():
    """任务16：启动追溯命中配置管理员 → 不计 total_failed，报告展示跳过计数。"""
    from datetime import datetime, timezone

    from modules.ad_detector import AdDetector

    db = _PendingDB()
    detector = AdDetector(config={}, db=db)
    detector.suspicious_users["42"] = {
        "score": 9,
        "first_seen": datetime.now(timezone.utc),
        "messages": [
            {"chat_id": -1001, "msg_id": 10, "score": 3, "direct_message_is_ad": True},
        ],
    }
    bot = _PendingBot()

    detector.process_pending_bans(bot, {"ADMIN_ID": 99, "ADMIN_IDS": [42]})

    # 配置管理员豁免：未被禁言、不计入禁言失败
    assert bot.restricted == []
    report_text = next(text for cid, text in bot.sent if cid == 99)
    assert "禁言失败：0人" in report_text
    assert "跳过管理员/查询失败：1人" in report_text
    # 视为正常跳过（非失败），追踪被清理而非保留重试
    assert "42" not in detector.suspicious_users


def test_admin_join_skips_profile_ad_detection(monkeypatch):
    """任务17：管理员入群 → 检测前置豁免，detect_profile_ad_signal 不被调用。"""
    from types import SimpleNamespace

    from core import message_dispatcher
    from core.handlers import member_handlers
    from modules import ad_profile_signals, anti_raid, emoji_mask_detector, federation, spam_watch

    bot = _FakeBot()
    user = SimpleNamespace(id=42, first_name="管理员", last_name="")
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        new_chat_members=[user],
        from_user=user,
    )
    profile_calls = []

    monkeypatch.setattr(anti_raid, "check_raid", lambda *args, **kwargs: False)
    monkeypatch.setattr(spam_watch, "check_user_spam", lambda *args, **kwargs: False)
    monkeypatch.setattr(federation, "execute_fban_on_join", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        emoji_mask_detector, "check_emoji_mask_in_username", lambda *args, **kwargs: (False, "")
    )
    # 管理员入群：member_handlers 检测前豁免返回 True
    monkeypatch.setattr(member_handlers, "_is_member_ad_exempt", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        ad_profile_signals,
        "detect_profile_ad_signal",
        lambda *args, **kwargs: profile_calls.append(args) or {"is_ad": True, "score": 3, "reason": "广告"},
    )

    message_dispatcher._handle_new_chat_members(bot, message, {}, object(), None)

    # 豁免生效：资料检测未被调用，也未触发任何处置
    assert profile_calls == []
    assert bot.deleted == []
    assert bot.restricted == []
