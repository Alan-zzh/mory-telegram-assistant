# -*- coding: utf-8 -*-
"""入群资料审核回归：覆盖截图账号、延迟 Bio 与正常语境。"""

from types import SimpleNamespace


class _User:
    def __init__(self, first_name, uid=614825577, username="dsmdwiha"):
        self.id = uid
        self.first_name = first_name
        self.last_name = ""
        self.username = username
        self.emoji_status_custom_emoji_id = ""


class _Bot:
    def __init__(self, bio=""):
        self.bio = bio
        self.sent = []
        self.restricted = []

    def get_chat(self, uid):
        return SimpleNamespace(bio=self.bio, emoji_status_custom_emoji_id="")

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))

    def restrict_chat_member(self, *args, **kwargs):
        self.restricted.append((args, kwargs))


class _StatusBot(_Bot):
    def get_custom_emoji_stickers(self, custom_emoji_ids):
        return [
            SimpleNamespace(
                emoji="",
                set_name="看我简介",
                custom_emoji_id=custom_emoji_ids[0],
                thumbnail=None,
            )
        ]


class _DB:
    def __init__(self, blacklisted=False):
        self.upserts = []
        self.blacklisted = blacklisted

    def upsert_group_member(self, *args):
        self.upserts.append(args)

    def is_blacklisted(self, uid):
        return self.blacklisted


def test_screenshot_display_name_variants_are_high_confidence_ads():
    from modules.ad_profile_signals import detect_profile_ad_signal

    for name in ("白虎一线天", "白虎_一线天", "白虎 · 一线天"):
        result = detect_profile_ad_signal(None, _User(name), "", {})
        assert result["is_ad"] is True, name
        assert result["score"] == 3


def test_white_tiger_and_scenic_normal_contexts_are_not_blocked():
    from modules.ad_profile_signals import detect_profile_ad_signal

    for name in ("白虎是四象神兽", "一线天景区明天开放", "白虎山一线天景点"):
        result = detect_profile_ad_signal(None, _User(name), "", {})
        assert result["is_ad"] is False, name


def test_name_bio_and_premium_icon_hits_share_unified_enforcement(monkeypatch):
    from core.handlers import member_handlers

    cases = [
        (_Bot(""), _User("白虎一线天"), ""),
        (
            _Bot(""),
            _User("普通昵称"),
            "同城母狗资源，包实战落地：https://t.me/+ij5Yv6mJ0hdlM2Vk",
        ),
        (_StatusBot(""), _User("普通昵称"), ""),
    ]
    cases[2][1].emoji_status_custom_emoji_id = "status-ad"
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )

    for bot, user, bio in cases:
        assert member_handlers._review_member_profile(
            bot, user, bio, {}, object(), -1003004701688
        ) is True

    assert len(enforced) == 3


def test_new_member_profile_block_stops_before_avatar_captcha_and_welcome(monkeypatch):
    from core.handlers import member_handlers
    from modules import anti_raid, emoji_mask_detector, federation, spam_watch, welcome_customization

    bot = _Bot(bio="")
    db = _DB()
    user = _User("白虎_一线天")
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        new_chat_members=[user],
        from_user=user,
    )
    enforced = []
    avatar_calls = []
    welcome_calls = []

    monkeypatch.setattr(anti_raid, "check_raid", lambda *args, **kwargs: False)
    monkeypatch.setattr(spam_watch, "check_user_spam", lambda *args, **kwargs: False)
    monkeypatch.setattr(federation, "execute_fban_on_join", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        emoji_mask_detector,
        "check_emoji_mask_in_username",
        lambda *args, **kwargs: (False, ""),
    )
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(
        member_handlers,
        "_review_member_avatar",
        lambda *args, **kwargs: avatar_calls.append(True) or False,
    )
    monkeypatch.setattr(
        welcome_customization,
        "send_welcome_message",
        lambda *args, **kwargs: welcome_calls.append(True),
    )

    member_handlers._handle_new_chat_members(
        bot,
        message,
        {"VERIFICATION_CONFIG": {"enable": True}},
        db,
    )

    assert len(enforced) == 1
    assert avatar_calls == []
    assert bot.sent == []
    assert bot.restricted == []
    assert welcome_calls == []


def test_existing_blacklist_rejoin_stops_before_all_admission_steps(monkeypatch):
    from core.handlers import member_handlers

    bot = _Bot()
    db = _DB(blacklisted=True)
    user = _User("换名后的广告号")
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        new_chat_members=[user],
        from_user=user,
    )
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )

    member_handlers._handle_new_chat_members(
        bot,
        message,
        {"VERIFICATION_CONFIG": {"enable": True}},
        db,
    )

    assert len(enforced) == 1
    assert bot.sent == []
    assert bot.restricted == []


def test_verification_release_rechecks_delayed_bio_and_blocks(monkeypatch):
    from core.handlers import member_handlers

    bio = "同城母狗资源，包实战落地：https://t.me/+ij5Yv6mJ0hdlM2Vk"
    bot = _Bot(bio=bio)
    db = _DB()
    user = _User("普通昵称")
    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        old_chat_member=SimpleNamespace(status="restricted", user=user),
        new_chat_member=SimpleNamespace(status="member", user=user),
    )
    enforced = []
    avatar_calls = []

    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(
        member_handlers,
        "_review_member_avatar",
        lambda *args, **kwargs: avatar_calls.append(True) or False,
    )

    member_handlers._handle_chat_member_update(bot, update, {}, db)

    assert db.upserts[0][4] == bio
    assert len(enforced) == 1
    assert avatar_calls == []


def test_non_release_member_update_only_tracks_without_repeat_review(monkeypatch):
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    db = _DB()
    user = _User("普通昵称")
    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        old_chat_member=SimpleNamespace(status="member", user=user),
        new_chat_member=SimpleNamespace(status="restricted", user=user),
    )
    profile_calls = []
    avatar_calls = []
    monkeypatch.setattr(
        member_handlers,
        "_review_member_profile",
        lambda *args, **kwargs: profile_calls.append(True) or False,
    )
    monkeypatch.setattr(
        member_handlers,
        "_review_member_avatar",
        lambda *args, **kwargs: avatar_calls.append(True) or False,
    )

    member_handlers._handle_chat_member_update(bot, update, {}, db)

    assert len(db.upserts) == 1
    assert profile_calls == []
    assert avatar_calls == []
