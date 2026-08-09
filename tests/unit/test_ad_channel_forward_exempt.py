# -*- coding: utf-8 -*-
"""
频道转发消息广告检测测试

测试场景（v5.38.29 变更）：
1. 频道转发消息应正常进行广告检测（不再豁免）
2. 非频道转发消息应正常进行广告检测
3. AD_EXEMPT_CHANNEL_FORWARDS 配置已废弃，频道转发不再豁免
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

    def track_suspicious_user(self, user_id: int, msg_id: int, chat_id: int, text: str, score: int, is_ad: bool = False, **kwargs) -> dict:
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


def test_channel_forward_message_runs_ad_detection():
    """测试：频道转发消息应正常进行广告检测（v5.38.29 不再豁免）"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_with_channel_forward()
    result = check_ad_detection(dctx)

    # 广告检测应该被调用（频道转发不再豁免）
    assert len(ad_detector.detect_calls) == 1


def test_non_channel_forward_message_runs_ad_detection():
    """测试：非频道转发消息应正常进行广告检测"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_without_channel_forward()
    result = check_ad_detection(dctx)

    # 广告检测应该被调用
    assert len(ad_detector.detect_calls) == 1


def test_channel_forward_exempt_config_ignored():
    """测试：AD_EXEMPT_CHANNEL_FORWARDS 配置已废弃，不再影响行为"""
    from core.handlers.security_handlers import check_ad_detection

    # 即使配置 AD_EXEMPT_CHANNEL_FORWARDS=True，频道转发仍应检测
    dctx, ad_detector = _create_dctx_with_channel_forward(
        config_overrides={"AD_EXEMPT_CHANNEL_FORWARDS": True}
    )
    result = check_ad_detection(dctx)

    # 广告检测应该被调用（配置已废弃）
    assert len(ad_detector.detect_calls) == 1


def test_configured_own_channel_forward_skips_ad_detection():
    """只有 CHANNEL_IDS 中的自有频道可信，不能把 Telegram 自动转发系统号当广告。"""
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_with_channel_forward(
        config_overrides={"CHANNEL_IDS": [{"id": -10099, "name": "自有频道"}]}
    )
    dctx.msg.chat.type = "supergroup"
    dctx.msg.sender_chat = type("SenderChat", (), {"id": -10099, "type": "channel"})()

    assert check_ad_detection(dctx) is False
    assert ad_detector.detect_calls == []


def test_other_channel_forward_still_runs_ad_detection():
    from core.handlers.security_handlers import check_ad_detection

    dctx, ad_detector = _create_dctx_with_channel_forward(
        config_overrides={"CHANNEL_IDS": [{"id": -10099, "name": "自有频道"}]}
    )
    dctx.msg.chat.type = "supergroup"
    dctx.msg.sender_chat = type("SenderChat", (), {"id": -20088, "type": "channel"})()

    assert check_ad_detection(dctx) is False
    assert len(ad_detector.detect_calls) == 1


@pytest.mark.parametrize(
    "text",
    [
        "新澳门六叔公单子有量，有庄收吗？",
        "新澳六彩盒单子有量找庄合作",
    ],
)
def test_lottery_ad_first_message_runs_unified_enforcement(monkeypatch, text):
    """两条生产漏判原文首条都必须进入删除、永久限制和双黑名单统一处置。"""
    from core.handlers.security_handlers import check_ad_detection
    from modules.ad_detector import AdDetector

    dctx, _ = _create_dctx_without_channel_forward()
    dctx.text = text
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
    assert any("global_blacklist" in sql for sql, _ in dctx.ctx.db.conn.executed)
    assert detector.get_user_tracking(dctx.uid)["message_count"] == 0


def test_daily_income_o_obfuscation_runs_unified_enforcement(monkeypatch):
    """“一日 9Oo+”首条必须删除、永久禁言并写黑名单，不能落入后续回复。"""
    from core.handlers.security_handlers import check_ad_detection
    from modules.ad_detector import AdDetector

    dctx, _ = _create_dctx_without_channel_forward()
    dctx.text = "一日 9Oo+"
    dctx.msg.text = dctx.text
    dctx.msg.from_user.first_name = "Emilia"
    dctx.msg.from_user.last_name = "Potts"
    dctx.uname = "Emilia Potts"

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


@pytest.mark.parametrize(
    "text",
    [
        "日1入 lOOO+",
        "加1微x信",
        "兼1职 日结 500元",
        "特1码有量，找庄",
        "裸1聊",
        "跑1分 接单返佣",
    ],
)
def test_obfuscated_ad_families_run_unified_enforcement(monkeypatch, text):
    """六类拆字广告首条都必须复用删除、永久禁言和黑名单统一处置链。"""
    from core.handlers.security_handlers import check_ad_detection
    from modules.ad_detector import AdDetector

    dctx, _ = _create_dctx_without_channel_forward()
    dctx.text = text
    dctx.msg.text = text
    dctx.msg.from_user.first_name = "广告变体"
    dctx.uname = "广告变体"

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
