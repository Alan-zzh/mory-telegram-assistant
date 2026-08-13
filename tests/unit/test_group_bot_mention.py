from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.handlers.ai_reply_handler import _dispatch_p10_ai
from core.message_dispatcher import _strip_direct_bot_mention
from core.mory_bot import MoryBot
from core.start_welcome_card import build_group_mention_caption


def test_direct_bot_mention_is_case_insensitive_and_boundary_safe():
    assert _strip_direct_bot_mention(
        "@MORY_ASSISTANT_BOT 帮我查一下", "mory_assistant_bot"
    ) == ("帮我查一下", True)
    assert _strip_direct_bot_mention(
        "请问@mory_assistant_bot，这个怎么处理", "mory_assistant_bot"
    ) == ("请问 ，这个怎么处理", True)
    assert _strip_direct_bot_mention(
        "@mory_assistant_bot_backup 帮忙", "mory_assistant_bot"
    ) == ("@mory_assistant_bot_backup 帮忙", False)


def test_group_mention_copy_pool_is_random_business_assistant_copy():
    class _EachChoice:
        def __init__(self):
            self.index = 0

        def choice(self, items):
            item = items[self.index % len(items)]
            self.index += 1
            return item

    rng = _EachChoice()
    replies = [build_group_mention_caption("小明", rng=rng) for _ in range(4)]
    assert len(set(replies)) == 4
    for reply in replies:
        assert "小明" in reply
        assert "直接" in reply or "问题" in reply
        assert not any(word in reply for word in ("想聊", "陪聊", "订阅", "预览"))


def test_mory_bot_group_photo_reply_enters_cleanup_tracking():
    class _TeleBot:
        def send_message(self, *_args, **_kwargs):
            return None

        def delete_message(self, *_args, **_kwargs):
            return None

        def get_me(self):
            return SimpleNamespace(id=999)

        def send_chat_action(self, *_args, **_kwargs):
            return None

        def send_photo(self, chat_id, photo, **kwargs):
            assert chat_id == -100
            assert kwargs["reply_to_message_id"] == 77
            return SimpleNamespace(message_id=88)

    class _Db:
        def __init__(self):
            self.replies = []
            self.channels = []

        def track_reply(self, *args):
            self.replies.append(args)

        def track_channel_message(self, *args):
            self.channels.append(args)

    db = _Db()
    wrapper = MoryBot(_TeleBot(), db, {})
    message = SimpleNamespace(chat=SimpleNamespace(id=-100), message_id=77)

    sent = wrapper.reply_photo_and_track(message, BytesIO(b"jpeg"), caption="我在")

    assert sent.message_id == 88
    assert db.replies == [(88, -100, 77)]
    assert db.channels == [(-100, 88, "photo")]


def test_pure_group_mention_sends_random_photo_card_without_sales_buttons(monkeypatch):
    sent = []

    class _MoryBot:
        def reply_photo_and_track(self, message, photo, **kwargs):
            sent.append((message, photo, kwargs))
            return SimpleNamespace(message_id=123)

        def reply_and_track(self, *_args, **_kwargs):
            raise AssertionError("图片成功时不应重复发送文字")

    class _Ai:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("纯点名不应调用模型")

    message = SimpleNamespace(
        text="@Mory_Assistant_Bot",
        message_id=77,
        from_user=SimpleNamespace(id=42, first_name="小明"),
        chat=SimpleNamespace(id=-100, type="supergroup"),
        reply_to_message=None,
    )
    context = SimpleNamespace(
        config={"REPLY_CHANCE": 0},
        db=SimpleNamespace(),
        bot=SimpleNamespace(),
        bot_username="mory_assistant_bot",
        bot_id=999,
        mory_bot=_MoryBot(),
        ai=_Ai(),
    )
    dispatch = SimpleNamespace(
        msg=message,
        ctx=context,
        text="",
        bot_mentioned=True,
        uid=42,
        uname="小明",
        chat_id=-100,
        is_priv=False,
        is_group=True,
        conversation_history=[],
        _analysis={"mode": "normal"},
    )
    card = SimpleNamespace(
        stream=BytesIO(b"jpeg"),
        asset_name="mory_start_v2_01.jpg",
    )
    monkeypatch.setattr(
        "core.start_welcome_card.build_start_welcome_card", lambda *_args: card
    )
    monkeypatch.setattr(
        "core.start_welcome_card.build_group_mention_caption",
        lambda *_args: "小明，我在。事情直接发来。",
    )

    _dispatch_p10_ai(dispatch)

    assert len(sent) == 1
    assert sent[0][1] is card.stream
    assert sent[0][2] == {"caption": "小明，我在。事情直接发来。"}
    assert "reply_markup" not in sent[0][2]


def test_group_mention_with_question_forces_ai_and_hides_bot_username(monkeypatch):
    delayed = []

    class _Ai:
        def __init__(self):
            self.inputs = []

        def ask(self, text, **_kwargs):
            self.inputs.append(text)
            return "这件事可以这样处理。"

    ai = _Ai()
    message = SimpleNamespace(
        text="@Mory_Assistant_Bot 这件事怎么处理",
        message_id=78,
        from_user=SimpleNamespace(id=43, first_name="小林"),
        chat=SimpleNamespace(id=-100, type="supergroup", title="测试群"),
        reply_to_message=None,
    )
    db = MagicMock()
    db.get_conversion_state.return_value = {}
    db.users.get_conversation_turn.return_value = 0
    db.users.get_user_persona_profile.return_value = None
    db.get_user_consult_count.return_value = 0
    context = SimpleNamespace(
        config={
            "REPLY_CHANCE": 0,
            "GROWTH_OPTIMIZER_ENABLED": False,
            "FAQ_TRACKING_ENABLED": False,
            "FAQ_AUTO_REPLY_ENABLED": False,
            "RELAY_MODE_ENABLED": False,
        },
        db=db,
        bot=SimpleNamespace(send_chat_action=lambda *_args, **_kwargs: None),
        bot_username="mory_assistant_bot",
        bot_id=999,
        mory_bot=SimpleNamespace(),
        ai=ai,
    )
    dispatch = SimpleNamespace(
        msg=message,
        ctx=context,
        text="这件事怎么处理",
        bot_mentioned=True,
        uid=43,
        uname="小林",
        chat_id=-100,
        is_priv=False,
        is_group=True,
        conversation_history=[],
        intent={"intent": "consult", "source": "intent_router"},
        _analysis={"mode": "normal"},
    )
    monkeypatch.setattr("modules.content.is_late_night", lambda: False)
    monkeypatch.setattr(
        "core.message_dispatcher._delayed_reply",
        lambda _bot, _chat_id, _msg, text, *_args, **_kwargs: delayed.append(text),
    )
    monkeypatch.setattr(
        "core.message_dispatcher._calc_humanized_delay", lambda *_args, **_kwargs: 0
    )
    monkeypatch.setattr(
        "core.growth_optimizer.get_conversion_state", lambda *_args: {}
    )
    monkeypatch.setattr(
        "core.growth_optimizer.persist_conversion_decision", lambda *_args: None
    )
    monkeypatch.setattr(
        "core.growth_optimizer.resolve_conversion_target",
        lambda *_args, **_kwargs: ("none", "ordinary_chat"),
    )
    monkeypatch.setattr(
        "core.handlers.ai_reply_handler._should_offer_proactive_preview",
        lambda **_kwargs: False,
    )

    _dispatch_p10_ai(dispatch)

    assert ai.inputs == ["这件事怎么处理"]
    assert delayed == ["这件事可以这样处理。"]
    assert "@mory_assistant_bot" not in ai.inputs[0].lower()
