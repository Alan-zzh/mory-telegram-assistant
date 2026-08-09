# -*- coding: utf-8 -*-
"""特定词自动回复卡片组件测试。

覆盖：按钮目标解析（规则显式目标绑定 / 未声明随机二选一）、
私聊无按钮红线、Rich/HTML 卡片结构、开关默认关闭、
发送回退链（Rich → HTML → 纯文本）与精准润色 prompt 约束。
"""

from types import SimpleNamespace

from core.auto_reply_card import (
    _AUTO_REPLY_CTA_POOLS,
    build_auto_reply_card,
    is_auto_reply_card_enabled,
    is_rich_message_enabled,
    pick_auto_reply_cta,
)
from core.broadcast_cta import (
    TARGET_CONTACT,
    TARGET_PREVIEW,
    TARGET_SUBSCRIBE,
    _DEFAULT_URLS,
)

_SUBSCRIBE_RULE = {
    "name": "下单咨询",
    "topic": "下单",
    "conversion_target": "subscribe",
    "base_reply": "已了解的话可以直接自助下单。",
}

_CONTACT_RULE = {
    "name": "定制咨询",
    "topic": "定制",
    "conversion_target": "contact",
}

_PREVIEW_RULE = {
    "name": "福利咨询",
    "topic": "福利",
    "keywords": ["福利"],
    "conversion_target": "preview",
    "base_reply": "当前内容和福利以 @moryselect 的预览为准。",
}

_NONE_RULE = {
    "name": "助理唤醒",
    "topic": "唤醒",
    "conversion_target": "none",
}

_BUTTON_OFF_RULE = {
    "name": "纯闲聊",
    "topic": "闲聊",
    "conversion_target": "none",
    "button_enabled": False,
}


class _FakeDb:
    def __init__(self):
        self.logs = []

    def log_telemetry(self, *args):
        self.logs.append(args)
        return 1

    def track_channel_message(self, *args):
        self.logs.append(args)

    def match_keyword_trigger(self, text):
        return []


class _FakeMoryBot:
    def __init__(self):
        self.replies = []
        self.raw_sent = []

    def reply_and_track(self, message, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(message_id=12)

    def reply_without_track(self, message, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(message_id=13)


# ── pick_auto_reply_cta ──────────────────────────────────────────────────────

def test_pick_binds_subscribe_target():
    cta = pick_auto_reply_cta(_SUBSCRIBE_RULE)
    assert cta is not None
    assert cta["target"] == TARGET_SUBSCRIBE
    assert cta["url"] == _DEFAULT_URLS[TARGET_SUBSCRIBE]
    assert cta["label"] and cta["closing"]


def test_pick_binds_contact_target():
    cta = pick_auto_reply_cta(_CONTACT_RULE)
    assert cta is not None
    assert cta["target"] == TARGET_CONTACT
    assert cta["url"] == _DEFAULT_URLS[TARGET_CONTACT]


def test_pick_binds_preview_target():
    cta = pick_auto_reply_cta(_PREVIEW_RULE)
    assert cta is not None
    assert cta["target"] == TARGET_PREVIEW
    assert cta["url"] == _DEFAULT_URLS[TARGET_PREVIEW]


def test_pick_none_target_returns_no_button():
    """conversion_target=none 是普通聊天红线：禁止挂销售按钮。"""
    assert pick_auto_reply_cta(_NONE_RULE) is None
    assert pick_auto_reply_cta({"conversion_target": ""}) is None
    assert pick_auto_reply_cta({"conversion_target": "unknown"}) is None


def test_pick_random_contact_or_subscribe_when_undeclared():
    import random

    # 仅未声明 conversion_target 键时才随机二选一
    undeclared = {"name": "未声明目标", "topic": "其他"}
    rng = random.Random(7)
    seen = set()
    for _ in range(200):
        cta = pick_auto_reply_cta(undeclared, rng=rng)
        assert cta is not None
        assert cta["target"] in (TARGET_CONTACT, TARGET_SUBSCRIBE)
        seen.add(cta["target"])
    assert seen == {TARGET_CONTACT, TARGET_SUBSCRIBE}


def test_pick_label_from_pool_with_emoji():
    cta = pick_auto_reply_cta(_SUBSCRIBE_RULE)
    assert cta is not None
    pool_labels = [item[0] for item in _AUTO_REPLY_CTA_POOLS[TARGET_SUBSCRIBE]]
    assert cta["label"] in pool_labels


def test_pick_disabled_button_returns_none():
    assert pick_auto_reply_cta(_BUTTON_OFF_RULE) is None


def test_pick_ignores_non_dict_rule():
    assert pick_auto_reply_cta(None) is None  # type: ignore[arg-type]


# ── build_auto_reply_card ───────────────────────────────────────────────────

def test_card_group_gets_markup_and_closing():
    card = build_auto_reply_card(_SUBSCRIBE_RULE, "看过预览的可以直接自助下单。", -1001)
    assert card["markup"] is not None
    assert card["closing"]
    assert "<h2>" in card["rich_html"]
    assert "Mory 小助理" in card["rich_html"]
    assert "<b><i>" in card["html_text"]
    assert "看过预览的可以直接自助下单。" in card["rich_html"]


def test_card_private_chat_no_markup_and_no_closing():
    card = build_auto_reply_card(_SUBSCRIBE_RULE, "想继续的话可以自助下单。", 12345)
    assert card["markup"] is None
    assert card["closing"] == ""
    assert "Mory 小助理" in card["html_text"]


def test_card_escapes_reply_text():
    card = build_auto_reply_card(_CONTACT_RULE, "<b>别被转义搞坏</b>&", -1001)
    assert "<b>别被转义搞坏</b>" not in card["html_text"]
    assert "&lt;b&gt;别被转义搞坏&lt;/b&gt;" in card["html_text"]


def test_card_title_emoji_from_pool():
    import random

    from core.auto_reply_card import _AUTO_REPLY_TITLE_EMOJIS

    rng = random.Random(3)
    card = build_auto_reply_card(_NONE_RULE, "在。", -1001, rng=rng)
    assert card["rich_html"].startswith("<h2>")
    title_emoji = card["rich_html"].split("<h2>")[1].split(" ")[0]
    assert title_emoji in _AUTO_REPLY_TITLE_EMOJIS


# ── 开关 ────────────────────────────────────────────────────────────────────

def test_card_enabled_flag_defaults_off():
    assert is_auto_reply_card_enabled({}) is False
    assert is_auto_reply_card_enabled({"AUTO_REPLY_CARD_ENABLED": False}) is False
    assert is_auto_reply_card_enabled({"AUTO_REPLY_CARD_ENABLED": True}) is True


def test_rich_flag_requires_enable_and_version():
    assert is_rich_message_enabled({}) is False
    assert is_rich_message_enabled({"RICH_MESSAGE_ENABLED": True}) is False
    assert is_rich_message_enabled(
        {"RICH_MESSAGE_ENABLED": True, "BROADCAST_FORMAT_VERSION": "rich"}
    ) is True
    assert is_rich_message_enabled(
        {"RICH_MESSAGE_ENABLED": True, "BROADCAST_FORMAT_VERSION": "html"}
    ) is False


# ── keyword_trigger 集成 ────────────────────────────────────────────────────

def _make_trigger(*rules, config_extra=None):
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    config = {"SPECIAL_AUTO_REPLIES": list(rules)}
    config.update(config_extra or {})
    return KeywordTrigger(db, mory_bot=_FakeMoryBot(), ai=None, config=config)


def _message(text="福利"):
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=-1001, type="group"),
        from_user=SimpleNamespace(id=42),
    )


def test_send_plain_text_when_card_disabled(monkeypatch):
    trigger = _make_trigger(_PREVIEW_RULE)
    message = _message()
    mory_bot = trigger.mory_bot
    assert mory_bot is not None

    assert (
        trigger.handle_message("福利在哪", -1001, message, object()) is True
    )
    assert mory_bot.replies[0][0] == "当前内容和福利以 @moryselect 的预览为准。"
    assert mory_bot.replies[0][1] == {}


def test_send_rich_first_then_html_fallback(monkeypatch):
    trigger = _make_trigger(
        _PREVIEW_RULE,
        config_extra={
            "AUTO_REPLY_CARD_ENABLED": True,
            "RICH_MESSAGE_ENABLED": True,
            "BROADCAST_FORMAT_VERSION": "rich",
        },
    )
    mory_bot = trigger.mory_bot
    assert mory_bot is not None

    sent = []

    def fake_rich(bot, chat_id, rich_html, **kwargs):
        sent.append(("rich", chat_id, rich_html, kwargs))
        raise RuntimeError("rich 不可用")

    monkeypatch.setattr(
        "core.telebot_compat.send_rich_message_compat", fake_rich
    )

    message = _message(text="福利在哪")
    assert trigger.handle_message("福利在哪", -1001, message, object()) is True
    assert sent and sent[0][0] == "rich"
    reply_text, kwargs = mory_bot.replies[0]
    assert kwargs.get("parse_mode") == "HTML"
    assert "<b><i>" in reply_text
