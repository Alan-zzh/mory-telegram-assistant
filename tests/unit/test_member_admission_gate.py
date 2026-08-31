# -*- coding: utf-8 -*-
"""入群资料审核回归：覆盖截图账号、延迟 Bio 与正常语境。"""

from datetime import datetime, timezone
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


class _PersonalChannelBot(_Bot):
    def __init__(self):
        super().__init__(bio="")
        self.personal_chat = SimpleNamespace(
            id=-1003735080194,
            title="恒泰高聘换资车队有码就要",
            username="gzy_channel",
            description="",
        )

    def get_chat(self, uid):
        if uid == self.personal_chat.id:
            return self.personal_chat
        return SimpleNamespace(
            bio="", emoji_status_custom_emoji_id="", personal_chat=self.personal_chat
        )

    def get_user_personal_chat_messages(self, user_id, limit):
        return [SimpleNamespace(
            text="",
            caption="微信支付宝来有码就要 无风险 日赚3ooo-8ooo，客服私信，担保公群",
        )]


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


def test_evasive_ad_name_and_bot_invite_bio_block_at_join_and_delayed_review(monkeypatch):
    from core.handlers import member_handlers

    user = _User("y同程老师免费上榜{牵.茗.进}y", username="")
    bio = "p小程序：https://t.me/tcsy1bot?start=invite_7982354468"
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )

    for stage in ("join", "delayed_30s"):
        assert member_handlers._review_member_profile(
            _Bot(bio), user, bio, {}, object(), -1003004701688, stage=stage
        ) is True

    assert len(enforced) == 2


def test_invite_opportunity_bio_blocks_at_join_and_delayed_review(monkeypatch):
    from core.handlers import member_handlers

    user = _User("fanbai", username="")
    bio = "https://t.me/+yZILbWYkW9hiMTg1 小白必做🫐勤快你就来懒人勿扰"
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )

    for stage in ("join", "delayed_30s"):
        assert member_handlers._review_member_profile(
            _Bot(bio), user, bio, {}, object(), -1003004701688, stage=stage
        ) is True

    assert len(enforced) == 2


def test_coded_phone_distribution_blocks_at_join_and_delayed_review(monkeypatch):
    from core.handlers import member_handlers

    user = _User("正-品-水-果17-手-机-全-系", username="spjc7ymbce")
    bio = "大量寻代理商和散户出货预定18 https://t.me/+npV6UqNCBedjM2Jk"
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )

    for stage in ("join", "delayed_30s"):
        assert member_handlers._review_member_profile(
            _Bot(bio), user, bio, {}, object(), -1003004701688, stage=stage
        ) is True

    assert len(enforced) == 2


def test_verify_release_does_not_enforce_normal_smith_name(monkeypatch):
    """截图回归：验证码放行后的真实入口不得把 Smith 中的 Sm 当色情引流。"""
    from core.handlers import member_handlers
    from modules.ad_detector import AdDetector

    bot = _Bot(bio="")
    db = _DB()
    user = _User("Kimberly", uid=8719901106, username=None)
    user.last_name = "Smith"
    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        old_chat_member=SimpleNamespace(status="restricted", user=user),
        new_chat_member=SimpleNamespace(status="member", user=user),
    )
    detector = AdDetector({"AD_ENABLED": True})
    monkeypatch.setattr(detector, "_check_cas", lambda _uid: (False, ""))
    monkeypatch.setattr(detector, "_check_spb", lambda _uid: (0.0, False))
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

    member_handlers._handle_chat_member_update(
        bot, update, {}, db, ctx=SimpleNamespace(ad_detector=detector)
    )

    assert enforced == []
    assert avatar_calls == [True]


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


def test_new_member_personal_channel_ad_blocks_before_welcome(monkeypatch):
    from core.handlers import member_handlers
    from modules import anti_raid, emoji_mask_detector, federation, spam_watch, welcome_customization

    bot = _PersonalChannelBot()
    db = _DB()
    user = _User("普通昵称", uid=8704705115, username="")
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        new_chat_members=[user],
        from_user=user,
    )
    enforced = []
    welcome_calls = []
    monkeypatch.setattr(anti_raid, "check_raid", lambda *args, **kwargs: False)
    monkeypatch.setattr(spam_watch, "check_user_spam", lambda *args, **kwargs: False)
    monkeypatch.setattr(federation, "execute_fban_on_join", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        emoji_mask_detector, "check_emoji_mask_in_username", lambda *args, **kwargs: (False, "")
    )
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(
        welcome_customization,
        "send_welcome_message",
        lambda *args, **kwargs: welcome_calls.append(True),
    )

    member_handlers._handle_new_chat_members(
        bot, message, {"VERIFICATION_CONFIG": {"enable": True}}, db
    )

    assert len(enforced) == 1
    assert welcome_calls == []
    assert bot.sent == []


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


def test_empty_release_bio_schedules_bounded_retry_and_later_blocks(monkeypatch):
    from core.handlers import member_handlers
    from tasks import task_scheduler

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace(status="member")
    db = _DB()
    user = _User("洪念桐", uid=8858734300)
    update = SimpleNamespace(
        chat=SimpleNamespace(id=-1003004701688),
        old_chat_member=SimpleNamespace(status="restricted", user=user),
        new_chat_member=SimpleNamespace(status="member", user=user),
    )
    jobs = []

    class _Scheduler:
        def add_job(self, func, **kwargs):
            jobs.append((func, kwargs))

    monkeypatch.setattr(task_scheduler, "get_scheduler_instance", lambda: _Scheduler())
    enforced = []
    monkeypatch.setattr(
        member_handlers,
        "_enforce_member_ad",
        lambda *args, **kwargs: enforced.append((args, kwargs)),
    )
    monkeypatch.setattr(member_handlers, "_review_member_avatar", lambda *args, **kwargs: False)

    member_handlers._handle_chat_member_update(bot, update, {}, db)

    assert len(jobs) == 1
    assert jobs[0][1]["id"] == "member_profile_retry_-1003004701688_8858734300"

    bot.bio = "👉 https://t.me/+GXnFrenFyj0zOTE9 👈多一条路试试。"
    func, job = jobs[0]
    func(*job["args"])

    assert len(enforced) == 1


def test_empty_bio_after_final_successful_fetch_is_clear_info(monkeypatch):
    """三次复审均能取到资料但 Bio 为空时，正常结束而非误报 degraded。"""
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace(status="member")
    user = _User("普通昵称", uid=8858734301)
    info = []
    warnings = []
    monkeypatch.setattr(member_handlers.logger, "info", lambda message, *args, **kwargs: info.append(message))
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    result = member_handlers._run_delayed_member_profile_review(
        bot,
        user,
        {},
        _DB(),
        -1003004701688,
        attempt=2,
    )

    assert result is False
    assert member_handlers._PROFILE_RETRY_DELAYS_SECONDS == (30, 300, 1800)
    assert any("outcome=complete reason=bio_absent_after_retries" in message for message in info)
    assert warnings == []


def test_empty_bio_after_final_get_chat_failure_is_degraded_warning(monkeypatch):
    """最终 get_chat 失败仍是未知状态，必须保留 degraded/retry_exhausted。"""
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace(status="member")

    def _get_chat_failure(_uid):
        raise RuntimeError("telegram unavailable")

    bot.get_chat = _get_chat_failure
    user = _User("普通昵称", uid=8858734302)
    info = []
    warnings = []
    monkeypatch.setattr(member_handlers.logger, "info", lambda message, *args, **kwargs: info.append(message))
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    result = member_handlers._run_delayed_member_profile_review(
        bot,
        user,
        {},
        _DB(),
        -1003004701688,
        attempt=2,
    )

    assert result is False
    assert any(
        "outcome=degraded reason=bio_fetch_failed_retry_exhausted" in message
        for message in warnings
    )
    assert not any("outcome=complete reason=bio_absent_after_retries" in message for message in info)


def test_empty_profile_retry_runs_full_chain_then_completes(monkeypatch):
    """真实 0→1→2 调度参数链保持有界，最终确认空 Bio 后正常完成。"""
    from core.handlers import member_handlers
    from tasks import task_scheduler

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace(status="member")
    user = _User("普通昵称", uid=8858734303)
    pending = []
    scheduled_delays = []
    info = []
    warnings = []

    class _Scheduler:
        def add_job(self, func, **kwargs):
            pending.append((func, kwargs["args"]))
            scheduled_delays.append(
                int((kwargs["run_date"] - datetime.now(timezone.utc)).total_seconds())
            )

    monkeypatch.setattr(task_scheduler, "get_scheduler_instance", lambda: _Scheduler())
    monkeypatch.setattr(member_handlers.logger, "info", lambda message, *args, **kwargs: info.append(message))
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    member_handlers._run_delayed_member_profile_review(
        bot, user, {}, _DB(), -1003004701688, attempt=0
    )
    while pending:
        func, args = pending.pop(0)
        func(*args)

    assert len(scheduled_delays) == 2
    assert scheduled_delays[0] in (299, 300)
    assert scheduled_delays[1] in (1799, 1800)
    assert any("outcome=complete reason=bio_absent_after_retries" in message for message in info)
    assert warnings == []


def test_none_profile_response_remains_degraded(monkeypatch):
    """Telegram 返回 None 不是成功空 Bio，最终必须保持降级可见。"""
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    bot.get_chat = lambda uid: None
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace(status="member")
    warnings = []
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    member_handlers._run_delayed_member_profile_review(
        bot, _User("普通昵称", uid=8858734304), {}, _DB(), -1003004701688, attempt=2
    )

    assert any("reason=bio_fetch_failed_retry_exhausted" in message for message in warnings)


def test_none_membership_response_remains_degraded(monkeypatch):
    """成员查询返回 None 不是普通成员，终态必须保留成员查询失败原因。"""
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: None
    warnings = []
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    member_handlers._run_delayed_member_profile_review(
        bot, _User("普通昵称", uid=8858734305), {}, _DB(), -1003004701688, attempt=2
    )

    assert any("reason=membership_query_failed_retry_exhausted" in message for message in warnings)


def test_empty_membership_status_remains_degraded(monkeypatch):
    """成员对象缺少 status 仍是未知态，不得被空 Bio 覆盖成正常完成。"""
    from core.handlers import member_handlers

    bot = _Bot(bio="")
    bot.get_chat_member = lambda chat_id, uid: SimpleNamespace()
    info = []
    warnings = []
    monkeypatch.setattr(member_handlers.logger, "info", lambda message, *args, **kwargs: info.append(message))
    monkeypatch.setattr(
        member_handlers.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message),
    )

    member_handlers._run_delayed_member_profile_review(
        bot, _User("普通昵称", uid=8858734306), {}, _DB(), -1003004701688, attempt=2
    )

    assert any("reason=membership_query_failed_retry_exhausted" in message for message in warnings)
    assert not any("outcome=complete" in message for message in info)


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
