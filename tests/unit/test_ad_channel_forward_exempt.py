# -*- coding: utf-8 -*-
"""
频道转发消息广告检测豁免测试

测试场景：
1. 频道转发消息应跳过广告检测
2. 配置开关 AD_EXEMPT_CHANNEL_FORWARDS 控制豁免行为
3. 非频道转发消息应正常进行广告检测
"""

import os
import sys

import pytest

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

    def get_chat_member(self, chat_id, uid):
        return type("Member", (), {"status": "member"})()

    def get_chat(self, user_id):
        return type("Chat", (), {"bio": ""})()


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
        return False

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_undeleted_messages(self, uid, chat_id=None, limit=2000):
        return []

    def mark_message_deleted(self, chat_id, msg_id):
        self.marked.append((chat_id, msg_id))
        return True

    def upsert_group_member(self, uid, chat_id, username, display_name, bio, role):
        pass


class _FakeAdDetector:
    def __init__(self):
        self.detect_calls = []

    def detect(self, username, msg, user_id, bot, bio, message_meta, chat_id, message):
        self.detect_calls.append({
            "username": username,
            "msg": msg,
            "user_id": user_id,
            "message_meta": message_meta,
        })
        return {"is_ad": False, "score": 0}

    def clear_user_tracking(self, uid):
        pass

    def track_suspicious_user(self, user_id: int, msg_id: int, chat_id: int, text: str, score: int) -> dict:
        return {"action": "none"}

    def check_consecutive_patterns(self, user_id: int, chat_id: int, bot=None) -> dict:
        return {"is_spam": False, "reason": "", "score": 0, "messages": []}


class _FakeKeywordManager:
    def get_ad_keywords(self):
        return []


def _create_dctx_with_channel_forward(config_overrides=None):
    """创建带有频道转发消息的 dctx"""
    bot = _FakeBot()
    db = _FakeDB()
    ad_detector = _FakeAdDetector()
    keyword_manager = _FakeKeywordManager()

    config = {
        "ENABLE_MESSAGE_DELETION": True,
        "AD_CLEANUP_HISTORY_LIMIT": 2000,
        "AD_WHITELIST": {"user_ids": []},
        "AD_EXEMPT_CHANNEL_FORWARDS": True,
    }
    if config_overrides:
        config.update(config_overrides)

    ctx = type("Ctx", (), {
        "bot": bot,
        "db": db,
        "config": config,
        "ad_detector": ad_detector,
        "keyword_manager": keyword_manager,
    })()

    # 创建频道转发消息
    forward_origin = type("ForwardOrigin", (), {"type": "channel"})()
    forward_from_chat = type("ForwardFromChat", (), {"type": "channel"})()
    msg = type("Msg", (), {
        "message_id": 99,
        "from_user": type("User", (), {
            "id": 123,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
            "is_bot": False,
        })(),
        "chat": type("Chat", (), {"id": -1001})(),
        "text": "测试消息",
        "forward_origin": forward_origin,
        "forward_from_chat": forward_from_chat,
        "forward_date": None,
        "photo": None,
        "sticker": None,
        "media_group_id": None,
        "web_page": None,
        "entities": None,
    })()

    dctx = type("Dctx", (), {
        "ctx": ctx,
        "uid": 123,
        "uname": "Test User",
        "chat_id": -1001,
        "msg": msg,
        "text": "测试消息",
        "is_group": True,
        "is_priv": False,
    })()

    return dctx, ad_detector


def _create_dctx_without_channel_forward(config_overrides=None):
    """创建不带频道转发消息的 dctx"""
    bot = _FakeBot()
    db = _FakeDB()
    ad_detector = _FakeAdDetector()
    keyword_manager = _FakeKeywordManager()

    config = {
        "ENABLE_MESSAGE_DELETION": True,
        "AD_CLEANUP_HISTORY_LIMIT": 2000,
        "AD_WHITELIST": {"user_ids": []},
        "AD_EXEMPT_CHANNEL_FORWARDS": True,
    }
    if config_overrides:
        config.update(config_overrides)

    ctx = type("Ctx", (), {
        "bot": bot,
        "db": db,
        "config": config,
        "ad_detector": ad_detector,
        "keyword_manager": keyword_manager,
    })()

    # 创建普通消息（非频道转发）
    msg = type("Msg", (), {
        "message_id": 99,
        "from_user": type("User", (), {
            "id": 123,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
            "is_bot": False,
        })(),
        "chat": type("Chat", (), {"id": -1001})(),
        "text": "测试消息",
        "forward_origin": None,
        "forward_from_chat": None,
        "forward_date": None,
        "photo": None,
        "sticker": None,
        "media_group_id": None,
        "web_page": None,
        "entities": None,
    })()

    dctx = type("Dctx", (), {
        "ctx": ctx,
        "uid": 123,
        "uname": "Test User",
        "chat_id": -1001,
        "msg": msg,
        "text": "测试消息",
        "is_group": True,
        "is_priv": False,
    })()

    return dctx, ad_detector


def test_channel_forward_message_skips_ad_detection():
    """测试：频道转发消息应跳过广告检测"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_with_channel_forward()
    result = check_ad_detection(dctx)

    # 应该返回 False（跳过广告检测）
    assert result is False
    # 广告检测不应该被调用
    assert len(ad_detector.detect_calls) == 0


def test_non_channel_forward_message_runs_ad_detection():
    """测试：非频道转发消息应正常进行广告检测"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_without_channel_forward()
    result = check_ad_detection(dctx)

    # 广告检测应该被调用
    assert len(ad_detector.detect_calls) == 1


def test_channel_forward_exempt_disabled():
    """测试：关闭频道转发豁免时，频道转发消息应进行广告检测"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_with_channel_forward(
        config_overrides={"AD_EXEMPT_CHANNEL_FORWARDS": False}
    )
    result = check_ad_detection(dctx)

    # 广告检测应该被调用
    assert len(ad_detector.detect_calls) == 1


def test_channel_forward_exempt_default_enabled():
    """测试：默认配置下，频道转发消息应跳过广告检测"""
    from core.handlers.security_handlers import check_ad_detection

    # 不传入 AD_EXEMPT_CHANNEL_FORWARDS 配置，使用默认值 True
    dctx, ad_detector = _create_dctx_with_channel_forward(
        config_overrides={"AD_EXEMPT_CHANNEL_FORWARDS": True}
    )
    result = check_ad_detection(dctx)

    # 应该返回 False（跳过广告检测）
    assert result is False
    # 广告检测不应该被调用
    assert len(ad_detector.detect_calls) == 0


def test_lottery_ad_first_message_runs_unified_enforcement(monkeypatch):
    """生产漏判原文首条命中后必须直接进入统一处置，不依赖累计或重复消息。"""
    from core.handlers.security_handlers import check_ad_detection
    from modules.ad_detector import AdDetector

    dctx, _ = _create_dctx_without_channel_forward()
    dctx.text = "港澳1-49特码有量，有收的庄吗？"
    dctx.msg.text = dctx.text
    dctx.msg.from_user.first_name = "财神"
    dctx.uname = "财神"

    detector = AdDetector(config=dctx.ctx.config, db=dctx.ctx.db)
    monkeypatch.setattr(detector, "_check_cas", lambda _uid: (False, ""))
    monkeypatch.setattr(detector, "_check_spb", lambda _uid: (0.0, False))
    dctx.ctx.ad_detector = detector

    handled = check_ad_detection(dctx)

    assert handled is True
    assert dctx.ctx.bot.deleted == [(-1001, 99)]
    assert len(dctx.ctx.bot.restricted) == 1
    assert dctx.ctx.db.blacklist
    assert detector.get_user_tracking(dctx.uid)["message_count"] == 0
