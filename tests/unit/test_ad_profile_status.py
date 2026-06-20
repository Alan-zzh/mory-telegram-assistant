# -*- coding: utf-8 -*-
"""
[Codex] 广告资料状态检测测试：覆盖 Telegram Premium emoji 状态中的看我简介信号。
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeSticker:
    def __init__(self, emoji="", set_name="", custom_emoji_id="status-1", thumbnail=None):
        self.emoji = emoji
        self.set_name = set_name
        self.custom_emoji_id = custom_emoji_id
        self.thumbnail = thumbnail


class _FakeBot:
    def __init__(self, stickers):
        self.stickers = stickers
        self.requested = []
        self.downloaded = []

    def get_custom_emoji_stickers(self, custom_emoji_ids):
        self.requested.append(list(custom_emoji_ids))
        return self.stickers

    def get_file(self, file_id):
        return type("FileInfo", (), {"file_path": f"stickers/{file_id}.webp"})()

    def download_file(self, file_path):
        self.downloaded.append(file_path)
        return b"fake-image"


class _FakeUser:
    def __init__(self, first_name="云间藏诗意", status_id="status-1"):
        self.id = 42
        self.first_name = first_name
        self.last_name = ""
        self.username = ""
        self.emoji_status_custom_emoji_id = status_id


def test_profile_status_metadata_hits_look_profile_pattern():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    result = detect_profile_ad_signal(bot, _FakeUser(), "")

    assert result["is_ad"] is True
    assert "emoji状态" in result["reason"]
    assert bot.requested == [["status-1"]]


def test_profile_status_without_text_only_tracks_suspicious():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakeBot([_FakeSticker(emoji="🐱", set_name="")])
    result = detect_profile_ad_signal(bot, _FakeUser(), "")

    assert result["is_ad"] is False
    assert result["score"] == 1
    assert "自定义emoji状态" in result["reason"]


def test_profile_status_ocr_hits_image_only_look_profile(monkeypatch):
    from modules import ad_profile_signals

    monkeypatch.setattr(ad_profile_signals, "analyze_image", lambda data, prompt, config: "看我简介")
    thumb = type("Thumb", (), {"file_id": "thumb-1"})()
    bot = _FakeBot([_FakeSticker(emoji="🐱", set_name="", thumbnail=thumb)])

    result = ad_profile_signals.detect_profile_ad_signal(bot, _FakeUser(), "", {"MODEL_POOLS": {"vision": [{"name": "qwen-vl"}]}, "API_KEY": "x"})

    assert result["is_ad"] is True
    assert "emoji状态图片OCR" in result["reason"]
    assert bot.downloaded == ["stickers/thumb-1.webp"]


def test_telebot_user_keeps_emoji_status_extra_field():
    from core.telebot_compat import preserve_user_extra_fields
    from telebot import types

    preserve_user_extra_fields()
    user = types.User(42, False, "云间藏诗意", emoji_status_custom_emoji_id="status-1")

    assert user.emoji_status_custom_emoji_id == "status-1"


class _FakeConn:
    def execute(self, *args, **kwargs):
        return []

    def commit(self):
        pass


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []

    def is_blacklisted(self, uid):
        return False

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_undeleted_messages(self, uid, chat_id=None, limit=2000):
        return []

    def mark_message_deleted(self, chat_id, msg_id):
        return True


class _FakeAdDetector:
    def track_suspicious_user(self, *args, **kwargs):
        return {"action": "none", "total_score": 0}


class _FakeShortMessage:
    content_type = "text"
    text = "1"
    message_id = 88
    chat = type("Chat", (), {"id": -1001, "type": "supergroup"})()
    from_user = _FakeUser()


def test_short_message_still_blocks_profile_status_ad():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    bot.deleted = []
    bot.restricted = []
    bot._me = type("Me", (), {"id": 7})()
    bot.get_chat = lambda uid: type("ChatInfo", (), {"bio": ""})()
    bot.get_me = lambda: bot._me
    bot.delete_message = lambda chat_id, msg_id: bot.deleted.append((chat_id, msg_id)) or True
    bot.restrict_chat_member = lambda chat_id, uid, **kwargs: bot.restricted.append((chat_id, uid, kwargs)) or True

    ctx = type("Ctx", (), {
        "bot": bot,
        "db": _FakeDB(),
        "config": {"ENABLE_MESSAGE_DELETION": True},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "1",
        "ctx": ctx,
        "msg": _FakeShortMessage(),
        "uid": 42,
        "uname": "云间藏诗意",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is True
    assert bot.deleted == [(-1001, 88)]
    assert bot.restricted[0][0:2] == (-1001, 42)
