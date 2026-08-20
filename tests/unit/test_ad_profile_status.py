# -*- coding: utf-8 -*-
"""
[Codex] 广告资料状态检测测试：覆盖 Telegram Premium emoji 状态中的看我简介信号。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeSticker:
    def __init__(self, emoji="", set_name="", custom_emoji_id="status-1", thumbnail=None):
        self.emoji = emoji
        self.set_name = set_name
        self.custom_emoji_id = custom_emoji_id
        self.thumbnail = thumbnail


class _FakeBot:
    def __init__(self, stickers):
        self.stickers = stickers
        self.requested = []
        self.downloaded = []

    def get_custom_emoji_stickers(self, custom_emoji_ids):
        self.requested.append(list(custom_emoji_ids))
        return self.stickers

    def get_file(self, file_id):
        return type("FileInfo", (), {"file_path": f"stickers/{file_id}.webp"})()

    def download_file(self, file_path):
        self.downloaded.append(file_path)
        return b"fake-image"


class _FakeUser:
    def __init__(self, first_name="云间藏诗意", status_id="status-1"):
        self.id = 42
        self.first_name = first_name
        self.last_name = ""
        self.username = ""
        self.emoji_status_custom_emoji_id = status_id


def test_profile_status_metadata_hits_look_profile_pattern():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    result = detect_profile_ad_signal(bot, _FakeUser(), "")

    assert result["is_ad"] is True
    assert "emoji状态" in result["reason"]
    assert bot.requested == [["status-1"]]


def test_profile_status_without_text_only_tracks_suspicious():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakeBot([_FakeSticker(emoji="🐱", set_name="")])
    result = detect_profile_ad_signal(bot, _FakeUser(), "")

    assert result["is_ad"] is False
    assert result["score"] == 1
    assert "自定义emoji状态" in result["reason"]


def test_profile_status_ocr_hits_image_only_look_profile(monkeypatch):
    from modules import ad_profile_signals

    monkeypatch.setattr(ad_profile_signals, "analyze_image", lambda data, prompt, config: "看我简介")
    thumb = type("Thumb", (), {"file_id": "thumb-1"})()
    bot = _FakeBot([_FakeSticker(emoji="🐱", set_name="", thumbnail=thumb)])

    result = ad_profile_signals.detect_profile_ad_signal(bot, _FakeUser(), "", {"MODEL_POOLS": {"vision": [{"name": "qwen-vl"}]}, "API_KEY": "x"})

    assert result["is_ad"] is True
    assert "emoji状态图片OCR" in result["reason"]
    assert bot.downloaded == ["stickers/thumb-1.webp"]


def test_profile_bio_group_invite_link_blocks_on_join():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bio = (
        "带两个缺钱的兄弟，只要你肯付出，一天保你一万打底，"
        "想做的兄弟，进群找了解: https://t.me/+pJMFeWCqXow2NmI1"
    )

    result = detect_profile_ad_signal(None, _FakeUser(first_name="甜甜 Shaikh", status_id=""), bio, {})

    assert result["is_ad"] is True
    assert result["score"] == 3
    assert "资料文字命中广告规则" in result["reason"]


def test_profile_bio_bare_personal_link_is_not_ad():
    """纯个人链接没有广告说明时只是资料，不得授权处置。"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="摄影记录", status_id=""),
        "https://t.me/my_daily_album",
        {},
    )

    assert result["is_ad"] is False
    assert result["score"] == 0


def test_profile_bio_invite_teaser_exact_incident_is_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="洪念桐", status_id=""),
        "👉 https://t.me/+GXnFrenFyj0zOTE9 👈多一条路试试。",
        {},
    )

    assert result["is_ad"] is True
    assert result["score"] == 3
    assert result["source"] == "bio_invite_teaser"


def test_same_city_prostitution_profile_name_is_direct_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="y同程嫖娼老师免费上榜{牵.茗.进}y", status_id=""),
        "p小程序：https://t.me/tcsy1bot?start=invite_7982354468",
        {},
    )

    assert result["is_ad"] is True
    assert result["score"] == 3


@pytest.mark.parametrize(
    "display_name",
    ["反诈提醒：嫖娼违法", "同程旅行老师", "同城电脑维修", "老师免费上榜"],
)
def test_same_city_prostitution_profile_rule_preserves_normal_names(display_name):
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name=display_name, status_id=""),
        "",
        {},
    )

    assert result["is_ad"] is False


def test_normal_group_invite_without_teaser_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="摄影群管理员", status_id=""),
        "备用摄影交流群：https://t.me/+AbCdEfGhIjKlMnOp",
        {},
    )

    assert result["is_ad"] is False
    assert result["score"] == 0


def test_profile_bio_explicit_promotion_with_link_is_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="业务推广", status_id=""),
        "广告引流：https://t.me/example_ads",
        {},
    )

    assert result["is_ad"] is True
    assert result["score"] == 3


def test_profile_bio_adult_resource_keywords_with_link_are_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="普通昵称", status_id=""),
        "同城母狗资源，包实战落地：https://t.me/example",
        {},
    )

    assert result["is_ad"] is True
    assert result["score"] == 3


class _FakePersonalChannelBot:
    def __init__(self, title, description="", username="channel_name", posts=None):
        self.posts = list(posts or [])
        self.user_chat = type(
            "UserChat",
            (),
            {
                "bio": "",
                "personal_chat": type(
                    "PersonalChat",
                    (),
                    {
                        "id": -1004432682202,
                        "title": title,
                        "username": username,
                        "description": "",
                    },
                )(),
            },
        )()
        self.channel_chat = type(
            "ChannelChat",
            (),
            {
                "id": -1004432682202,
                "title": title,
                "username": username,
                "description": description,
            },
        )()

    def get_chat(self, chat_id):
        if chat_id == -1004432682202:
            return self.channel_chat
        return self.user_chat

    def get_user_personal_chat_messages(self, user_id, limit):
        return [
            type("ChannelMessage", (), {"text": "", "caption": caption})()
            for caption in self.posts[:limit]
        ]


def test_plain_bound_personal_channel_is_not_ad():
    """只绑定普通个人频道，即使带频道 username，也不能直接封禁。"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "我的摄影日记",
        "记录旅行、家人和日常照片",
        "my_daily_album",
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False
    assert result["score"] == 0
    assert result["personal_chat_id"] == -1004432682202


def test_personal_channel_exact_production_variant_is_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "财天下飞机进群结演员结算频道",
        "别人准备干你说不好干，别人赚钱了你说人家干得早",
        "gzy_9671271455_1_9203",
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is True
    assert result["source"] == "personal_chat"
    assert result["personal_chat_id"] == -1004432682202
    assert set(result["personal_chat_anchors"]) >= {
        "平台暗语", "拉群动作", "商业招揽", "频道载体"
    }


def test_personal_channel_split_words_and_reflective_expansion_is_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "财天下 飞 机 交 流 频 道",
        "别人还在反思，你已经开始做；想了解就私 聊 进 群，每天统一结 算。",
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is True
    assert result["source"] == "personal_chat"


def test_personal_channel_rewritten_without_platform_slang_is_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "项目交流频道",
        "需要了解的私聊我加群，做单佣金统一日结。",
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is True
    assert set(result["personal_chat_anchors"]) >= {"拉群动作", "商业招揽", "频道载体"}


def test_personal_channel_normal_flight_group_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot("飞机航班交流群", "每日更新天气、延误和登机口信息")
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False


def test_personal_channel_normal_actor_settlement_notice_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot("影视演员工作结算通知频道", "仅发布剧组工资到账通知")
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False


def test_personal_channel_reflective_motivation_alone_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot("每日反思", "别人赚钱不是运气，坚持努力也要尊重自己的节奏")
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False


def test_personal_channel_payment_code_screenshot_title_blocks_on_join():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot("恒泰高聘换资车队有码就要")
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is True
    assert result["source"] == "personal_chat"
    assert set(result["personal_chat_anchors"]) >= {"资金码盘", "灰产组织"}


def test_personal_channel_latest_post_payment_code_ad_blocks_on_join():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "恒泰业务交流",
        posts=[
            "微信支付宝来有码就要 无风险 日赚3ooo-8ooo\n"
            "高效率稳定开工多年老盘安全有保障\n"
            "飞哥客服：@Dl88o 双向私信：@feieobot 担保公群 https://t.me/example"
        ],
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is True
    assert result["source"] == "personal_chat"
    assert set(result["personal_chat_anchors"]) >= {
        "资金码盘", "灰产组织", "收益承诺", "资料导流"
    }


def test_personal_channel_normal_payment_tutorial_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot(
        "支付宝收款码操作教程频道",
        posts=["本周讲解企业收款码申请、财务对账和支付故障排查"],
    )
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False


def test_personal_channel_normal_vehicle_team_notice_is_not_ad():
    from modules.ad_profile_signals import detect_profile_ad_signal

    bot = _FakePersonalChannelBot("网约车队司机通知", posts=["今晚机场排队较长，请司机错峰交班"])
    result = detect_profile_ad_signal(bot, _FakeUser(status_id=""), "", {})

    assert result["is_ad"] is False


def test_telebot_user_keeps_emoji_status_extra_field():
    from core.telebot_compat import preserve_user_extra_fields
    from telebot import types

    preserve_user_extra_fields()
    user = types.User(42, False, "云间藏诗意", emoji_status_custom_emoji_id="status-1")

    assert user.emoji_status_custom_emoji_id == "status-1"


class _FakeConn:
    def execute(self, *args, **kwargs):
        return []

    def commit(self):
        pass


class _FakeDB:
    def __init__(self):
        self.conn = _FakeConn()
        self.blacklist = []
        self.ad_marked = []

    def is_blacklisted(self, uid):
        return False

    def blacklist_add(self, uid, reason):
        self.blacklist.append((uid, reason))

    def get_user_undeleted_messages(self, uid, chat_id=None, limit=2000):
        return []

    def mark_message_deleted(self, chat_id, msg_id):
        return True

    def mark_message_ad(self, chat_id, msg_id):
        self.ad_marked.append((chat_id, msg_id))
        return True


class _FakeAdDetector:
    def __init__(self):
        self.cleared = []

    def track_suspicious_user(self, *args, **kwargs):
        return {"action": "none", "total_score": 0}

    def clear_user_tracking(self, uid):
        self.cleared.append(uid)

    def detect(self, **_kwargs):
        return {"is_ad": False, "score": 0, "matched_rules": []}

    def check_consecutive_patterns(self, *_args, **_kwargs):
        return {"is_spam": False, "score": 0, "messages": []}


class _FakeShortMessage:
    content_type = "text"
    text = "1"
    message_id = 88
    chat = type("Chat", (), {"id": -1001, "type": "supergroup"})()
    from_user = _FakeUser()


def test_profile_ad_deletes_even_when_general_deletion_is_disabled():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    bot.deleted = []
    bot.restricted = []
    bot._me = type("Me", (), {"id": 7})()
    bot.get_chat = lambda uid: type("ChatInfo", (), {"bio": ""})()
    bot.get_me = lambda: bot._me
    bot.delete_message = lambda chat_id, msg_id: bot.deleted.append((chat_id, msg_id)) or True
    bot.restrict_chat_member = lambda chat_id, uid, **kwargs: bot.restricted.append((chat_id, uid, kwargs)) or True

    db = _FakeDB()
    ctx = type("Ctx", (), {
        "bot": bot,
        "db": db,
        "config": {"ENABLE_MESSAGE_DELETION": False},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "1",
        "ctx": ctx,
        "msg": _FakeShortMessage(),
        "uid": 42,
        "uname": "云间藏诗意",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is True
    assert bot.deleted == [(-1001, 88)]
    assert bot.restricted[0][0:2] == (-1001, 42)
    # 账号资料是广告证据，但正文“1”不是广告；仍删除拦截，不伪造逐条广告真值。
    assert db.ad_marked == []


def test_personal_channel_ad_blocks_short_probe_before_ai_reply():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakePersonalChannelBot(
        "财天下飞机进群结演员结算频道",
        "别人准备干你说不好干，别人赚钱了你说人家干得早",
    )
    bot.deleted = []
    bot.restricted = []
    bot.get_chat_member = lambda chat_id, uid: type("Member", (), {"status": "member"})()
    bot.delete_message = lambda chat_id, msg_id: bot.deleted.append((chat_id, msg_id)) or True
    bot.restrict_chat_member = (
        lambda chat_id, uid, **kwargs: bot.restricted.append((chat_id, uid, kwargs)) or True
    )

    msg = _FakeShortMessage()
    msg.text = "凎活啦"
    ctx = type("Ctx", (), {
        "bot": bot,
        "db": _FakeDB(),
        "config": {"ENABLE_MESSAGE_DELETION": False},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "凎活啦",
        "ctx": ctx,
        "msg": msg,
        "uid": 42,
        "uname": "李大哥",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is True
    assert bot.deleted == [(-1001, 88)]
    assert bot.restricted[0][0:2] == (-1001, 42)


def test_bare_link_bio_and_plain_channel_do_not_block_short_message():
    """真实回复入口反例：裸链接+普通频道不能删消息、禁言或截断回复。"""
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakePersonalChannelBot(
        "我的摄影日记",
        "记录旅行和生活",
        "my_daily_album",
    )
    bot.user_chat.bio = "https://t.me/my_daily_album"
    bot.deleted = []
    bot.restricted = []
    bot.get_chat_member = lambda chat_id, uid: type("Member", (), {"status": "member"})()
    bot.delete_message = lambda chat_id, msg_id: bot.deleted.append((chat_id, msg_id)) or True
    bot.restrict_chat_member = (
        lambda chat_id, uid, **kwargs: bot.restricted.append((chat_id, uid, kwargs)) or True
    )

    msg = _FakeShortMessage()
    msg.text = "在吗"
    ctx = type("Ctx", (), {
        "bot": bot,
        "db": _FakeDB(),
        "config": {"ENABLE_MESSAGE_DELETION": True},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "在吗",
        "ctx": ctx,
        "msg": msg,
        "uid": 42,
        "uname": "摄影记录",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is False
    assert bot.deleted == []
    assert bot.restricted == []
    assert ctx.db.blacklist == []


def test_invite_teaser_and_look_at_me_message_are_enforced_and_marked():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakePersonalChannelBot("", "", "")
    bot.user_chat.personal_chat = None
    bot.user_chat.bio = "👉 https://t.me/+GXnFrenFyj0zOTE9 👈多一条路试试。"
    bot.deleted = []
    bot.restricted = []
    bot.get_chat_member = lambda chat_id, uid: type("Member", (), {"status": "member"})()
    bot.delete_message = lambda chat_id, msg_id: bot.deleted.append((chat_id, msg_id)) or True
    bot.restrict_chat_member = (
        lambda chat_id, uid, **kwargs: bot.restricted.append((chat_id, uid, kwargs)) or True
    )

    msg = _FakeShortMessage()
    msg.text = "都TMD看我，搞不了几k你直接骂死我"
    db = _FakeDB()
    ctx = type("Ctx", (), {
        "bot": bot,
        "db": db,
        "config": {"ENABLE_MESSAGE_DELETION": False},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": msg.text,
        "ctx": ctx,
        "msg": msg,
        "uid": 42,
        "uname": "洪念桐",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is True
    assert bot.deleted == [(-1001, 88)]
    assert bot.restricted[0][0:2] == (-1001, 42)
    assert db.ad_marked == [(-1001, 88)]


def test_profile_status_ad_does_not_block_whitelisted_user():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    bot.deleted = []
    bot.restricted = []
    bot.get_chat_member = lambda chat_id, uid: type("Member", (), {"status": "member"})()

    ctx = type("Ctx", (), {
        "bot": bot,
        "db": _FakeDB(),
        "config": {"ENABLE_MESSAGE_DELETION": True, "AD_WHITELIST": {"user_ids": [42]}},
        "ad_detector": _FakeAdDetector(),
    })()
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "1",
        "ctx": ctx,
        "msg": _FakeShortMessage(),
        "uid": 42,
        "uname": "云间藏诗意",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is False
    assert bot.requested == []
    assert bot.deleted == []
    assert bot.restricted == []


def test_checkin_text_bypasses_profile_status_ad_tracking():
    from core.handlers.security_handlers import check_ad_detection

    bot = _FakeBot([_FakeSticker(set_name="kanwo 看我简介")])
    bot.deleted = []
    bot.restricted = []
    ad_detector = _FakeAdDetector()

    ctx = type("Ctx", (), {
        "bot": bot,
        "db": _FakeDB(),
        "config": {"ENABLE_MESSAGE_DELETION": True},
        "ad_detector": ad_detector,
    })()
    msg = _FakeShortMessage()
    msg.text = "签到"
    dctx = type("Dctx", (), {
        "is_group": True,
        "text": "签到",
        "ctx": ctx,
        "msg": msg,
        "uid": 42,
        "uname": "云间藏诗意",
        "chat_id": -1001,
    })()

    assert check_ad_detection(dctx) is False
    assert bot.requested == []
    assert ad_detector.cleared == [42]
    assert bot.deleted == []
    assert bot.restricted == []


# =====================================================================
# v5.28.3 回归测试：色情引流组合模式检测
# 修复 SM/淫素/过夜/出+年龄 等关键词覆盖漏洞
# =====================================================================


def test_bio_sm_dog_pattern():
    """回归：Bio 含 SM+母狗+交友 必须被资料层识别"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="蜜桃成熟时", status_id=""),
        bio="精全国各地SM母狗交友信息：https://t.me/+zXWSqSu64ORhZmQ9"
    )
    assert result["is_ad"] is True
    assert result["score"] == 3
    assert "资料文字命中广告规则" in result["reason"]


def test_bio_night_service_pattern():
    """回归：Bio 含 过夜+服务+链接 必须被资料层识别"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="夜猫子", status_id=""),
        bio="全国各地可以过夜，联系@service_bot https://t.me/+abc123"
    )
    assert result["is_ad"] is True
    assert result["score"] == 3
    assert "资料文字命中广告规则" in result["reason"]


def test_bio_sm交友_link_pattern():
    """回归：Bio 含 SM+交友+链接 必须被资料层识别"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="SM玩家", status_id=""),
        bio="SM交友信息：https://t.me/+smgroup"
    )
    assert result["is_ad"] is True
    assert result["score"] == 3


def test_bio_smith_followed_by_social_text_is_not_sm_adult_evidence():
    """Smith 中的 Sm 不是独立缩写，后接普通交友文字也不能冒充色情证据。"""
    from modules.ad_profile_signals import detect_profile_ad_signal

    result = detect_profile_ad_signal(
        None,
        _FakeUser(first_name="Kimberly Smith", status_id=""),
        bio="Smith交友",
    )

    assert result["is_ad"] is False
    assert result["score"] == 0


def test_adult_keyword_sm_in_text():
    """回归：消息含 SM 必须被消息层识别"""
    from modules.ad_detector import AdDetector

    detector = AdDetector({"AD_ENABLED": True})
    result = detector.detect(
        username="smhwmt",
        msg="SM全套服务，私聊了解",
        user_id=999
    )
    assert result["is_ad"] is True


def test_adult_keyword_淫素_in_text():
    """回归：消息含 淫素 必须被消息层识别"""
    from modules.ad_detector import AdDetector

    detector = AdDetector({"AD_ENABLED": True})
    result = detector.detect(
        username="testuser",
        msg="出23岁淫素，可以过夜",
        user_id=998
    )
    assert result["is_ad"] is True
