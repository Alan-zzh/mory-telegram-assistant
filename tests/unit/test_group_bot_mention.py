from io import BytesIO
import inspect
from types import SimpleNamespace

from core.message_dispatcher import (
    DispatchContext,
    _do_dispatch_inner,
    _dispatch_first_group_mention_onboarding,
    _strip_direct_bot_mention,
)
from core.mory_bot import MoryBot
from core.start_welcome_card import send_start_welcome


def _message(*, uid=42, chat_id=-100, text="@Mory_Assistant_Bot"):
    return SimpleNamespace(
        text=text,
        message_id=77,
        from_user=SimpleNamespace(id=uid, first_name="小明", last_name="测试"),
        chat=SimpleNamespace(id=chat_id, type="supergroup", title="测试群"),
        reply_to_message=None,
    )


class _OnboardingDb:
    def __init__(self, delivered=False):
        self.delivered = delivered
        self.claims = []
        self.completed = []
        self.released = []

    def has_onboarding_delivery(self, uid, chat_id, surface):
        return self.delivered

    def claim_onboarding_delivery(self, uid, chat_id, surface):
        self.claims.append((uid, chat_id, surface))
        return True

    def complete_onboarding_delivery(self, uid, chat_id, surface):
        self.delivered = True
        self.completed.append((uid, chat_id, surface))
        return True

    def release_onboarding_delivery(self, uid, chat_id, surface):
        self.released.append((uid, chat_id, surface))
        return True


def _dispatch(db, mory_bot, ai=None):
    message = _message()
    ctx = SimpleNamespace(
        config={},
        db=db,
        bot=SimpleNamespace(),
        bot_username="mory_assistant_bot",
        bot_id=999,
        mory_bot=mory_bot,
        ai=ai,
    )
    return DispatchContext(
        ctx=ctx,
        msg=message,
        uid=42,
        uname="小明",
        chat_id=-100,
        is_priv=False,
        is_group=True,
        text="",
        bot_mentioned=True,
    )


def test_direct_bot_mention_is_case_insensitive_and_boundary_safe():
    assert _strip_direct_bot_mention(
        "@MORY_ASSISTANT_BOT 帮我查一下", "mory_assistant_bot"
    ) == ("帮我查一下", True)
    assert _strip_direct_bot_mention(
        "@mory_assistant_bot_backup 帮忙", "mory_assistant_bot"
    ) == ("@mory_assistant_bot_backup 帮忙", False)


def test_mory_bot_group_photo_reply_enters_cleanup_tracking():
    class _TeleBot:
        send_message = delete_message = send_chat_action = lambda *_a, **_k: None
        get_me = lambda *_a: SimpleNamespace(id=999)

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
    sent = wrapper.reply_photo_and_track(
        SimpleNamespace(chat=SimpleNamespace(id=-100), message_id=77),
        BytesIO(b"jpeg"),
        caption="我在",
    )
    assert sent.message_id == 88
    assert db.replies == [(88, -100, 77)]
    assert db.channels == [(-100, 88, "photo")]


def test_first_group_mention_uses_exact_private_start_delivery_and_zero_ai(monkeypatch):
    delivered = []

    class _ForbiddenAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("群首次 @ 不允许调用 AI")

    db = _OnboardingDb()
    dctx = _dispatch(db, SimpleNamespace(), ai=_ForbiddenAi())
    fake_delivery = SimpleNamespace(
        asset_name="mory_start_v3_04.jpg", degraded_to_text=False
    )

    def capture(bot, message, config, *, mory_bot, rng=None):
        delivered.append((bot, message, config, mory_bot, rng))
        return fake_delivery

    monkeypatch.setattr("core.start_welcome_card.send_start_welcome", capture)

    assert _dispatch_first_group_mention_onboarding(dctx) is True
    assert len(delivered) == 1
    assert delivered[0][1] is dctx.msg
    assert db.claims == [(42, -100, "group_mention")]
    assert db.completed == [(42, -100, "group_mention")]
    assert db.released == []


def test_first_group_mention_route_precedes_every_model_capable_path():
    source = inspect.getsource(_do_dispatch_inner)
    assert "if not skip_memory_summary:\n            check_and_trigger" in source
    onboarding = source.index("_dispatch_first_group_mention_onboarding(dctx)")
    intent = source.index("_dispatch_p3_6_intent_routing(dctx)")
    ai = source.index("_dispatch_p10_ai(dctx)")
    assert onboarding < intent < ai


def test_existing_group_onboarding_allows_normal_message_chain(monkeypatch):
    db = _OnboardingDb(delivered=True)
    called = []
    monkeypatch.setattr(
        "core.start_welcome_card.send_start_welcome",
        lambda *_args, **_kwargs: called.append(True),
    )

    assert _dispatch_first_group_mention_onboarding(
        _dispatch(db, SimpleNamespace())
    ) is False
    assert called == []
    assert db.claims == []


def test_failed_group_onboarding_releases_claim_and_blocks_ai(monkeypatch):
    db = _OnboardingDb()
    monkeypatch.setattr(
        "core.start_welcome_card.send_start_welcome",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("telegram down")),
    )

    assert _dispatch_first_group_mention_onboarding(
        _dispatch(db, SimpleNamespace())
    ) is True
    assert db.completed == []
    assert db.released == [(42, -100, "group_mention")]


def test_group_first_mention_delivery_has_private_start_caption_and_two_sales_buttons():
    captured = []

    class _MoryBot:
        def reply_photo_and_track(self, message, photo, **kwargs):
            captured.append((message, photo.read(16), kwargs))
            return SimpleNamespace(message_id=123)

    delivery = send_start_welcome(
        SimpleNamespace(),
        _message(),
        {},
        mory_bot=_MoryBot(),
    )

    assert delivery.delivered is True
    assert delivery.asset_name.startswith("mory_start_v3_")
    assert "小明" in delivery.caption
    assert "Mory" in delivery.caption
    assert len(captured) == 1
    kwargs = captured[0][2]
    assert kwargs["caption"] == delivery.caption
    buttons = kwargs["reply_markup"].keyboard[0]
    assert [button.url for button in buttons] == [
        "https://t.me/moryselect",
        "https://t.me/MorychannelBot",
    ]
