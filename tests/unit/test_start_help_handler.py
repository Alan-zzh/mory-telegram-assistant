from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from core.handlers import start_help_handler
from core.start_welcome_card import (
    build_start_welcome_caption,
    build_start_welcome_card,
    build_start_welcome_markup,
)


class _Bot:
    def __init__(self):
        self.sent = []
        self.photos = []
        self.replied = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))

    def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append((chat_id, photo, kwargs))

    def reply_to(self, message, text):
        self.replied.append((message.chat.id, text))


def _message(*, uid=101, chat_id=101, chat_type="private", text="/start"):
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        from_user=SimpleNamespace(id=uid, first_name="DarkDesire", last_name=""),
    )


def test_private_start_for_regular_user_sends_business_card_without_ai_route(monkeypatch):
    bot = _Bot()
    message = _message(uid=101)
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == []
    assert bot.sent == []
    assert bot.replied == []
    assert len(bot.photos) == 1
    chat_id, photo, kwargs = bot.photos[0]
    assert chat_id == 101
    assert isinstance(photo, BytesIO)
    assert "DarkDesire" in kwargs["caption"]
    assert "直接" in kwargs["caption"]
    assert "送达" in kwargs["caption"]
    assert not any(word in kwargs["caption"] for word in ("想聊", "陪聊", "单纯聊"))
    buttons = kwargs["reply_markup"].keyboard[0]
    assert [button.url for button in buttons] == [
        "https://t.me/moryselect",
        "https://t.me/MorychannelBot",
    ]


def test_start_welcome_card_contains_dynamic_name_date_and_valid_jpeg():
    class _FirstChoice:
        @staticmethod
        def choice(items):
            return items[0]

    cst = timezone(timedelta(hours=8))
    card = build_start_welcome_card(
        "DarkDesire",
        now=datetime(2026, 8, 14, 9, 30, tzinfo=cst),
        rng=_FirstChoice(),
    )

    assert card.asset_name == "mory_start_v3_00.jpg"
    assert card.display_name == "DarkDesire"
    assert card.date_text == "2026年8月14日"
    with Image.open(card.stream) as image:
        assert image.format == "JPEG"
        assert image.size == (960, 480)


def test_start_welcome_copy_pool_is_business_assistant_only():
    class _EachChoice:
        def __init__(self):
            self.index = 0

        def choice(self, items):
            item = items[self.index % len(items)]
            self.index += 1
            return item

    rng = _EachChoice()
    replies = [build_start_welcome_caption("小明", rng=rng) for _ in range(4)]
    assert len(set(replies)) == 4
    for reply in replies:
        assert "Mory" in reply
        assert "处理" in reply
        assert "转达" in reply
        assert "是否送达" in reply or "送达结果" in reply or "有没有送达" in reply
        assert not any(word in reply for word in ("想聊", "陪聊", "单纯聊"))


def test_start_welcome_markup_keeps_preview_then_subscribe():
    markup = build_start_welcome_markup()
    buttons = markup.keyboard[0]
    assert len(buttons) == 2
    assert buttons[0].url == "https://t.me/moryselect"
    assert buttons[1].url == "https://t.me/MorychannelBot"


def test_start_welcome_markup_randomizes_both_button_labels_without_changing_targets():
    class _EachChoice:
        def __init__(self):
            self.index = 0

        def choice(self, items):
            item = items[self.index % len(items)]
            self.index += 1
            return item

    rng = _EachChoice()
    pairs = []
    for _ in range(4):
        markup = build_start_welcome_markup(rng=rng)
        pairs.append(tuple(button.text for button in markup.keyboard[0]))
        assert [button.url for button in markup.keyboard[0]] == [
            "https://t.me/moryselect",
            "https://t.me/MorychannelBot",
        ]

    assert len({pair[0] for pair in pairs}) == 4
    assert len({pair[1] for pair in pairs}) == 4


def test_start_welcome_uses_exactly_six_local_templates():
    from core import start_welcome_card

    assets = sorted(start_welcome_card._ASSET_DIR.glob(start_welcome_card._ASSET_PATTERN))
    assert [item.name for item in assets] == [
        f"mory_start_v3_{index:02d}.jpg" for index in range(6)
    ]


def test_private_start_keeps_business_entry_when_image_card_fails(monkeypatch):
    bot = _Bot()
    message = _message(uid=101)
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})

    monkeypatch.setattr(
        "core.start_welcome_card.build_start_welcome_card",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("image unavailable")),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert bot.photos == []
    assert len(bot.sent) == 1
    _chat_id, text, kwargs = bot.sent[0]
    assert "Mory" in text
    assert "直接" in text
    assert len(kwargs["reply_markup"].keyboard[0]) == 2


def test_private_start_for_admin_keeps_group_management_onboarding(monkeypatch):
    bot = _Bot()
    message = _message(uid=999)
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == []
    assert len(bot.sent) == 1
    assert "给我管理员权限" in bot.sent[0][1]


def test_group_start_keeps_short_group_guidance(monkeypatch):
    bot = _Bot()
    message = _message(uid=101, chat_id=-1001, chat_type="supergroup")
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})
    routed = []

    monkeypatch.setattr(
        "core.message_dispatcher.master_handler",
        lambda routed_message, routed_ctx: routed.append((routed_message, routed_ctx)),
    )

    start_help_handler.handle_start_command(bot, message, ctx)

    assert routed == []
    assert bot.sent == []
    assert len(bot.replied) == 1
    assert "@我" in bot.replied[0][1]


def test_private_help_does_not_leak_admin_commands_to_regular_user():
    bot = _Bot()
    message = _message(uid=101, text="/help")
    ctx = SimpleNamespace(config={"ADMIN_IDS": [999]})

    start_help_handler.handle_help_command(bot, message, ctx)

    assert len(bot.sent) == 1
    assert "用户命令清单" in bot.sent[0][1]
    assert "管理员命令清单" not in bot.sent[0][1]
