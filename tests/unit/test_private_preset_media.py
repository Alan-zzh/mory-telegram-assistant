from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.keyword_trigger import KeywordTrigger
from modules.private_preset_media import (
    MEDIA_ROOT,
    PHOTO_POOL,
    PrivatePresetMediaService,
)


EXPECTED_ASSET_HASHES = {
    "mory_self_portrait.png": "75ae1c5f9a3f8b946a8432f757e30818a329657b7970712c21ddbf7e1d4cf1fa",
    "original_taste_menu.png": "c9c11f4c388d93794d573c00b5c46372d46c8932c0e4b296f89d152d36f931fe",
    "photo_pool_01.png": "294f7263a832ac9e35e399c482ce262ebb6392db6c2a7c7d23026c687fc596a3",
    "photo_pool_02.png": "da0d2a1163b29b89dba07f335a94508d6c20f43baa1a3691a56b7f74d9679a13",
    "photo_pool_03.png": "24d6b2ff157d5d5f085b79481e658212475afa5a1a53f558e829f55758d4fbde",
    "photo_pool_04.png": "60efc4654e4ac50c5af87ed68018e5710319cff6b36385feaf6ca3440709c20a",
    "photo_pool_05.png": "232f5b7d0d640817a7002bc9241024e4e38d4fb1085a64af8c79928777f0d4d4",
    "photo_pool_06.png": "51c3b94a5e62203300f79f793bf2b3ce6f657c29895f3a91d38efa3bebf6d201",
    "photo_pool_07.png": "3452b22f89d47210199c156eaf2b439bdeb6cc8fd603b14514b4e24f4e379943",
}


class FakeDB:
    def __init__(self):
        self.states = {}

    def get_system_state(self, key, default=None):
        return self.states.get(key, default)

    def set_system_state(self, key, value):
        self.states[key] = str(value)

    def match_keyword_trigger(self, _text):
        return []

    def log_telemetry(self, *_args, **_kwargs):
        return None

    def record_business_context(self, *_args, **_kwargs):
        return None


class FakeMoryBot:
    def __init__(self, events=None, *, photo_result=True):
        self.events = events if events is not None else []
        self.photo_result = photo_result

    def reply_and_track(self, message, text, **kwargs):
        self.events.append(("text", text, kwargs))
        return SimpleNamespace(message_id=9001)

    def reply_photo_and_track(self, message, photo, **kwargs):
        self.events.append(("photo", Path(photo.name).name, kwargs, photo.read(8)))
        if not self.photo_result:
            return None
        return SimpleNamespace(message_id=9002)


class FailIfUsedAI:
    def ask(self, *_args, **_kwargs):
        raise AssertionError("私聊预设照片链不得调用 AI")


def _message(text="照片", *, message_id=11, user_id=22, chat_type="private"):
    chat_id = user_id if chat_type == "private" else -100
    return SimpleNamespace(
        text=text,
        message_id=message_id,
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        from_user=SimpleNamespace(id=user_id),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("原味", "original_taste"),
        ("订阅里有原味吗", "original_taste"),
        ("想看你本人的照片", "self_portrait"),
        ("给我一张你的真实图片", "self_portrait"),
        ("发张照片", "photo_random"),
        ("有照片吗", "photo_random"),
        ("不要原味", None),
        ("别发你的照片", None),
        ("照片挺好看", None),
        ("我喜欢这张图片", None),
    ],
)
def test_detect_scene_matches_final_source_contract(text, expected):
    assert PrivatePresetMediaService.detect_scene(text) == expected


def test_all_approved_source_assets_are_preserved_byte_for_byte():
    assert set(EXPECTED_ASSET_HASHES) == {
        item.name for item in MEDIA_ROOT.glob("*.png")
    }
    for name, expected_hash in EXPECTED_ASSET_HASHES.items():
        actual = hashlib.sha256((MEDIA_ROOT / name).read_bytes()).hexdigest()
        assert actual == expected_hash


def test_random_pool_avoids_consecutive_asset_and_duplicate_message():
    db = FakeDB()
    bot = FakeMoryBot()
    service = PrivatePresetMediaService(
        db, chooser=lambda items: items[0], cooldown_seconds=0, daily_limit=0
    )

    first = service.send_for_request(
        _message(message_id=101), bot, scene="photo_random"
    )
    duplicate = service.send_for_request(
        _message(message_id=101), bot, scene="photo_random"
    )
    second = service.send_for_request(
        _message(message_id=102), bot, scene="photo_random"
    )

    assert (first, duplicate, second) == ("sent", "duplicate", "sent")
    assert [event[1] for event in bot.events] == [PHOTO_POOL[0], PHOTO_POOL[1]]


def test_rate_limit_blocks_rapid_refire_and_daily_overflow():
    db = FakeDB()
    bot = FakeMoryBot()
    service = PrivatePresetMediaService(db, chooser=lambda items: items[0])

    assert service.send_for_request(
        _message(message_id=111), bot, scene="photo_random"
    ) == "sent"
    # 冷却期内换措辞重发（新 message_id）必须被拦截
    assert service.send_for_request(
        _message(message_id=112), bot, scene="photo_random"
    ) == "rate_limited"

    # 关闭冷却后，超过每日上限同样拦截（独立 DB，避免前段计数干扰）
    open_service = PrivatePresetMediaService(
        FakeDB(), chooser=lambda items: items[0], cooldown_seconds=0
    )
    results = []
    for mid in range(120, 130):
        results.append(open_service.send_for_request(
            _message(message_id=mid), bot, scene="photo_random"
        ))
    assert all(r == "sent" for r in results)
    assert open_service.send_for_request(
        _message(message_id=999), bot, scene="photo_random"
    ) == "rate_limited"


def test_failed_send_is_fail_closed_without_consuming_random_asset():
    db = FakeDB()
    service = PrivatePresetMediaService(db, chooser=lambda items: items[0])
    failing_bot = FakeMoryBot(photo_result=False)

    assert service.send_for_request(
        _message(message_id=201), failing_bot, scene="photo_random"
    ) == "failed"
    assert db.get_system_state("private_preset_media:last_asset:22", "") == ""
    assert service.send_for_request(
        _message(message_id=201), failing_bot, scene="photo_random"
    ) == "duplicate"


def test_direct_private_photo_request_is_zero_token_and_visible_photo():
    db = FakeDB()
    events = []
    mory_bot = FakeMoryBot(events)
    service = PrivatePresetMediaService(db, chooser=lambda items: items[0])
    trigger = KeywordTrigger(
        db,
        mory_bot,
        FailIfUsedAI(),
        {},
        private_preset_media=service,
    )
    message = _message("发张照片", message_id=301)

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        bot=SimpleNamespace(),
    ) is True
    assert events[0][0] == "photo"
    assert "caption" in events[0][2]
    assert "@moryselect" in events[0][2]["caption"]


def test_benefit_preset_keeps_text_then_appends_captionless_photo():
    db = FakeDB()
    events = []
    mory_bot = FakeMoryBot(events)
    service = PrivatePresetMediaService(db, chooser=lambda items: items[0])
    config = {
        "SPECIAL_AUTO_REPLIES": [
            {
                "name": "福利咨询",
                "topic": "福利",
                "enabled": True,
                "keywords": ["有什么福利"],
                "ai_polish": False,
                "conversion_target": "preview",
                "base_reply": "原有福利文字，去 @moryselect 看预览。",
            }
        ]
    }
    trigger = KeywordTrigger(
        db,
        mory_bot,
        FailIfUsedAI(),
        config,
        private_preset_media=service,
    )
    message = _message("有什么福利", message_id=401)

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        bot=SimpleNamespace(),
    ) is True
    assert [event[0] for event in events] == ["text", "photo"]
    assert events[0][1] == "原有福利文字，去 @moryselect 看预览。"
    assert "caption" not in events[1][2]


def test_original_taste_preset_keeps_rule_text_then_fixed_menu_without_caption():
    db = FakeDB()
    events = []
    mory_bot = FakeMoryBot(events)
    service = PrivatePresetMediaService(db)
    trigger = KeywordTrigger(
        db,
        mory_bot,
        None,
        {},
        private_preset_media=service,
    )
    message = _message("原味定制有什么规则", message_id=501)

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        bot=SimpleNamespace(),
    ) is True
    assert [event[0] for event in events] == ["text", "photo"]
    assert events[1][1] == "original_taste_menu.png"
    assert "caption" not in events[1][2]


def test_group_photo_request_does_not_enter_private_media_route():
    db = FakeDB()
    mory_bot = FakeMoryBot()
    service = PrivatePresetMediaService(db)
    trigger = KeywordTrigger(
        db,
        mory_bot,
        FailIfUsedAI(),
        {},
        private_preset_media=service,
    )
    message = _message("发张照片", message_id=601, chat_type="supergroup")

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        bot=SimpleNamespace(),
    ) is False
    assert mory_bot.events == []


def test_admin_private_message_does_not_trigger_preset_photo():
    db = FakeDB()
    mory_bot = FakeMoryBot()
    service = PrivatePresetMediaService(db)
    trigger = KeywordTrigger(
        db,
        mory_bot,
        FailIfUsedAI(),
        {},
        private_preset_media=service,
    )
    message = _message("发张照片", message_id=650)

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        bot=SimpleNamespace(),
        is_admin=True,
    ) is False
    assert mory_bot.events == []


def test_new_private_message_cancels_previous_delayed_reply(monkeypatch):
    from core import message_dispatcher

    timers = []

    class DeferredTimer:
        def __init__(self, _delay, callback):
            self.callback = callback
            self.daemon = False
            self.cancelled = False
            timers.append(self)

        def start(self):
            return None

        def cancel(self):
            self.cancelled = True

    class ActionBot:
        def send_chat_action(self, *_args, **_kwargs):
            return None

    message_dispatcher._cancel_pending_private_replies(22)
    monkeypatch.setattr(message_dispatcher.threading, "Timer", DeferredTimer)
    mory_bot = FakeMoryBot()
    message = _message("上一轮", message_id=701)

    message_dispatcher._delayed_reply(
        ActionBot(),
        message.chat.id,
        message,
        "不应晚到的旧回复",
        3,
        mory_bot,
        is_priv=True,
    )
    assert message_dispatcher._cancel_pending_private_replies(22) == 1
    assert timers[0].cancelled is True

    # 即使底层调度器在取消竞态中仍调用 callback，stop_event 也会阻断实发。
    timers[0].callback()
    assert mory_bot.events == []
