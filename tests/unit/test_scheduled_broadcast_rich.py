# -*- coding: utf-8 -*-

from types import SimpleNamespace

import pytest

from modules import scheduled_broadcast
from core.broadcast_formatter import build_greeting_html
from core.telebot_compat import (
    get_allowed_updates,
    preserve_message_extra_fields,
    restrict_chat_member_compat,
    send_checklist_compat,
    send_photo_compat,
    send_poll_compat,
    send_rich_message_compat,
)


class _FakeDb:
    def __init__(self):
        self.tracked = []
        self.claimed = []
        self.released = []
        self.profiles = {}

    def is_task_executed_today(self, task_key):
        return False

    def claim_task(self, task_key):
        self.claimed.append(task_key)
        return True

    def release_task(self, task_key):
        self.released.append(task_key)
        return True

    def track_channel_message(self, chat_id, message_id, content_type):
        self.tracked.append((chat_id, message_id, content_type))

    def get_user_profile(self, user_id):
        return self.profiles.get(user_id)


def test_get_broadcast_schedule_supports_hour_minute_and_time():
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {"id": "a", "enabled": True, "hour": 9, "minute": 15, "content": "A"},
            {"id": "b", "enabled": True, "time": "20:35", "content": "B"},
        ]
    }

    schedule = scheduled_broadcast.get_broadcast_schedule(cfg)

    assert schedule[0]["hour"] == 9
    assert schedule[0]["minute"] == 15
    assert schedule[1]["hour"] == 20
    assert schedule[1]["minute"] == 35


def test_execute_scheduled_broadcast_only_sends_target_broadcast(monkeypatch):
    calls = []
    db = _FakeDb()
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {"id": "morning", "enabled": True, "hour": 9, "minute": 0, "content": "早上好", "type": "text"},
            {"id": "evening", "enabled": True, "hour": 20, "minute": 0, "content": "晚上好", "type": "text"},
        ]
    }

    def fake_send_message(bot, chat_id, text, **kwargs):
        calls.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=101)

    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send_message)

    scheduled_broadcast.execute_scheduled_broadcast(
        bot=object(),
        chat_id=-1001,
        config=cfg,
        db=db,
        target_broadcast_id="evening",
    )

    assert len(calls) == 1
    assert "晚上好" in calls[0][1]
    assert db.tracked == [(-1001, 101, "text")]


def test_execute_scheduled_broadcast_wraps_plain_text_as_html(monkeypatch):
    captured = {}
    db = _FakeDb()
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {
                "id": "notice",
                "enabled": True,
                "hour": 10,
                "minute": 30,
                "title": "今日提醒",
                "badge": "Mory小提示",
                "footer": "需要详细入口的话，点按钮就行。",
                "button_text": "去看看",
                "button_url": "https://t.me/MorychannelBot",
                "content": "今晚会有新内容上线，记得来看看。",
                "type": "text",
            }
        ]
    }

    def fake_send_message(bot, chat_id, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=202)

    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send_message)

    scheduled_broadcast.execute_scheduled_broadcast(object(), -1002, cfg, db, target_broadcast_id="notice")

    assert "今日提醒" in captured["text"]
    assert "<b><i>" in captured["text"]
    assert "<blockquote expandable>" in captured["text"]
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert captured["kwargs"]["reply_markup"] is not None


@pytest.mark.parametrize("content_type", ["rich_message", "text", "voice", "poll", "checklist"])
def test_terminal_send_failure_releases_claim_and_raises(monkeypatch, content_type):
    db = _FakeDb()
    item = {
        "id": f"failure_{content_type}",
        "enabled": True,
        "type": content_type,
        "content": "测试内容",
    }
    if content_type == "rich_message":
        item["rich_message"] = {"text": "测试内容"}
        monkeypatch.setattr(
            scheduled_broadcast,
            "send_rich_message_compat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("network down")),
        )
    elif content_type == "text":
        monkeypatch.setattr(
            scheduled_broadcast,
            "send_message_compat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("network down")),
        )
    elif content_type == "voice":
        class _Bot:
            def send_voice(self, *_args, **_kwargs):
                raise ConnectionError("network down")
        bot = _Bot()
    elif content_type == "poll":
        item.update({"question": "选一个", "options": ["A", "B"]})
        monkeypatch.setattr(
            scheduled_broadcast,
            "send_poll_compat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("network down")),
        )
    else:
        item.update({"business_connection_id": "biz", "tasks": ["A"]})
        monkeypatch.setattr(
            scheduled_broadcast,
            "send_checklist_compat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("network down")),
        )

    bot = locals().get("bot", object())
    cfg = {"SCHEDULED_BROADCASTS": [item]}
    with pytest.raises(ConnectionError, match="network down"):
        scheduled_broadcast.execute_scheduled_broadcast(
            bot, -1001, cfg, db, target_broadcast_id=item["id"]
        )

    assert len(db.claimed) == 1
    assert db.released == db.claimed


def test_image_fallback_success_keeps_claim_and_returns_success(monkeypatch):
    db = _FakeDb()
    monkeypatch.setattr(
        scheduled_broadcast,
        "send_photo_compat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("photo down")),
    )
    monkeypatch.setattr(
        scheduled_broadcast,
        "send_message_compat",
        lambda *_args, **_kwargs: SimpleNamespace(message_id=808),
    )
    cfg = {"SCHEDULED_BROADCASTS": [{
        "id": "image_fallback",
        "enabled": True,
        "type": "image",
        "content": "missing-file.jpg",
        "caption": "图片暂不可用，先看文字。",
    }]}

    scheduled_broadcast.execute_scheduled_broadcast(
        object(), -1001, cfg, db, target_broadcast_id="image_fallback"
    )

    assert db.released == []
    assert db.tracked == [(-1001, 808, "text")]


@pytest.mark.parametrize("item", [
    {"id": "bad_poll", "enabled": True, "type": "poll", "question": "", "options": []},
    {"id": "bad_checklist", "enabled": True, "type": "checklist", "tasks": ["A"]},
])
def test_invalid_claimed_broadcast_releases_and_raises(item):
    db = _FakeDb()
    with pytest.raises(ValueError, match="配置无效"):
        scheduled_broadcast.execute_scheduled_broadcast(
            object(), -1001, {"SCHEDULED_BROADCASTS": [item]}, db,
            target_broadcast_id=item["id"],
        )

    assert db.released == db.claimed


def test_execute_scheduled_broadcast_applies_profile_and_template_variation(monkeypatch):
    captured = {}
    db = _FakeDb()
    db.profiles[12345] = {"tags": ["vip"], "level": 5, "interests": ["tarot"]}
    cfg = {
        "BROADCAST_TEMPLATE_VARIATION_ENABLED": True,
        "SCHEDULED_BROADCASTS": [
            {
                "id": "vip_notice",
                "enabled": True,
                "hour": 21,
                "minute": 0,
                "period": "night",
                "title": "睡前提醒",
                "footer": "原来的尾巴还在。",
                "content": "今晚也给你留了一点内容。",
                "type": "text",
            }
        ]
    }

    def fake_send_message(bot, chat_id, text, **kwargs):
        captured["text"] = text
        return SimpleNamespace(message_id=212)

    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send_message)

    scheduled_broadcast.execute_scheduled_broadcast(object(), 12345, cfg, db, target_broadcast_id="vip_notice")

    # 去萌化后画像只改变视觉语气，不再暴露“VIP专属”等机械标签；
    # v5.38.10 也已删除会复发尬聊的固定模板变体。
    assert "🔮 睡前提醒" in captured["text"]
    assert "VIP专属" not in captured["text"]
    assert "精选推荐" not in captured["text"]
    assert "原来的尾巴还在。" in captured["text"]
    assert "今晚不重复昨天那句" not in captured["text"]
    assert "睡前版本今天" not in captured["text"]
    assert "深夜这条仍然" not in captured["text"]


def test_build_markup_receives_config_for_colored_button(monkeypatch):
    calls = {}

    def fake_create_colored_button(text, url=None, callback_data=None, style="default", icon_emoji_id=None):
        calls["text"] = text
        calls["url"] = url
        calls["style"] = style
        calls["icon_emoji_id"] = icon_emoji_id
        from telebot import types
        return types.InlineKeyboardButton(text=text, url=url)

    monkeypatch.setattr("core.telebot_compat.create_colored_button", fake_create_colored_button)

    markup = scheduled_broadcast._build_markup(
        {
            "button_text": "去看看",
            "button_url": "https://t.me/MorychannelBot",
            "button_style": "success",
            "button_emoji_id": "emoji-1",
        },
        {"BUTTON_STYLE_ENABLED": True},
    )

    assert markup is not None
    assert calls == {
        "text": "去看看",
        "url": "https://t.me/MorychannelBot",
        "style": "success",
        "icon_emoji_id": "emoji-1",
    }


def test_build_greeting_html_uses_expandable_footer():
    rich = build_greeting_html("morning", "今天也要顺顺利利呀", "有事随时来找我。")

    assert "<b><i>☀️ 早</i></b>" in rich
    assert "今天也要顺顺利利呀" in rich
    assert "<blockquote expandable>" in rich
    assert "有事随时来找我。" in rich


def test_send_photo_compat_falls_back_to_raw_request(monkeypatch):
    calls = {}

    class _Bot:
        token = "fake-token"

        def send_photo(self, *args, **kwargs):
            raise AssertionError("带 show_caption_above_media 时不该走原生 send_photo")

    def fake_raw_request(bot, method_name, params, files=None):
        calls["method_name"] = method_name
        calls["params"] = params
        return SimpleNamespace(message_id=303)

    monkeypatch.setattr("core.telebot_compat._make_raw_request", fake_raw_request)

    result = send_photo_compat(
        _Bot(),
        -1003,
        "AgACAg-test",
        caption="hello",
        show_caption_above_media=True,
    )

    assert result.message_id == 303
    assert calls["method_name"] == "sendPhoto"
    assert calls["params"]["show_caption_above_media"] is True


def test_send_rich_message_compat_calls_raw_api(monkeypatch):
    calls = {}

    class _Bot:
        token = "fake-token"

    def fake_raw_request(bot, method_name, params, files=None):
        calls["method_name"] = method_name
        calls["params"] = params
        return SimpleNamespace(message_id=404)

    monkeypatch.setattr("core.telebot_compat._make_raw_request", fake_raw_request)

    result = send_rich_message_compat(
        _Bot(),
        -1004,
        {"text": {"text": "hello"}},
        allow_paid_broadcast=True,
    )

    assert result.message_id == 404
    assert calls["method_name"] == "sendRichMessage"
    assert calls["params"]["allow_paid_broadcast"] is True


def test_send_poll_compat_uses_raw_api_for_new_poll_fields(monkeypatch):
    calls = {}

    class _Bot:
        token = "fake-token"

        def send_poll(self, *args, **kwargs):
            raise AssertionError("带新版投票字段时不该走原生 send_poll")

    def fake_raw_request(bot, method_name, params, files=None):
        calls["method_name"] = method_name
        calls["params"] = params
        return SimpleNamespace(message_id=405)

    monkeypatch.setattr("core.telebot_compat._make_raw_request", fake_raw_request)

    result = send_poll_compat(
        _Bot(),
        -1004,
        "问题",
        ["A", "B"],
        members_only=True,
        allow_adding_options=True,
    )

    assert result.message_id == 405
    assert calls["method_name"] == "sendPoll"
    assert calls["params"]["members_only"] is True


def test_send_checklist_compat_calls_raw_api(monkeypatch):
    calls = {}

    class _Bot:
        token = "fake-token"

    def fake_raw_request(bot, method_name, params, files=None):
        calls["method_name"] = method_name
        calls["params"] = params
        return SimpleNamespace(message_id=406)

    monkeypatch.setattr("core.telebot_compat._make_raw_request", fake_raw_request)

    result = send_checklist_compat(
        _Bot(),
        "bc_1",
        -1004,
        {"title": "清单", "tasks": [{"id": 1, "text": "确认活动"}]},
    )

    assert result.message_id == 406
    assert calls["method_name"] == "sendChecklist"
    assert calls["params"]["business_connection_id"] == "bc_1"


def test_execute_scheduled_broadcast_supports_rich_message(monkeypatch):
    captured = {}
    db = _FakeDb()
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {
                "id": "rich_1",
                "enabled": True,
                "hour": 11,
                "minute": 45,
                "type": "rich_message",
                "rich_message": {"text": {"text": "rich body"}},
            }
        ]
    }

    def fake_send_rich_message(bot, chat_id, rich_message, **kwargs):
        captured["chat_id"] = chat_id
        captured["rich_message"] = rich_message
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=505)

    monkeypatch.setattr(scheduled_broadcast, "send_rich_message_compat", fake_send_rich_message)

    scheduled_broadcast.execute_scheduled_broadcast(
        object(),
        -1005,
        cfg,
        db,
        target_broadcast_id="rich_1",
    )

    assert captured["chat_id"] == -1005
    assert captured["rich_message"]["text"]["text"] == "rich body"
    assert db.tracked == [(-1005, 505, "rich_message")]


def test_text_broadcast_prefers_rich_message_when_enabled(monkeypatch):
    """Rich Message HTML 自动转换已在 v5.31.0 临时禁用，当前预期回退到 HTML 发送。

    原因：_html_to_rich_components 生成的组件格式触发 Telegram API 400
    "object expected as rich message"。待组件转换器修复后再恢复 Rich 优先。
    """
    captured = {}
    db = _FakeDb()
    cfg = {
        "RICH_MESSAGE_ENABLED": True,
        "BROADCAST_FORMAT_VERSION": "rich",
        "SCHEDULED_BROADCASTS": [
            {"id": "rich_text", "enabled": True, "hour": 10, "minute": 0, "content": "正文", "type": "text"}
        ],
    }

    def fake_send_rich(*args, **kwargs):
        raise AssertionError("HTML 自动转 Rich 已禁用，不应调用 send_rich_message_compat")

    def fake_send_message(bot, chat_id, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=515)

    monkeypatch.setattr(scheduled_broadcast, "send_rich_message_compat", fake_send_rich)
    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send_message)

    scheduled_broadcast.execute_scheduled_broadcast(object(), -1005, cfg, db, target_broadcast_id="rich_text")

    assert "正文" in captured["text"]
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert db.tracked == [(-1005, 515, "text")]


def test_text_broadcast_falls_back_to_html_when_rich_fails(monkeypatch):
    captured = {}
    db = _FakeDb()
    cfg = {
        "RICH_MESSAGE_ENABLED": True,
        "BROADCAST_FORMAT_VERSION": "rich",
        "SCHEDULED_BROADCASTS": [
            {"id": "fallback_text", "enabled": True, "hour": 10, "minute": 0, "content": "正文", "type": "text"}
        ],
    }

    def fake_send_rich(*args, **kwargs):
        raise RuntimeError("rich unavailable")

    def fake_send_message(bot, chat_id, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=516)

    monkeypatch.setattr(scheduled_broadcast, "send_rich_message_compat", fake_send_rich)
    monkeypatch.setattr(scheduled_broadcast, "send_message_compat", fake_send_message)

    scheduled_broadcast.execute_scheduled_broadcast(object(), -1005, cfg, db, target_broadcast_id="fallback_text")

    assert "正文" in captured["text"]
    assert captured["kwargs"]["parse_mode"] == "HTML"
    assert db.tracked == [(-1005, 516, "text")]


def test_execute_scheduled_broadcast_supports_new_poll(monkeypatch):
    captured = {}
    db = _FakeDb()
    cfg = {
        "SCHEDULED_BROADCASTS": [
            {
                "id": "poll_1",
                "enabled": True,
                "hour": 12,
                "minute": 5,
                "type": "poll",
                "question": "今晚想看哪种内容",
                "options": ["轻松聊天", "深夜故事"],
                "members_only": True,
                "allow_adding_options": True,
                "hide_results_until_closes": True,
            }
        ]
    }

    def fake_send_poll(bot, chat_id, question, options, **kwargs):
        captured["chat_id"] = chat_id
        captured["question"] = question
        captured["options"] = options
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=606)

    monkeypatch.setattr(scheduled_broadcast, "send_poll_compat", fake_send_poll)

    scheduled_broadcast.execute_scheduled_broadcast(
        object(),
        -1006,
        cfg,
        db,
        target_broadcast_id="poll_1",
    )

    assert captured["chat_id"] == -1006
    assert captured["question"] == "今晚想看哪种内容"
    assert captured["kwargs"]["members_only"] is True
    assert captured["kwargs"]["allow_adding_options"] is True
    assert db.tracked == [(-1006, 606, "poll")]


def test_execute_scheduled_broadcast_supports_checklist(monkeypatch):
    captured = {}
    db = _FakeDb()
    cfg = {
        "TELEGRAM_BUSINESS_CONNECTION_ID": "bc_1",
        "SCHEDULED_BROADCASTS": [
            {
                "id": "checklist_1",
                "enabled": True,
                "hour": 14,
                "minute": 20,
                "type": "checklist",
                "title": "活动清单",
                "tasks": ["确认素材", "检查入口"],
            }
        ],
    }

    def fake_send_checklist(bot, business_connection_id, chat_id, checklist, **kwargs):
        captured["business_connection_id"] = business_connection_id
        captured["chat_id"] = chat_id
        captured["checklist"] = checklist
        return SimpleNamespace(message_id=808)

    monkeypatch.setattr(scheduled_broadcast, "send_checklist_compat", fake_send_checklist)

    scheduled_broadcast.execute_scheduled_broadcast(
        object(),
        -1008,
        cfg,
        db,
        target_broadcast_id="checklist_1",
    )

    assert captured["business_connection_id"] == "bc_1"
    assert captured["checklist"]["tasks"][0]["text"] == "确认素材"
    assert db.tracked == [(-1008, 808, "checklist")]


def test_preserve_message_extra_fields_keeps_bot_api_10_fields():
    from telebot import types

    preserve_message_extra_fields()
    # 【v5.38.9 修复】pyTelegramBotAPI 4.36.0 的 RichMessage.de_json 要求 blocks 字段，
    # 旧的 {"text": {"text": "hello"}} 格式已不兼容。使用 Bot API 10 的 paragraph block。
    msg = types.Message.de_json({
        "message_id": 1,
        "date": 1,
        "chat": {"id": 1, "type": "private"},
        "rich_message": {"blocks": [{"type": "paragraph", "text": "hello"}]},
        "guest_query_id": "guest-1",
    })

    assert msg.content_type == "rich_message"
    assert msg.rich_message is not None
    assert len(msg.rich_message.blocks) == 1
    assert msg.guest_query_id == "guest-1"


def test_business_message_update_enters_message_pipeline():
    from core.telebot_compat import preserve_telegram_extra_fields
    from telebot import types

    preserve_telegram_extra_fields()
    update = types.Update.de_json({
        "update_id": 100,
        "business_message": {
            "message_id": 9,
            "date": 1,
            "chat": {"id": 1, "type": "private"},
            "business_connection_id": "bc_1",
            "text": "hello",
        },
    })

    assert update.business_message.text == "hello"
    assert update.message.text == "hello"
    assert update.message.business_connection_id == "bc_1"
    assert update.message._mory_update_type == "business_message"


def test_edited_business_message_update_enters_edited_pipeline():
    from core.telebot_compat import preserve_telegram_extra_fields
    from telebot import types

    preserve_telegram_extra_fields()
    update = types.Update.de_json({
        "update_id": 101,
        "edited_business_message": {
            "message_id": 10,
            "date": 1,
            "chat": {"id": 1, "type": "private"},
            "business_connection_id": "bc_2",
            "text": "edited",
        },
    })

    assert update.edited_business_message.text == "edited"
    assert update.edited_message.text == "edited"
    assert update.edited_message.business_connection_id == "bc_2"
    assert update.edited_message._mory_update_type == "edited_business_message"


def test_restrict_chat_member_compat_passes_new_permission_fields_to_raw(monkeypatch):
    calls = {}

    class _Bot:
        token = "fake-token"

    def fake_raw_result(bot, method_name, params, files=None):
        calls["method_name"] = method_name
        calls["params"] = params
        return True

    monkeypatch.setattr("core.telebot_compat._make_raw_result", fake_raw_result)

    ok = restrict_chat_member_compat(
        _Bot(),
        -1006,
        42,
        permissions={
            "can_send_messages": False,
            "can_react_to_messages": False,
            "can_send_paid_media": False,
        },
    )

    assert ok is True
    assert calls["method_name"] == "restrictChatMember"
    assert calls["params"]["permissions"]["can_react_to_messages"] is False


def test_get_allowed_updates_enables_existing_handlers_and_new_events():
    updates = get_allowed_updates({})

    assert "edited_message" in updates
    assert "channel_post" in updates
    assert "edited_channel_post" in updates
    assert "message_reaction" in updates
    assert "business_message" in updates
    assert "deleted_business_messages" in updates
    assert "guest_message" in updates
    assert "managed_bot" in updates


def test_get_allowed_updates_can_be_overridden_or_unbounded():
    updates = get_allowed_updates({"TELEGRAM_ALLOWED_UPDATES": ["message", "custom_update"]})
    assert updates[0:2] == ["message", "custom_update"]
    assert "deleted_business_messages" in updates
    assert get_allowed_updates({"TELEGRAM_ALLOWED_UPDATES": "all"}) is None
