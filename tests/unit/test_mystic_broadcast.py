from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


_CST = timezone(timedelta(hours=8))


def _config(enabled=True):
    return {
        "GROUP_ID": -100123,
        "RICH_MESSAGE_ENABLED": True,
        "BROADCAST_FORMAT_VERSION": "rich",
        "MYSTIC_BROADCAST_CONFIG": {
            "enabled": enabled,
            "morning_time": "09:05",
            "morning_mode": "feng_shui",
            "afternoon_time": "13:05",
            "afternoon_mode": "tarot",
            "evening_time": "20:35",
            "evening_mode": "fortune",
            "legacy_targeted_tarot_enabled": False,
        },
    }


def test_mystic_content_is_daily_stable_and_has_three_distinct_columns():
    from tasks.support.mystic_content import (
        MYSTIC_NOTE,
        build_mystic_broadcast,
        is_usable_mystic_broadcast,
    )

    now = datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    expected = {
        "morning": ("feng_shui", "今日风水播报"),
        "afternoon": ("tarot", "今日塔罗播报"),
        "evening": ("fortune", "晚间宜忌播报"),
    }
    for period, (mode, title) in expected.items():
        first = build_mystic_broadcast(_config(), period, now)
        second = build_mystic_broadcast(_config(), period, now)
        assert first == second
        assert first["mode"] == mode
        assert first["title"] == title
        assert first["note"] == MYSTIC_NOTE
        assert is_usable_mystic_broadcast(first)
        visible = str(first)
        assert "新闻" not in visible
        assert "热搜" not in visible
        assert "@moryselect" not in visible.lower()
        assert "@morychannelbot" not in visible.lower()


def test_mystic_content_is_a_neutral_group_column_not_personal_coaching():
    from tasks.support.mystic_content import build_mystic_broadcast

    forbidden = (
        "给你的",
        "交给你",
        "自己",
        "内心",
        "情绪",
        "真正的选择",
        "自责",
        "写下一句",
    )
    now = datetime(2026, 7, 27, 13, 5, tzinfo=_CST)
    for period in ("morning", "afternoon", "evening"):
        payload = build_mystic_broadcast(_config(), period, now)
        visible = " ".join(
            [payload["title"]]
            + [f"{label} {value}" for label, value in payload["sections"]]
            + [payload["note"]]
        )
        assert all(marker not in visible for marker in forbidden)
        assert len(payload["sections"]) == 4
        assert payload["note"] == "每日随机参考，仅供娱乐，祝大家顺顺利利。"


def test_random_mode_changes_by_date_but_retry_same_day_is_stable():
    from tasks.support.mystic_content import build_mystic_broadcast

    cfg = _config()
    cfg["MYSTIC_BROADCAST_CONFIG"]["evening_mode"] = "random"
    days = [
        datetime(2026, 7, day, 20, 35, tzinfo=_CST)
        for day in range(20, 28)
    ]
    payloads = [build_mystic_broadcast(cfg, "evening", day) for day in days]
    assert len({payload["mode"] for payload in payloads}) >= 2
    assert build_mystic_broadcast(cfg, "evening", days[0]) == payloads[0]


def test_mystic_renderers_keep_sender_separate_and_have_no_sales_entry():
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
    rendered = [
        build_mystic_html(
            payload["title"], payload["sections"], payload["note"], payload["emoji"]
        ),
        build_rich_mystic_card_message(
            payload["title"], payload["sections"], payload["note"], payload["emoji"]
        ),
    ]
    for text in rendered:
        assert "@MoryMateBot" in text
        assert "新闻" not in text
        assert "下单" not in text
        assert "订阅" not in text
        assert "私聊" not in text


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


def test_rich_mystic_send_is_tracked(monkeypatch):
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
    monkeypatch.setattr(mystic_task, "schedule_auto_delete", lambda *args: events.append(("delete", args[2])))
    monkeypatch.setattr(
        telebot_compat,
        "send_rich_message_compat",
        lambda bot, gid, rich: events.append(("send", gid, rich)) or SimpleNamespace(message_id=88),
    )

    mystic_task.execute_mystic_broadcast_task(rm, "mystic_morning", "morning")

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
        "开启风水播报",
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
        "把早间风水时间改成8点",
        cfg,
        None,
        message,
        lambda: saved.append(True),
        mory_bot=mory_bot,
    )
    assert cfg["MYSTIC_BROADCAST_CONFIG"]["morning_time"] == "08:05"
    assert len(saved) == 2
