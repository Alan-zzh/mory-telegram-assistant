# -*- coding: utf-8 -*-
"""播报排版、话题润色与监控误报回归测试。"""

from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
from types import SimpleNamespace


def test_polling_exception_handler_only_handles_get_updates_5xx(monkeypatch):
    from core.telegram_send_utils import TelegramPollingExceptionHandler

    sleeps = []
    warnings = []
    handler = TelegramPollingExceptionHandler(
        sleep_func=sleeps.append,
        warning_func=warnings.append,
    )

    class FakeApiError(Exception):
        function_name = "getUpdates"
        error_code = 502

    class FakeSendError(Exception):
        function_name = "sendMessage"
        error_code = 502

    assert handler.handle(FakeApiError("Bad Gateway")) is True
    assert sleeps == [1]
    assert len(warnings) == 1
    assert "502" in warnings[0]
    assert handler.handle(FakeSendError("Bad Gateway")) is False


def test_broadcast_button_matches_each_user_intent():
    from tasks.support.common import build_mory_contact_markup

    expected = {
        "afternoon": ("👀 看看预览", "https://t.me/moryselect"),
        "night": ("👀 看看预览", "https://t.me/moryselect"),
    }

    for period, (text, url) in expected.items():
        markup = build_mory_contact_markup(period)
        button = markup.keyboard[0][0]
        assert (button.text, button.url) == (text, url)
    assert build_mory_contact_markup("morning") is None
    assert build_mory_contact_markup("evening") is None
    assert build_mory_contact_markup("news") is None


def test_scheduled_broadcast_example_alternates_contact_and_self_service():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    buttons = {
        item["id"]: (item["button_text"], item["button_url"])
        for item in config["SCHEDULED_BROADCASTS"]
    }

    assert buttons == {
        "morning_nudge": ("", ""),
        "afternoon_tease": ("👀 看看预览", "https://t.me/moryselect"),
        "evening_warm": ("", ""),
        "night_hook": ("👀 看看预览", "https://t.me/moryselect"),
    }


def test_static_information_topics_only_use_preview_entry():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    topics = {item["topic"]: item for item in config["SPECIAL_AUTO_REPLIES"]}

    for topic in ("价格", "福利", "内容"):
        rule = topics[topic]
        assert rule["conversion_target"] == "preview"
        assert rule["required_terms"] == ["@moryselect"]
        assert "@MorychannelBot" not in rule["base_reply"]
        assert "@Moryfansbot" not in rule["base_reply"]
    assert "定制" not in topics


def test_send_greeting_keeps_button_on_html_fallback(monkeypatch):
    import tasks.support.common as common

    captured = {}

    class _GreetingDb:
        def track_channel_message(self, *args):
            pass

        def track_bot_message(self, *args):
            pass

        def track_broadcast(self, *args):
            pass

    class _Rm:
        config = {
            "RICH_MESSAGE_ENABLED": False,
            "BROADCAST_AUTO_DELETE_CONFIG": {"greeting_chain_delete": False},
        }
        bot = object()
        db = _GreetingDb()

        @contextmanager
        def locked(self, _name):
            yield

    def fake_send(_bot, _chat_id, text, **kwargs):
        captured["text"] = text
        captured["kwargs"] = kwargs
        return SimpleNamespace(message_id=21)

    monkeypatch.setattr(common, "send_message_compat", fake_send)
    monkeypatch.setattr(common, "schedule_auto_delete", lambda *args: None)
    markup = common.build_mory_contact_markup("afternoon")

    sent = common.send_greeting(
        _Rm(),
        -1001,
        "<b>晚安</b>",
        rich_text="<h2>晚安</h2>",
        reply_markup=markup,
    )

    assert sent.message_id == 21
    assert captured["kwargs"]["reply_markup"] is markup
    assert captured["kwargs"]["parse_mode"] == "HTML"


class _FakeDb:
    def __init__(self):
        self.telemetry = []

    def log_telemetry(self, *args):
        self.telemetry.append(args)
        return 1


class _FakeMoryBot:
    def __init__(self):
        self.replies = []

    def reply_and_track(self, message, text):
        self.replies.append(text)
        return SimpleNamespace(message_id=12)


class _FakeAi:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return self.reply


def _topic_config():
    return {
        "SPECIAL_AUTO_REPLIES": [{
            "name": "福利咨询",
            "topic": "福利",
            "enabled": True,
            "keywords": ["福利", "更多福利"],
            "ai_polish": True,
            "ai_mode": "normal",
            "conversion_target": "preview",
            "polish_prompt": "不要承诺未配置优惠，只保留 @moryselect。",
            "required_terms": ["@moryselect"],
            "forbidden_terms": ["轻食"],
            "base_reply": "当前内容和福利以 @moryselect 的预览为准。",
        }]
    }


def test_special_topic_reply_uses_ai_and_records_anonymous_stats():
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    mory_bot = _FakeMoryBot()
    ai = _FakeAi("想看更完整一点的，去 @moryselect 自己翻，别急。")
    trigger = KeywordTrigger(db, mory_bot=mory_bot, ai=ai, config=_topic_config())
    message = SimpleNamespace(
        text="福利在哪呀",
        from_user=SimpleNamespace(id=42),
    )

    assert trigger.handle_message(message.text, -1001, message, object()) is True
    assert mory_bot.replies == ["想看更完整一点的，去 @moryselect 自己翻，别急。"]
    assert "不要承诺未配置优惠" in ai.calls[0][0]
    event = db.telemetry[0]
    assert event[0:6] == (
        42,
        -1001,
        "topic_interest",
        "福利",
        "reply_polished",
        1.0,
    )
    assert "用户原话" not in event[6]


def test_special_topic_reply_rejects_internal_ai_fallback():
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    mory_bot = _FakeMoryBot()
    ai = _FakeAi("润色后：脑子刚才短路，请稍后再试")
    trigger = KeywordTrigger(db, mory_bot=mory_bot, ai=ai, config=_topic_config())
    message = SimpleNamespace(
        text="有没有福利",
        from_user=SimpleNamespace(id=43),
    )

    assert trigger.handle_message(message.text, 43, message, object()) is True
    assert mory_bot.replies == ["当前内容和福利以 @moryselect 的预览为准。"]
    assert db.telemetry[0][4] == "reply_template"


def test_special_topic_reply_rejects_rule_specific_hallucination():
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    mory_bot = _FakeMoryBot()
    ai = _FakeAi("想看福利就去 @moryselect，群里只是轻食版。")
    trigger = KeywordTrigger(db, mory_bot=mory_bot, ai=ai, config=_topic_config())
    message = SimpleNamespace(
        text="福利在哪",
        from_user=SimpleNamespace(id=44),
    )

    assert trigger.handle_message(message.text, 44, message, object()) is True
    assert mory_bot.replies == ["当前内容和福利以 @moryselect 的预览为准。"]
    assert db.telemetry[0][4] == "reply_template"


def test_custom_topic_requires_mory_as_decision_owner():
    from modules.keyword_trigger import KeywordTrigger

    rule = {
        "required_terms": ["@Moryfansbot", "Mory确认"],
        "forbidden_terms": ["我"],
    }

    assert KeywordTrigger._is_usable_polish(
        "去 @Moryfansbot 说清需求，最后由Mory确认能不能接。",
        rule,
    )
    assert not KeywordTrigger._is_usable_polish(
        "去 @Moryfansbot 说清需求，我确认能接再聊。",
        rule,
    )


def test_partial_prompt_config_keeps_default_greeting_modes():
    from core.ai_engine import AIEngine

    engine = object.__new__(AIEngine)
    engine.config = {"PROMPT_TEMPLATES": {"tarot": "自定义塔罗"}}

    prompt, is_replacement = engine._get_mode_persona("morning", seed=123)

    assert "在熟悉的粉丝群里发一条早安" in prompt
    assert "不虚构Mory刚醒" in prompt
    assert "随机种子123" in prompt
    assert is_replacement is True


def test_legacy_productivity_greeting_override_is_ignored():
    """旧配置不能继续把粉丝群问候写成效率教练或编程运维提醒。"""
    from core.ai_engine import AIEngine

    engine = object.__new__(AIEngine)
    engine.config = {
        "PROMPT_TEMPLATES": {
            "afternoon": "午安。别硬撑多线程，把通知静音，只留当前任务窗口。",
        }
    }

    prompt, is_replacement = engine._get_mode_persona("afternoon", seed=321)

    assert is_replacement is True
    assert "熟悉的粉丝群" in prompt
    assert "延续主助理人设" in prompt
    assert "别硬撑多线程" not in prompt
    assert "只留当前任务窗口" not in prompt


def test_greeting_full_persona_keeps_configured_mory_identity():
    """问候专用提示词仍应继承 BASE_PERSONA 的人设底色。"""
    from core.ai_engine import AIEngine

    engine = object.__new__(AIEngine)
    engine.config = {
        "BASE_PERSONA": "你是Mory，底色是清冷、小傲娇和温柔。",
        "STYLE_APPEND": "像熟悉的群友说话，走心但不演戏。",
        "PROMPT_TEMPLATES": {},
    }
    engine.model_pool = [{"name": "test-model"}]
    engine.current_idx = 0

    persona = engine._build_persona(
        "afternoon",
        seed=456,
        is_priv=False,
        message="午安",
        model_name="test-model",
    )

    assert "清冷、小傲娇和温柔" in persona
    assert "像熟悉的群友说话" in persona
    assert "熟悉的粉丝群" in persona


def test_scheduled_broadcast_rejects_ai_failure_copy():
    from modules.scheduled_broadcast import _try_ai_generate

    ai = _FakeAi("脑子刚才短路了，暂时没法稳定接上模型，请等一会儿。")
    content = _try_ai_generate(
        {"ai_generate": True, "period": "morning"},
        ai,
        "morning_nudge",
    )

    assert content == ""


def test_greeting_quality_gate_rejects_productivity_copy_and_accepts_fan_copy():
    from tasks.support.message_templates import MessageTemplates

    assert MessageTemplates.is_usable_greeting(
        "afternoon",
        "午安呀。忙到现在也该歇口气了，你们在群里冒个泡，我看到就会回。",
    )
    assert not MessageTemplates.is_usable_greeting(
        "morning",
        "早安，先喝口水缓一缓，今天会顺一点。",
    )
    assert not MessageTemplates.is_usable_greeting(
        "afternoon",
        "下午脑子容易被弹窗切得稀碎，别硬撑多线程。把无关通知全静音，只留当前任务窗口就行。",
    )


def test_greeting_has_no_fixed_fallback_copy_pool():
    from tasks.support.message_templates import MessageTemplates

    assert not hasattr(MessageTemplates, "GREETING_FALLBACK_POOL")
    assert not hasattr(MessageTemplates, "get_fallback_greeting")
