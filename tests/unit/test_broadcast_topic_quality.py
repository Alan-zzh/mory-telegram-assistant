# -*- coding: utf-8 -*-
"""播报排版、话题润色与监控误报回归测试。"""

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace


def test_news_internal_source_labels_never_render():
    from core.broadcast_formatter import (
        build_rich_news_card_message,
        build_rich_news_html,
    )

    news = "\n".join(
        [f"第{i}条真实新闻" for i in range(1, 6)]
        + ["💡 信息还在继续变化"]
    )
    for renderer in (build_rich_news_html, build_rich_news_card_message):
        rendered = renderer("早间", news, source_name="fallback")
        assert "多源汇总" not in rendered
        assert "均衡筛选" not in rendered
        assert "TrendRadar" not in rendered
        assert "@MoryMateBot" in rendered
        assert "@MorychannelBot" not in rendered


def test_news_personas_require_five_headlines_before_observation():
    from core.ai_engine import AIEngine

    for mode in (
        "news",
        "afternoon_news",
        "evening_news",
        "trendradar_morning_news",
        "trendradar_noon_news",
        "trendradar_evening_news",
    ):
        prompt = AIEngine._DEFAULT_PROMPT_TEMPLATES[mode]
        assert "严格只写5条" in prompt
        assert "第6行" in prompt
        assert "从10条候选中" in prompt
        assert "观察必须点名" in prompt
        assert "严格只写10条" not in prompt
        assert "第11行" not in prompt


def test_legacy_ten_item_news_override_cannot_replace_five_item_contract():
    from core.ai_engine import AIEngine

    engine = object.__new__(AIEngine)
    engine.config = {
        "PROMPT_TEMPLATES": {
            "news": "旧模板：严格只写10条，第11行总结。",
        }
    }

    persona, full_replacement = engine._get_mode_persona(
        "news",
        seed=123,
        news_content="十条真实标题",
    )

    assert full_replacement is True
    assert "严格只写5条" in persona
    assert "第6行" in persona
    assert "从10条候选中" in persona
    assert "严格只写10条" not in persona


def test_news_output_gate_rejects_source_labels_and_missing_items():
    from tasks.support.common import is_usable_news_output

    valid = "\n".join(
        [f"第{i}条综合头条已经讲清事实和影响" for i in range(1, 6)]
        + ["💡 综合头条里的事实和影响还要继续看"]
    )
    leaked = valid.replace(
        "第1条综合头条已经讲清事实和影响",
        "【社会·NewsNow澎湃】第1条综合头条已经讲清事实和影响",
    )
    missing = "\n".join(valid.splitlines()[:4] + [valid.splitlines()[-1]])
    overlong = "\n".join(
        [f"第{i}条旧版长新闻输出" for i in range(1, 11)]
        + ["旧版第十一行观察"]
    )

    assert is_usable_news_output(
        valid,
        expected_count=5,
        source_lines=valid.splitlines()[:5],
    ) is True
    assert is_usable_news_output(leaked, expected_count=5) is False
    assert is_usable_news_output(missing, expected_count=5) is False
    assert is_usable_news_output(overlong, expected_count=5) is False


def test_news_output_gate_rejects_generic_observation_unrelated_to_headlines():
    """第6行必须复盘本卡片的具体实体或事件，不能放万能空话。"""
    from tasks.support.common import is_usable_news_output

    headlines = [
        "携程因垄断被罚没超五十亿元，平台整改与用户权益保障成焦点",
        "中东战争风险积聚美或两线作战，地区局势外溢效应值得持续警惕",
        "南岸情书在链条征百分之十税，高净值人群资产配置逻辑生变",
        "王小洪会见美联邦调查局局长，中美执法合作释放务实沟通信号",
        "基层干部服务群众本领被强调，治理效能提升关键在落地执行",
    ]
    generic = "\n".join(
        headlines + ["民生与国际议题交织，午间资讯折射现实关切"]
    )
    grounded = "\n".join(
        headlines + ["平台整改与中东局势，是这轮最该继续盯的两条线"]
    )

    assert is_usable_news_output(
        generic,
        expected_count=5,
        source_lines=headlines,
    ) is False
    assert is_usable_news_output(
        grounded,
        expected_count=5,
        source_lines=headlines,
    ) is True


def test_news_fallback_observation_uses_complete_headline_clauses():
    from tasks.support.common import build_news_without_ai

    copy = build_news_without_ai(
        [
            "携程因垄断被罚没超五十亿元，平台合规整改成焦点",
            "中东局势风险继续积聚，多方关注外溢影响",
            "基层服务能力被再次强调，后续看治理落地",
            "中美执法合作释放信号，双方保持务实沟通",
            "资产配置逻辑出现变化，高净值人群重新评估",
        ],
        "午间",
    )

    assert "先盯这两件事：携程因垄断被罚没超五十亿元；中东局势风险继续积聚" in copy
    assert "，；" not in copy


def test_news_source_chain_skips_partial_result_when_next_source_has_ten(monkeypatch):
    import core.trendradar_news as news_sources
    import tasks.support.common as common

    partial = "\n".join(f"{i}. 部分新闻{i}" for i in range(1, 7))
    complete = "\n".join(f"{i}. 完整新闻{i}" for i in range(1, 11))
    monkeypatch.setattr(news_sources, "fetch_real_news", lambda: partial)
    monkeypatch.setattr(news_sources, "fetch_trendradar_news", lambda: complete)
    monkeypatch.setattr(common, "_news_pushed_today", set())

    lines, source_name = common.get_preferred_news_lines(
        "早间",
        {"NEWS_BROADCAST_CONFIG": {"preferred_source": "real_first"}},
    )

    assert source_name == "trendradar"
    assert len(lines) == 10


def test_news_source_chain_never_sends_underfilled_card(monkeypatch):
    import core.trendradar_news as news_sources
    import tasks.support.common as common

    partial = "\n".join(f"{i}. 同一条部分新闻{i}" for i in range(1, 7))
    monkeypatch.setattr(news_sources, "fetch_real_news", lambda: partial)
    monkeypatch.setattr(news_sources, "fetch_trendradar_news", lambda: partial)
    monkeypatch.setattr(common, "_news_pushed_today", set())

    lines, source_name = common.get_preferred_news_lines(
        "晚间",
        {"NEWS_BROADCAST_CONFIG": {"preferred_source": "real_first"}},
    )

    assert lines == []
    assert source_name == "none"


def test_polling_exception_handler_only_handles_get_updates_5xx(monkeypatch):
    from core.telebot_compat import TelegramPollingExceptionHandler

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
        "morning": ("☀️ 和 Mory 说早安", "https://t.me/Moryfansbot"),
        "afternoon": ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
        "evening": ("🌙 找 Mory 聊聊", "https://t.me/Moryfansbot"),
        "news": ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
    }

    for period, (text, url) in expected.items():
        markup = build_mory_contact_markup(period)
        button = markup.keyboard[0][0]
        assert (button.text, button.url) == (text, url)


def test_scheduled_broadcast_example_alternates_contact_and_self_service():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    buttons = {
        item["id"]: (item["button_text"], item["button_url"])
        for item in config["SCHEDULED_BROADCASTS"]
    }

    assert buttons == {
        "morning_nudge": ("☀️ 和 Mory 说早安", "https://t.me/Moryfansbot"),
        "afternoon_tease": ("🛒 自助下单 / 订阅", "https://t.me/MorychannelBot"),
        "evening_warm": ("🌙 找 Mory 聊聊", "https://t.me/Moryfansbot"),
        "night_hook": ("✨ 自助查看订阅", "https://t.me/MorychannelBot"),
    }


def test_custom_topic_contacts_mory_while_welfare_stays_self_service():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    topics = {
        item["topic"]: item
        for item in config["SPECIAL_AUTO_REPLIES"]
    }

    assert "@MorychannelBot" in topics["福利"]["required_terms"]
    assert "@Moryfansbot" in topics["定制"]["required_terms"]
    assert "@MorychannelBot" not in topics["定制"]["required_terms"]
    assert "@Moryfansbot" in topics["定制"]["base_reply"]


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


def test_greeting_fallbacks_are_fan_group_copy_not_task_coaching():
    from tasks.support.message_templates import MessageTemplates

    technical_markers = ("多线程", "任务", "待办", "通知", "窗口", "效率", "开机")
    for pool in MessageTemplates.GREETING_FALLBACK_POOL.values():
        for copy in pool:
            assert not any(marker in copy for marker in technical_markers)
            assert any(marker in copy for marker in ("你们", "群里", "大家", "我"))
