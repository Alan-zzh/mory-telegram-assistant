from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


_CST = timezone(timedelta(hours=8))


def _config(enabled=True, cta_enabled=True):
    return {
        "GROUP_ID": -100123,
        "RICH_MESSAGE_ENABLED": True,
        "BROADCAST_FORMAT_VERSION": "rich",
        "MYSTIC_BROADCAST_CONFIG": {
            "enabled": enabled,
            "cta_enabled": cta_enabled,
            "private_reply_enabled": False,
            "morning_time": "09:05",
            "morning_mode": "almanac",
            "afternoon_time": "13:05",
            "afternoon_mode": "tarot",
            "evening_time": "20:35",
            "evening_mode": "iching",
            "legacy_targeted_tarot_enabled": False,
        },
    }


def _visible_lines(payload):
    return [
        f"{label} {value}"
        for block in payload["blocks"]
        for label, value in block["lines"]
    ]


def test_three_period_products_are_fixed_daily_stable_and_usable():
    from tasks.support.mystic_content import (
        build_mystic_broadcast,
        is_usable_mystic_broadcast,
    )

    now = datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    expected = {
        "morning": ("almanac", "早间 · 今日黄历", "cnlunar-0.2.4"),
        "afternoon": ("tarot", "午间 · 三张塔罗", "curated-major-arcana-v1"),
        "evening": ("iching", "晚间 · 易经一卦", "king-wen-64-v1"),
    }
    for period, (mode, title, source) in expected.items():
        first = build_mystic_broadcast(_config(), period, now)
        second = build_mystic_broadcast(_config(), period, now)
        assert first == second
        assert first["mode"] == mode
        assert first["title"] == title
        assert first["source"] == source
        assert is_usable_mystic_broadcast(first)
        visible = str(first)
        assert "新闻" not in visible
        assert "热搜" not in visible


def test_real_almanac_contains_lunar_good_bad_and_calendar_details():
    from tasks.support.mystic_content import build_mystic_broadcast

    payload = build_mystic_broadcast(
        _config(),
        "morning",
        datetime(2026, 7, 27, 9, 5, tzinfo=_CST),
    )
    visible = " ".join(_visible_lines(payload))
    assert "农历丙午年 六月大十四" in payload["meta"]
    assert "壬寅日" in payload["meta"]
    assert "宜 嫁娶" in visible
    assert "忌 出行" in visible
    assert "冲煞 虎日冲猴" in visible
    assert "值日 危日 · 金贵 · 黄道日" in visible
    assert "星宿 心月狐" in visible
    assert "下一节气 · 立秋 · 8月7日" in visible
    assert "动土" in payload["insight"]


def test_tarot_draws_three_distinct_cards_with_positions_and_combined_reading():
    from tasks.support.mystic_content import build_mystic_broadcast

    payload = build_mystic_broadcast(
        _config(),
        "afternoon",
        datetime(2026, 7, 27, 13, 5, tzinfo=_CST),
    )
    rows = payload["blocks"][0]["lines"]
    assert [row[0] for row in rows] == ["主牌", "助力", "提醒"]
    assert len({row[1].split(" · ")[1] for row in rows}) == 3
    assert all(("正位" in value or "逆位" in value) for _, value in rows)
    assert "主导元素" == payload["blocks"][1]["lines"][0][0]
    assert "牌阵从" in payload["insight"]


def test_iching_has_all_patterns_and_moving_line_produces_changed_hexagram():
    from tasks.support.mystic_content import (
        _HEXAGRAM_BY_PATTERN,
        build_mystic_broadcast,
    )

    assert len(_HEXAGRAM_BY_PATTERN) == 64
    payload = build_mystic_broadcast(
        _config(),
        "evening",
        datetime(2026, 7, 27, 20, 35, tzinfo=_CST),
    )
    rows = dict(payload["blocks"][0]["lines"])
    assert rows["本卦"] != rows["之卦"]
    assert "第" in rows["动爻"] and "爻变" in rows["动爻"]
    assert "本卦看" in payload["insight"]


def test_cta_uses_unified_pool_and_can_be_disabled():
    """CTA 由统一组件生成：target 合法、label/image_label 强绑定、单按钮、可关闭。"""
    from core.broadcast_image_card import strip_visual_emoji
    from tasks.broadcast.mystic_broadcast_task import build_mystic_cta, build_mystic_cta_markup
    from tasks.support.mystic_content import build_mystic_broadcast

    now = datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    expected_urls = {
        "contact": "https://t.me/Moryfansbot",
        "preview": "https://t.me/moryselect",
        "subscribe": "https://t.me/MorychannelBot",
    }
    for period in ("morning", "afternoon", "evening"):
        payload = build_mystic_broadcast(_config(), period, now)
        # 旧第二套 CTA 已收敛：payload 不再自带 cta，由发送层统一生成并回填
        assert payload.get("cta") is None
        cta = build_mystic_cta(payload, config=_config())
        assert cta["target"] in expected_urls
        assert cta["label"]
        assert cta["url"] == expected_urls[cta["target"]]
        # 强绑定：图片卡文案必须由按钮文案 strip emoji 派生
        assert cta["image_label"] == strip_visual_emoji(cta["label"])
        markup = build_mystic_cta_markup(payload, config=_config())
        assert len(markup.keyboard) == 1
        assert len(markup.keyboard[0]) == 1
        button = markup.keyboard[0][0]
        assert button.text == cta["label"]
        assert button.url == cta["url"]

    no_cta = build_mystic_broadcast(
        _config(cta_enabled=False), "morning", now
    )
    cta_off = build_mystic_cta(no_cta, config=_config(cta_enabled=False))
    assert not cta_off.get("label")
    assert build_mystic_cta_markup(no_cta, config=_config(cta_enabled=False)) is None


def test_renderers_have_structured_layout_sender_and_matching_cta_copy():
    from core.broadcast_formatter import (
        build_mystic_html,
        build_rich_mystic_card_message,
    )
    from tasks.support.mystic_content import build_mystic_broadcast

    payload = build_mystic_broadcast(
        _config(),
        "afternoon",
        datetime(2026, 7, 27, 13, 5, tzinfo=_CST),
    )
    # 与发送层一致：统一 CTA 生成后回填 payload，正文 closing 与按钮同源
    from tasks.broadcast.mystic_broadcast_task import build_mystic_cta
    payload["cta"] = build_mystic_cta(payload, config=_config())
    html = build_mystic_html(payload)
    rich = build_rich_mystic_card_message(payload)
    for text in (html, rich):
        assert "@MoryMateBot" in text
        assert payload["cta"]["closing"] in text
        assert "新闻" not in text
        assert payload["cta"]["url"] not in text
        assert "不替代现实判断" not in text
        assert "传统民俗参考" not in text
        assert "不作确定性断言" not in text
    assert "<h2>" in rich
    assert rich.count("<h3>") == len(payload["blocks"])
    assert "<blockquote>" in rich
    assert "<footer>@MoryMateBot</footer>" in rich


def test_private_mystic_requests_are_local_daily_and_topic_aware():
    from tasks.support.mystic_content import (
        build_private_mystic_reply,
        resolve_private_mystic_mode,
    )

    day1 = datetime(2026, 7, 27, 16, 0, tzinfo=_CST)
    day2 = datetime(2026, 7, 28, 16, 0, tzinfo=_CST)
    cases = {
        "帮我看看风水": ("almanac", "🧭 你的今日风水参考"),
        "给我抽一下塔罗看感情": ("tarot", "🔮 你的三张牌阵"),
        "想算卦问工作": ("iching", "☯️ 为你起一卦"),
        "/tarot 感情": ("tarot", "🔮 你的三张牌阵"),
        "/iching@MoryMateBot 工作": ("iching", "☯️ 为你起一卦"),
    }
    for text, (mode, title) in cases.items():
        assert resolve_private_mystic_mode(text) == mode
        first = build_private_mystic_reply(text, 42, day1)
        retry = build_private_mystic_reply(text, 42, day1)
        assert first == retry
        assert first["mode"] == mode
        assert first["token_usage"] == 0
        assert first["text"].startswith(title)
        assert "不替代" not in first["text"]
        assert "传统民俗参考" not in first["text"]
        assert "不作确定性断言" not in first["text"]

    assert build_private_mystic_reply("想算卦问工作", 42, day1) != (
        build_private_mystic_reply("想算卦问工作", 42, day2)
    )
    assert build_private_mystic_reply("想算卦问工作", 42, day1) != (
        build_private_mystic_reply("想算卦问感情", 42, day1)
    )


def test_private_mystic_intent_does_not_hijack_general_discussion():
    from tasks.support.mystic_content import resolve_private_mystic_mode

    for text in (
        "塔罗是不是一种心理投射",
        "你怎么看易经",
        "这家店的风水说法可信吗",
        "今天看到一篇占卜文章",
        "方位这个词怎么解释",
    ):
        assert resolve_private_mystic_mode(text) is None


def test_mystic_schedule_replaces_news_and_legacy_targeted_tarot_is_off():
    from tasks.broadcast.mystic_broadcast_task import MysticBroadcastTask
    from tasks.broadcast.tarot_task import TarotTask

    rm = SimpleNamespace(config=_config())
    schedule = MysticBroadcastTask(rm).schedule()
    assert [item["job_id"] for item in schedule] == [
        "mystic_morning",
        "mystic_afternoon",
        "mystic_evening",
    ]
    assert all("news" not in item["job_id"] for item in schedule)
    assert TarotTask(rm).schedule() == []


def test_disabled_mystic_task_does_not_claim_or_send(monkeypatch):
    import tasks.broadcast.mystic_broadcast_task as mystic_task

    called = []

    class FailTransaction:
        def __init__(self, *args, **kwargs):
            called.append("claimed")

    rm = SimpleNamespace(config=_config(enabled=False))
    monkeypatch.setattr(mystic_task, "TaskTransactionManager", FailTransaction)
    mystic_task.execute_mystic_broadcast_task(rm, "mystic_morning", "morning")
    assert called == []


def test_rich_mystic_send_and_single_markup_are_tracked(monkeypatch):
    import core.telebot_compat as telebot_compat
    import tasks.broadcast.mystic_broadcast_task as mystic_task

    events = []

    class FakeTransaction:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return SimpleNamespace(claimed=True)

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeDb:
        def track_channel_message(self, chat_id, message_id, content_type):
            events.append(("channel", chat_id, message_id, content_type))

        def track_bot_message(self, chat_id, message_id):
            events.append(("bot", chat_id, message_id))

        def track_broadcast(self, chat_id, category, message_id):
            events.append(("broadcast", chat_id, category, message_id))

    @contextmanager
    def locked(_name):
        yield

    rm = SimpleNamespace(
        config=_config(),
        db=FakeDb(),
        bot=object(),
        locked=locked,
    )
    monkeypatch.setattr(mystic_task, "TaskTransactionManager", FakeTransaction)
    monkeypatch.setattr(
        mystic_task,
        "schedule_auto_delete",
        lambda *args: events.append(("delete", args[2])),
    )

    def fake_send(bot, gid, rich, **kwargs):
        markup = kwargs["reply_markup"]
        events.append(("send", gid, rich, len(markup.keyboard)))
        return SimpleNamespace(message_id=88)

    monkeypatch.setattr(telebot_compat, "send_rich_message_compat", fake_send)
    mystic_task.execute_mystic_broadcast_task(
        rm, "mystic_morning", "morning"
    )

    assert any(event[:2] == ("send", -100123) for event in events)
    assert ("channel", -100123, 88, "text") in events
    assert ("bot", -100123, 88) in events
    assert ("broadcast", -100123, "mystic", 88) in events


def test_natural_admin_toggle_and_time_update_mystic_config():
    from modules.natural_cmd import _handle_modify_number, _handle_toggle

    replies = []
    saved = []
    mory_bot = SimpleNamespace(
        reply_and_track=lambda _message, text: replies.append(text)
    )
    message = SimpleNamespace(text="")
    cfg = {
        "AUTO_NEWS": True,
        "NEWS_BROADCAST_CONFIG": {"enabled": True},
        "MYSTIC_BROADCAST_CONFIG": {
            "enabled": False,
            "morning_time": "09:05",
        },
    }

    assert _handle_toggle(
        "开启传统文化播报",
        cfg,
        None,
        message,
        lambda: saved.append(True),
        mory_bot=mory_bot,
    )
    assert cfg["MYSTIC_BROADCAST_CONFIG"]["enabled"] is True
    assert cfg["NEWS_BROADCAST_CONFIG"]["enabled"] is False
    assert cfg["AUTO_NEWS"] is False

    assert _handle_modify_number(
        "把早间黄历时间改成8点",
        cfg,
        None,
        message,
        lambda: saved.append(True),
        mory_bot=mory_bot,
    )
    assert cfg["MYSTIC_BROADCAST_CONFIG"]["morning_time"] == "08:05"
    assert len(saved) == 2
