# -*- coding: utf-8 -*-
"""
[Codex] 广告历史消息清理回归测试。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeBot:
    def __init__(self, fail_msg_ids=None):
        self.fail_msg_ids = set(fail_msg_ids or [])
        self.deleted = []
        self.restricted = []
        self._me = type("Me", (), {"id": 7})()

    def delete_message(self, chat_id, msg_id):
        if msg_id in self.fail_msg_ids:
            raise RuntimeError("temporary telegram delete failure")
        self.deleted.append((chat_id, msg_id))
        return True

    def restrict_chat_member(self, chat_id, uid, **kwargs):
        self.restricted.append((chat_id, uid, kwargs))
        return True

    def get_me(self):
        return self._me


class _FakeConn:
    def execute(self, *args, **kwargs):
        return []

    def commit(self):
        pass


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []
        self.marked = []
        self.ad_marked = []

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_ad_messages(self, uid, chat_id=None, limit=2000):
        return [
            {"chat_id": -1001, "msg_id": 10, "deleted": 0},
            {"chat_id": -1001, "msg_id": 11, "deleted": 1},
            {"chat_id": -1001, "msg_id": 12, "deleted": 0},
        ]

    def mark_message_deleted(self, chat_id, msg_id):
        self.marked.append((chat_id, msg_id))
        return True

    def mark_message_ad(self, chat_id, msg_id):
        self.ad_marked.append((chat_id, msg_id))
        return True


def test_cleanup_retries_deleted_marked_rows_and_marks_only_success():
    from modules.ad_enforcement import enforce_ad_user

    bot = _FakeBot(fail_msg_ids={12})
    db = _FakeDB()

    result = enforce_ad_user(
        bot=bot,
        db=db,
        config={"ENABLE_MESSAGE_DELETION": True, "AD_CLEANUP_HISTORY_LIMIT": 2000},
        chat_id=-1001,
        uid=42,
        uname="广告号",
        reason="[Codex] 单测广告",
        current_msg_id=99,
        current_message_is_ad=True,
        notify_admin=False,
    )

    assert result["data"]["deleted_count"] == 3
    assert result["data"]["evidence_persisted"] is True
    assert db.ad_marked == [(-1001, 99)]
    assert bot.deleted == [(-1001, 99), (-1001, 10), (-1001, 11)]
    assert (-1001, 11) in db.marked
    assert (-1001, 12) not in db.marked
