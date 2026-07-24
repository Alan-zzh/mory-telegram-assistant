# -*- coding: utf-8 -*-
"""播报排版、话题润色与监控误报回归测试。"""

from contextlib import contextmanager
from types import SimpleNamespace


def test_news_internal_source_labels_never_render():
    from core.broadcast_formatter import (
        build_rich_news_card_message,
        build_rich_news_html,
    )

    news = "\n".join([
        "第一条真实新闻",
        "第二条真实新闻",
        "第三条真实新闻",
        "第四条真实新闻",
        "第五条真实新闻",
        "💡 信息还在继续变化",
    ])
    for renderer in (build_rich_news_html, build_rich_news_card_message):
        rendered = renderer("早间", news, source_name="fallback")
        assert "多源汇总" not in rendered
        assert "均衡筛选" not in rendered
        assert "TrendRadar" not in rendered
        assert "@MorychannelBot" in rendered


def test_greeting_contact_button_is_period_specific():
    from tasks.support.common import build_mory_contact_markup

    markup = build_mory_contact_markup("morning")
    button = markup.keyboard[0][0]

    assert button.text == "☀️ 和 Mory 说早安"
    assert button.url == "https://t.me/MorychannelBot"


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
    markup = common.build_mory_contact_markup("evening")

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
            "polish_prompt": "不要承诺未配置优惠。",
            "required_terms": ["@MorychannelBot"],
            "forbidden_terms": ["轻食"],
            "base_reply": "更完整的内容在 @MorychannelBot。",
        }]
    }


def test_special_topic_reply_uses_ai_and_records_anonymous_stats():
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    mory_bot = _FakeMoryBot()
    ai = _FakeAi("想看更完整一点的，去 @MorychannelBot 自己翻，别急。")
    trigger = KeywordTrigger(db, mory_bot=mory_bot, ai=ai, config=_topic_config())
    message = SimpleNamespace(
        text="福利在哪呀",
        from_user=SimpleNamespace(id=42),
    )

    assert trigger.handle_message(message.text, -1001, message, object()) is True
    assert mory_bot.replies == ["想看更完整一点的，去 @MorychannelBot 自己翻，别急。"]
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
    assert mory_bot.replies == ["更完整的内容在 @MorychannelBot。"]
    assert db.telemetry[0][4] == "reply_template"


def test_special_topic_reply_rejects_rule_specific_hallucination():
    from modules.keyword_trigger import KeywordTrigger

    db = _FakeDb()
    mory_bot = _FakeMoryBot()
    ai = _FakeAi("想看福利就去 @MorychannelBot，群里只是轻食版。")
    trigger = KeywordTrigger(db, mory_bot=mory_bot, ai=ai, config=_topic_config())
    message = SimpleNamespace(
        text="福利在哪",
        from_user=SimpleNamespace(id=44),
    )

    assert trigger.handle_message(message.text, 44, message, object()) is True
    assert mory_bot.replies == ["更完整的内容在 @MorychannelBot。"]
    assert db.telemetry[0][4] == "reply_template"


def test_partial_prompt_config_keeps_default_greeting_modes():
    from core.ai_engine import AIEngine

    engine = object.__new__(AIEngine)
    engine.config = {"PROMPT_TEMPLATES": {"tarot": "自定义塔罗"}}

    prompt, is_replacement = engine._get_mode_persona("morning", seed=123)

    assert "给熟悉的群友发一条早安" in prompt
    assert "不要写Mory本人做了什么" in prompt
    assert "随机种子123" in prompt
    assert is_replacement is True


def test_zero_throughput_single_pending_write_does_not_trigger_migration_alert(monkeypatch):
    import core.db_migration_monitor as monitor
    from core.write_queue import write_queue

    with monitor._samples_lock:
        monitor._samples.clear()
        monitor._samples.extend([
            {"ts": 100.0, "total": 10, "pending": 0, "success": 10, "failed": 0},
            {"ts": 160.0, "total": 11, "pending": 1, "success": 10, "failed": 0},
        ])
    monkeypatch.setattr(
        write_queue,
        "get_stats",
        lambda: {"total": 11, "pending": 1, "success": 10, "failed": 0},
    )

    result = monitor._check_avg_write_queue_delay()

    assert result["value"] is None
    assert result["exceeded"] is False
    assert "无法推算" in result["message"]


def test_scheduled_broadcast_rejects_ai_failure_copy():
    from modules.scheduled_broadcast import _try_ai_generate

    ai = _FakeAi("脑子刚才短路了，暂时没法稳定接上模型，请等一会儿。")
    content = _try_ai_generate(
        {"ai_generate": True, "period": "morning"},
        ai,
        "morning_nudge",
    )

    assert content == ""


def test_greeting_quality_gate_rejects_cliche_and_accepts_plain_copy():
    from tasks.support.message_templates import MessageTemplates

    assert MessageTemplates.is_usable_greeting(
        "morning",
        "早。先别急着回完所有消息，挑一件真要紧的做，脑子会清楚很多。",
    )
    assert not MessageTemplates.is_usable_greeting(
        "morning",
        "早安，先喝口水缓一缓，今天会顺一点。",
    )
