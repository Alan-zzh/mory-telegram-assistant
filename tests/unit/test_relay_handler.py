# -*- coding: utf-8 -*-
"""[Codex] 私聊中继必须支持管理员直接回复转发消息。"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeForwarded:
    def __init__(self, message_id):
        self.message_id = message_id


class _FakeBot:
    def __init__(self):
        self.forward_calls = []
        self.send_calls = []
        self.copy_calls = []

    def forward_message(self, admin_id, chat_id, message_id, disable_notification=True):
        self.forward_calls.append((admin_id, chat_id, message_id, disable_notification))
        return _FakeForwarded(9001)

    def send_message(self, chat_id, text, parse_mode=None):
        self.send_calls.append((chat_id, text, parse_mode))
        return _FakeForwarded(9002)

    def copy_message(self, chat_id, from_chat_id, message_id, caption=None):
        self.copy_calls.append((chat_id, from_chat_id, message_id, caption))
        return _FakeForwarded(9003)


class _FakeDB:
    def __init__(self):
        self.sessions = []
        self.lookup = None

    def save_session(self, **kwargs):
        self.sessions.append(kwargs)
        return len(self.sessions)

    def find_by_admin_msg(self, admin_chat_id, admin_msg_id):
        return self.lookup


class _FakeUser:
    def __init__(self, uid, name):
        self.id = uid
        self.first_name = name


class _FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class _FakeMessage:
    def __init__(self, uid=123, name="测试用户", chat_id=123, message_id=456, text="你好", reply_to_message=None, content_type="photo", caption=None):
        self.from_user = _FakeUser(uid, name)
        self.chat = _FakeChat(chat_id)
        self.message_id = message_id
        self.text = text
        self.reply_to_message = reply_to_message
        self.content_type = content_type
        self.caption = caption


def test_relay_original_message_to_admin_saves_session():
    from core.handlers.relay_handler import relay_original_message_to_admin

    bot = _FakeBot()
    db = _FakeDB()
    cfg = {"ADMIN_ID": 777}
    message = _FakeMessage()

    ok = relay_original_message_to_admin(bot, db, cfg, message, source_type="private", note="🖼️ 私聊图片")

    assert ok is True
    assert bot.forward_calls == [(777, 123, 456, True)]
    assert len(db.sessions) == 1
    assert db.sessions[0]["admin_msg_id"] == 9001
    assert db.sessions[0]["user_chat_id"] == 123


def test_handle_admin_reply_routes_back_to_user():
    from core.handlers.relay_handler import handle_admin_reply

    bot = _FakeBot()
    db = _FakeDB()
    db.lookup = {"user_id": 123, "user_chat_id": 123, "source_type": "private"}
    cfg = {"ADMIN_ID": 777, "ADMIN_IDS": [777]}
    reply_target = _FakeForwarded(9001)
    admin_msg = _FakeMessage(uid=777, name="管理员", chat_id=777, message_id=999, text="收到", reply_to_message=reply_target)

    ok = handle_admin_reply(bot, db, cfg, admin_msg)

    assert ok is True
    assert bot.send_calls[0][0] == 123
    assert bot.send_calls[0][1] == "[管理员回复] 收到"


def test_handle_admin_reply_copies_media_back_to_user():
    from core.handlers.relay_handler import handle_admin_reply

    bot = _FakeBot()
    db = _FakeDB()
    db.lookup = {"user_id": 123, "user_chat_id": 123, "source_type": "private"}
    cfg = {"ADMIN_ID": 777, "ADMIN_IDS": [777]}
    reply_target = _FakeForwarded(9001)
    admin_msg = _FakeMessage(
        uid=777,
        name="管理员",
        chat_id=777,
        message_id=1001,
        text="",
        reply_to_message=reply_target,
        content_type="photo",
        caption="这是图片说明",
    )

    ok = handle_admin_reply(bot, db, cfg, admin_msg)

    assert ok is True
    assert bot.copy_calls[0] == (123, 777, 1001, "[管理员回复] 这是图片说明")
