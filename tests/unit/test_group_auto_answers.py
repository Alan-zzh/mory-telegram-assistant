import json
from pathlib import Path
from types import SimpleNamespace


def test_group_verification_numbers_are_filtered_before_chat_pipeline():
    from core.message_dispatcher import _is_group_verification_number

    assert _is_group_verification_number("123")
    assert _is_group_verification_number(" 1 2 3 ")
    assert _is_group_verification_number("１２３")
    assert not _is_group_verification_number("今天赚了100")
    assert not _is_group_verification_number("验证码123")

    source = Path("core/message_dispatcher.py").read_text(encoding="utf-8")
    assert source.index("if is_group and _is_group_verification_number") < source.index(
        "load_recent_conversation"
    )


class _QuestionDb:
    def __init__(self):
        self.telemetry = []
        self.faq_hits = []
        self.business_context = []
        self.questions = []

    def match_keyword_trigger(self, _text):
        return []

    def log_telemetry(self, *args):
        self.telemetry.append(args)
        return 1

    def search_faq(self, _msg, _mode, _intent):
        return [{
            "id": 7,
            "answer_template": "签到积分可兑换VIP月卡等福利。",
            "ai_polish": False,
        }]

    def increment_faq_hit(self, faq_id):
        self.faq_hits.append(faq_id)

    def record_business_context(self, *args, **kwargs):
        self.business_context.append((args, kwargs))
        return True

    def log_question(self, **kwargs):
        self.questions.append(kwargs)
        return len(self.questions)


class _ReplyRecorder:
    def __init__(self):
        self.replies = []

    def reply_and_track(self, _message, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(message_id=12, chat=SimpleNamespace(id=-1001))


class _NoReplyAi:
    def ask(self, *_args, **_kwargs):
        return None


def _message(text, uid=42):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=uid),
        chat=SimpleNamespace(id=-1001),
        message_id=9,
    )


def _private_message(text, uid=42):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=uid),
        chat=SimpleNamespace(id=uid, type="private"),
        message_id=10,
    )


def test_invalid_checkin_aliases_are_rejected_with_simplified_format():
    from modules.checkin import (
        CHECKIN_FORMAT_HINT,
        _configured_bonus_days,
        is_checkin_enabled,
        is_invalid_checkin_command,
    )

    for text in ("簽到", "/簽到", "QD", "qd", "/qd", "Q.D"):
        assert is_invalid_checkin_command(text)
    assert not is_invalid_checkin_command("签到")
    assert "简体“签到”" in CHECKIN_FORMAT_HINT
    assert "不要加任何符号" in CHECKIN_FORMAT_HINT
    assert is_checkin_enabled({"CHECKIN_CONFIG": {"enabled": True}})
    assert is_checkin_enabled({"CHECKIN_CONFIG": {"enable": True}})
    assert not is_checkin_enabled(
        {"CHECKIN_CONFIG": {"enabled": False, "enable": True}}
    )
    bonus_days = _configured_bonus_days({
        "streak_bonus": {"3": 9},
        "bonus_7d": 20,
    })
    assert bonus_days[3] == 9
    assert bonus_days[7] == 20


def test_checkin_dashboard_normalizes_and_saves_both_enable_keys(monkeypatch):
    from flask import Flask
    import dashboard.api.settings_api as settings_api

    store = {
        "CHECKIN_CONFIG": {
            "enable": True,
            "base_points": 10,
            "bonus_3d": 9,
            "bonus_7d": 20,
        },
    }
    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)
    app = Flask(__name__)
    app.secret_key = "checkin-test"
    app.register_blueprint(settings_api.settings_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"

    current = client.get("/api/settings/checkin").get_json()["data"]
    assert current["enabled"] is True
    assert current["streak_bonus"]["3"] == 9
    assert current["streak_bonus"]["7"] == 20

    response = client.post(
        "/api/settings/checkin",
        json={
            "enabled": False,
            "base_points": 8,
            "streak_bonus": {"3": 11, "7": 22},
        },
    )
    assert response.status_code == 200
    assert store["CHECKIN_CONFIG"]["enabled"] is False
    assert store["CHECKIN_CONFIG"]["enable"] is False
    assert store["CHECKIN_CONFIG"]["base_points"] == 8
    assert store["CHECKIN_CONFIG"]["streak_bonus"] == {"3": 11, "7": 22}


def test_builtin_persona_wakeup_replies_without_conversion_entry():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config={})

    assert trigger.handle_message("助理出来", -1001, _message("助理出来"), object())
    assert recorder.replies
    assert "@moryselect" not in recorder.replies[0][0]
    assert "@MorychannelBot" not in recorder.replies[0][0]
    assert "@Moryfansbot" not in recorder.replies[0][0]
    assert db.telemetry[0][3] == "助理唤醒"


def test_group_silence_questions_use_reviewed_base_and_ai_tone_variation():
    from modules.keyword_trigger import KeywordTrigger

    class _PolishAi:
        def __init__(self):
            self.prompts = []

        def ask(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            return (
                "这就是个粉丝反馈群，Mory 不是做女菩萨来陪聊的，也不是做门姐找你要门槛的。"
                "有问题就反馈，有通知会发公告；想订阅就自助，联系按群里现有入口走。整天在群里口嗨，"
                "能赚钱还是能涨粉？付费用户更在意内容和效率，大家都要忙，务实点。"
                "打嘴炮的事 Mory 干不出来，我相信你也不是这样的人，喜欢这样的吧，对不对？"
            )

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    ai = _PolishAi()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=ai, config={})

    variants = (
        "群里好安静", "群里怎么没人说话", "为什么群里都不说话",
        "这个群怎么这么冷清", "群里没人聊天",
    )
    for text in variants:
        rule = trigger._match_special_rule(text)
        assert rule and rule["name"] == "群聊冷场说明", text

    message = _message("群里好安静")
    assert trigger.handle_message(message.text, message.chat.id, message, object())
    assert ai.prompts
    assert "140到180个汉字" in ai.prompts[0]
    assert "不得弱化成客服腔" in ai.prompts[0]
    assert "结尾必须逐字保留" in ai.prompts[0]
    assert "想订阅就自助" in ai.prompts[0]
    assert "粉丝反馈群" in recorder.replies[0][0]
    assert "有通知会发公告" in recorder.replies[0][0]
    for term in (
        "女菩萨", "门姐", "口嗨", "赚钱", "涨粉", "打嘴炮",
        "想订阅就自助", "喜欢这样的",
    ):
        assert term in recorder.replies[0][0]
    assert "不喜欢这样" not in recorder.replies[0][0]
    assert "@MorychannelBot" not in recorder.replies[0][0]
    assert db.business_context[0][1]["conversion_target"] == "none"


def test_group_silence_polish_with_reversed_closing_falls_back_to_owner_wording():
    from modules.keyword_trigger import KeywordTrigger

    class _ReversedClosingAi:
        def ask(self, *_args, **_kwargs):
            return (
                "这是粉丝反馈群，Mory 不是女菩萨陪聊，也不是门姐找你要门槛。"
                "有问题反馈，有通知发公告。群里口嗨不能赚钱涨粉，大家都务实点。"
                "打嘴炮的事 Mory 不做，我相信你也不是这样的人，应该也不喜欢这样吧？"
            )

    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=recorder,
        ai=_ReversedClosingAi(),
        config={},
    )
    message = _message("群里好安静")

    assert trigger.handle_message(message.text, message.chat.id, message, object())
    reply = recorder.replies[-1][0]
    assert "喜欢这样的吧，对不对" in reply
    assert "不喜欢这样" not in reply


def test_group_silence_followups_and_unrelated_phrases_do_not_cross_match():
    from modules.keyword_trigger import KeywordTrigger

    trigger = KeywordTrigger(_QuestionDb(), config={})
    history = [
        {"role": "user", "content": "群里好安静", "intent": "群聊定位"},
        {"role": "assistant", "content": "这里主要承接反馈和通知。", "intent": "群聊定位"},
    ]
    followups = (
        "一直这样吗", "都不聊天吗", "为什么不活跃", "没人活跃吗",
        "还是很安静", "还是没人说话", "对", "确实", "说得对", "有道理",
        "这样挺好", "我就喜欢这样", "你说得也对啊", "我喜欢这种氛围",
        "这么也挺好的", "我明白了", "好像是这么回事", "但是群里还是很冷清啊",
    )
    for text in followups:
        rule = trigger._match_special_rule(text, conversation_history=history)
        assert rule and rule["name"] == "群聊冷场说明", text
        assert rule["conversion_target"] == "preview", text
        assert rule["card_enabled"] is True, text
        assert "@moryselect" in rule["base_reply"], text
        assert "@MorychannelBot" not in rule["base_reply"], text

    unrelated = (
        "今天办公室怎么没人说话",
        "为什么客服不说话",
        "群里没人回答我的退款问题",
        "没人说话就发红包吧",
        "群里好安静适合学习",
    )
    for text in unrelated:
        assert trigger._match_special_rule(text) is None, text

    refusal_or_objection = (
        "不喜欢这样", "我就想聊天", "别推了", "不用了", "你说话太冲",
    )
    for text in refusal_or_objection:
        assert trigger._match_special_rule(text, conversation_history=history) is None, text

    # 明确订阅不由冷场追问抢答，继续交给统一 subscribe 成交链。
    assert trigger._match_special_rule("怎么订阅", conversation_history=history) is None


def test_group_silence_positive_followup_sends_single_preview_card():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        db,
        mory_bot=recorder,
        ai=_NoReplyAi(),
        config={"AUTO_REPLY_CARD_ENABLED": True},
    )
    history = [
        {"role": "user", "content": "群里好安静", "intent": "群聊定位"},
        {"role": "assistant", "content": "这就是个粉丝反馈群。", "intent": "群聊定位"},
    ]

    message = _message("说得对")
    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        object(),
        conversation_history=history,
    )

    reply_text, kwargs = recorder.replies[-1]
    assert "@moryselect" in reply_text
    assert "@MorychannelBot" not in reply_text
    markup = kwargs["reply_markup"]
    assert len(markup.keyboard) == 1
    assert len(markup.keyboard[0]) == 1
    assert markup.keyboard[0][0].url == "https://t.me/moryselect"
    assert db.business_context[-1][1]["conversion_target"] == "preview"


def test_vpn_and_ladder_questions_use_clickable_confirmed_referral_without_llm():
    from modules.keyword_trigger import KeywordTrigger

    class _FailIfCalledAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("VPN/梯子推荐必须在进入 LLM 前确定性承接")

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_FailIfCalledAi(), config={})

    for text in (
        "有没有VPN推荐？",
        "有没有好用的梯子",
        "科学上网怎么弄",
        "翻墙工具推荐",
        "代理软件推荐一下",
        "有外网加速器吗",
        "有机场推荐吗",
        "节点推荐一下",
    ):
        assert trigger.handle_message(text, -1001, _message(text), object())

    reply_text, kwargs = recorder.replies[0]
    assert reply_text == (
        "可以试试这个，免费用，不好用删掉就行。\n"
        '体验地址 ➡️ <a href="https://getsapp.net/tQtX3e">'
        "https://getsapp.net/tQtX3e</a>"
    )
    assert "t.me/morychat" not in reply_text
    assert kwargs == {"parse_mode": "HTML", "disable_web_page_preview": True}
    assert db.telemetry[0][3] == "VPN/梯子推荐"
    assert db.business_context[0][1]["conversion_target"] == "none"


def test_vpn_context_followup_is_handled_but_normal_and_opt_out_phrases_are_not():
    from modules.keyword_trigger import KeywordTrigger

    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=recorder,
        ai=_NoReplyAi(),
        config={},
    )
    history = [
        {"role": "user", "content": "有没有VPN推荐？"},
        {"role": "assistant", "content": "可以试试这个，免费用。"},
    ]

    followup = _message("群友有没有？😁")
    assert trigger.handle_message(
        followup.text,
        followup.chat.id,
        followup,
        object(),
        conversation_history=history,
    )
    assert "https://getsapp.net/tQtX3e" in recorder.replies[0][0]
    assert trigger._match_special_rule(
        "群友有没有？😁",
        conversation_history=history,
    )["name"] == "VPN/梯子推荐"
    assert trigger._match_special_rule("今天去机场接人") is None
    assert trigger._match_special_rule("代理型号 X1 的售后问题") is None
    assert trigger._match_special_rule("VPN我不用了") is None


def test_private_mystic_reply_short_circuits_ai_with_zero_token():
    from modules.keyword_trigger import KeywordTrigger

    class _FailIfCalledAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("私聊本地占卜不应调用 LLM")

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        db,
        mory_bot=recorder,
        ai=_FailIfCalledAi(),
        config={
            "MYSTIC_BROADCAST_CONFIG": {
                "private_reply_enabled": True,
            },
        },
    )
    message = _private_message("帮我算卦看工作")

    assert trigger.handle_message(
        message.text,
        message.chat.id,
        message,
        object(),
    )
    assert recorder.replies[0][0].startswith("☯️ 为你起一卦")
    assert db.telemetry[0][3] == "mystic_iching"
    assert db.telemetry[0][6]["ai_mode"] == "local_zero_token"


def test_private_mystic_reply_is_default_off_and_group_does_not_trigger():
    from modules.keyword_trigger import KeywordTrigger

    disabled = KeywordTrigger(
        _QuestionDb(),
        mory_bot=_ReplyRecorder(),
        ai=_NoReplyAi(),
        config={},
    )
    private = _private_message("给我抽一下塔罗")
    assert not disabled.handle_message(
        private.text, private.chat.id, private, object()
    )

    group_recorder = _ReplyRecorder()
    enabled = KeywordTrigger(
        _QuestionDb(),
        mory_bot=group_recorder,
        ai=_NoReplyAi(),
        config={
            "MYSTIC_BROADCAST_CONFIG": {
                "private_reply_enabled": True,
            },
        },
    )
    group = _message("给我抽一下塔罗")
    assert not enabled.handle_message(group.text, group.chat.id, group, object())
    assert group_recorder.replies == []


def test_unconfigured_builtin_points_answer_is_not_active():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config={})

    points_msg = "签到积分有什么福利"
    video_msg = "定制视频是什么"
    assert not trigger.handle_message(points_msg, -1001, _message(points_msg), object())
    assert not trigger.handle_message(video_msg, -1001, _message(video_msg), object())
    assert recorder.replies == []


def test_configured_points_question_uses_only_configured_answer_without_llm():
    from modules.keyword_trigger import KeywordTrigger

    class _FailIfCalledAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("预设问答族必须零 Token 确定性回复")

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        db,
        mory_bot=recorder,
        ai=_FailIfCalledAi(),
        config={"SPECIAL_AUTO_REPLIES": [{
            "name": "积分咨询",
            "topic": "积分",
            "enabled": True,
            "keywords": ["积分怎么使用"],
            "keyword_match_mode": "full",
            "conversion_target": "none",
            "ai_polish": False,
            "remember_context": True,
            "base_reply": "这是老板配置的积分说明。",
        }]},
    )

    text = "积分怎么使用"
    assert trigger.handle_message(text, -1001, _message(text), object())
    reply = recorder.replies[-1][0]
    assert reply == "这是老板配置的积分说明。"
    assert db.business_context[-1][1]["conversion_target"] == "none"


def test_unconfigured_points_followup_does_not_reactivate_builtin_answer():
    from modules.keyword_trigger import KeywordTrigger

    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=recorder,
        ai=_NoReplyAi(),
        config={},
    )
    points_history = [
        {"role": "user", "content": "积分怎么使用", "intent": "积分兑换"},
        {"role": "assistant", "content": "积分可以兑换至臻精选会员。", "intent": "积分兑换"},
    ]

    followup = _message("门槛多少？")
    assert not trigger.handle_message(
        followup.text,
        followup.chat.id,
        followup,
        object(),
        conversation_history=points_history,
    )
    rule = trigger._match_special_rule("门槛多少？", conversation_history=points_history)
    assert rule is None
    assert trigger._match_special_rule("门槛多少？", conversation_history=[]) is None
    assert recorder.replies == []


def test_meet_mory_question_and_followups_use_social_unlock_not_chatbot_rejection():
    from modules.keyword_trigger import KeywordTrigger

    class _FailIfCalledAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("怎么约 Mory 必须先命中预设，不得交给模型乱答")

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_FailIfCalledAi(), config={})

    for text in (
        "怎么约你",
        "怎么约mory",
        "怎么和你约",
        "怎么跟你约",
        "怎么约到你",
        "怎样才能和Mory见面？",
        "我可以约你吗",
        "我想见你",
    ):
        assert trigger.handle_message(text, -1001, _message(text), object())
        reply = recorder.replies[-1][0]
        assert "@MorychannelBot" in reply
        assert "Mory 最终确认" in reply
        assert "只能在这里陪你聊天" not in reply
        assert "没有线下见面的安排" not in reply
        assert "想聊点什么" not in reply

    history = [
        {"role": "user", "content": "怎么联系Mory", "intent": "联系Mory"},
        {"role": "assistant", "content": recorder.replies[-1][0], "intent": "联系Mory"},
    ]
    followup = _message("线下呢？")
    assert trigger.handle_message(
        followup.text,
        followup.chat.id,
        followup,
        object(),
        conversation_history=history,
    )
    reply = recorder.replies[-1][0]
    assert "城市、事项和期望时间" in reply
    assert "是否安排由 Mory 最终确认" in reply
    assert not trigger._match_special_rule("怎么约朋友出去吃饭")
    assert not trigger._match_special_rule("怎么预约体检")
    assert not trigger._match_special_rule("怎么和你约定会议时间")


def test_private_short_business_questions_use_presets_without_widening_groups():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        db,
        mory_bot=recorder,
        ai=_NoReplyAi(),
        config={"FAQ_TRACKING_ENABLED": True, "CHECKIN_CONFIG": {"enabled": False}},
    )
    cases = {
        "可以约吗": "联系与社交解锁",
        "约吗": "联系与社交解锁",
        "怎么进群": "会员加入入口",
        "我怎么进群": "会员加入入口",
        "怎么加群": "会员加入入口",
        "会员群": "会员加入入口",
        "包年可以": "会员包年咨询",
        "预览": "预览入口",
        "刚刚开了会员，是可以聊定制了咩？": "已购会员定制承接",
    }
    for text, expected_rule in cases.items():
        message = _private_message(text)
        assert trigger.handle_message(text, message.chat.id, message, object())
        assert db.questions[-1]["answer_source"] == "preset"
        assert db.questions[-1]["answer_ref"] == expected_rule
        assert db.questions[-1]["ai_reply_summary"] == recorder.replies[-1][0]

    replies_before = len(recorder.replies)
    questions_before = len(db.questions)
    for text in ("签到！！！", "签到签到", "什么？我断签了🤪", "签到"):
        message = _private_message(text)
        assert not trigger.handle_message(text, message.chat.id, message, object())
    assert len(recorder.replies) == replies_before
    assert len(db.questions) == questions_before

    # 裸短句只有私聊对象明确时才承接；群聊不能猜成 Mory 业务。
    for text in ("可以约吗", "约吗", "怎么进群", "怎么加群", "会员群", "包年可以", "预览"):
        assert trigger._match_special_rule(text, is_private=False) is None


def test_explicit_group_business_questions_match_but_unrelated_topics_do_not():
    from modules.keyword_trigger import KeywordTrigger

    trigger = KeywordTrigger(_QuestionDb(), config={})
    expected = {
        "会员可以包年吗": "会员包年咨询",
        "至臻全享有年付吗": "会员包年咨询",
        "怎么加入VIP群": "会员加入入口",
        "会员群在哪里": "会员加入入口",
    }
    for text, rule_name in expected.items():
        rule = trigger._match_special_rule(text, is_private=False)
        assert rule and rule["name"] == rule_name, text

    for text in (
        "怎么进游戏群", "怎么加公司群", "群友怎么加",
        "健身房包年可以吗", "包年月嫂可以吗",
        "航空多少积分兑换机票", "信用卡积分不能兑换了吗", "商场积分换礼品",
    ):
        assert trigger._match_special_rule(text, is_private=False) is None, text


def test_new_business_presets_keep_each_problem_on_its_own_answer():
    from modules.keyword_trigger import KeywordTrigger

    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=recorder,
        ai=_NoReplyAi(),
        config={},
    )
    cases = {
        "至臻全享三个群分别是什么": ("至臻精选、至臻全享、精选图集", "14900"),
        "VIP订阅具体权益": ("最想要什么", "订单号"),
        "原味/视频定制规则": ("需求、预算和边界", "14900"),
        "官方联系方式": ("普通咨询直接在这里发", "积分商城"),
    }

    for text, (required, forbidden) in cases.items():
        assert trigger.handle_message(text, -1001, _message(text), object())
        reply = recorder.replies[-1][0]
        assert required in reply
        assert forbidden not in reply


def test_business_presets_cover_common_natural_phrasing_without_ai():
    from modules.keyword_trigger import KeywordTrigger

    class _FailIfCalledAi:
        def ask(self, *_args, **_kwargs):
            raise AssertionError("高频业务问法必须在 AI 前确定性命中")

    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=_ReplyRecorder(),
        ai=_FailIfCalledAi(),
        config={},
    )
    cases = {
        "至臻全享群说明": ("全享包括哪三个群", "至臻全享都有哪些群"),
        "VIP订阅权益说明": (
            "会员都包括什么", "VIP能干嘛", "订阅后可以得到什么", "会员有啥权益",
        ),
        "定制规则说明": ("原味怎么定制", "可以定制什么内容", "定制要准备什么"),
        "联系与社交解锁": (
            "微信怎么加", "可以加你微信吗", "怎么跟Mory联系", "会员怎么联系你", "想找Mory本人",
        ),
    }

    for expected_name, texts in cases.items():
        for text in texts:
            rule = trigger._match_special_rule(text)
            assert rule and rule["name"] == expected_name, text


def test_business_presets_reject_same_words_in_unrelated_topics():
    from modules.keyword_trigger import KeywordTrigger

    trigger = KeywordTrigger(_QuestionDb(), config={})
    unrelated = (
        "航空积分怎么用",
        "航空积分有什么福利",
        "定制家具流程是什么",
        "怎么加好友玩游戏",
        "怎么联系你们客服",
        "怎么约你们团队采访",
        "会员包含什么保险权益",
        "我想约你开会",
    )
    for text in unrelated:
        assert trigger._match_special_rule(text) is None, text

    contact_history = [
        {"role": "user", "content": "怎么联系Mory", "intent": "联系Mory"},
        {"role": "assistant", "content": "按当前社交解锁说明操作。", "intent": "联系Mory"},
    ]
    assert trigger._match_special_rule(
        "怎么约定会议时间",
        conversation_history=contact_history,
    ) is None


def test_example_config_rules_keep_project_topics_and_reject_shared_words():
    from modules.keyword_trigger import KeywordTrigger

    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    trigger = KeywordTrigger(_QuestionDb(), config=config)
    expected = {
        "这个多少钱": "价格咨询",
        "会员有哪些福利": "福利咨询",
        "福利在哪呀": "福利咨询",
        "有没有福利": "福利咨询",
        "会员里有什么内容": "内容咨询",
        "积分有什么用": "积分咨询",
        "积分有什么作用吗": "积分咨询",
        "积分有什么作用": "积分咨询",
        "签到有什么奖励": "签到奖励咨询",
        "签到有什么作用吗": "签到奖励咨询",
    }
    for text, name in expected.items():
        rule = trigger._match_special_rule(text)
        assert rule and rule["name"] == name, text

    unrelated = (
        "机票多少钱",
        "航空积分怎么用",
        "航空积分有什么福利",
        "会员包含什么保险权益",
        "这家公司的员工福利怎么样",
        "这本书有什么内容",
    )
    for text in unrelated:
        assert trigger._match_special_rule(text) is None, text


def test_configured_points_answer_keeps_owner_authored_reply_and_provenance():
    from modules.keyword_trigger import KeywordTrigger

    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    config["FAQ_TRACKING_ENABLED"] = True
    expected_rule = next(
        rule for rule in config["SPECIAL_AUTO_REPLIES"] if rule["name"] == "积分咨询"
    )
    expected_rule["ai_polish"] = False
    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config=config)
    message = _private_message("积分有什么用")

    assert trigger.handle_message(message.text, message.chat.id, message, object())
    assert recorder.replies[-1][0] == expected_rule["base_reply"]
    assert db.questions[-1]["answer_source"] == "preset"
    assert db.questions[-1]["answer_ref"] == "积分咨询"


def test_unconfigured_points_variants_do_not_become_presets():
    from modules.keyword_trigger import KeywordTrigger

    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    trigger = KeywordTrigger(_QuestionDb(), config=config)

    for text in (
        "多少积分兑换",
        "现在不可以用积分兑换了吗",
        "积分现在不能换会员了吗",
        "积分做什么",
        # v5.42.25 起 "签到有啥奖励" 已由 config.json.example 显式收录为
        # "签到奖励咨询" 的 keywords（老板确认），不再是"未配置变体"。
    ):
        assert trigger._match_special_rule(text, is_private=True) is None, text


def test_external_feature_classifier_covers_only_unowned_operational_topics():
    import modules.keyword_trigger as keyword_trigger

    classifier = getattr(keyword_trigger, "is_external_feature_text", None)
    assert callable(classifier)
    for text in (
        "签到！！！", "签到签到", "什么？我断签了🤪", "补签", "积分可以提现吗",
        "多少积分兑换", "积分商城", "/checkin", "/points", "积分有什么作用吗",
        "积分有啥作用",
    ):
        assert classifier(text), text

    for text in (
        "怎么订阅会员", "怎么进会员群", "包年可以吗", "预览",
        "刚开会员可以聊定制吗", "预约签到处", "连续订阅90天",
        "数学积分怎么求", "航空积分怎么兑换机票", "信用卡积分不能换了吗",
        "签到一份合同", "打卡景点推荐",
    ):
        assert not classifier(text), text


def test_external_feature_delegation_records_for_audit_without_generating_reply():
    import core.message_dispatcher as message_dispatcher

    handler = getattr(message_dispatcher, "_defer_external_feature", None)
    assert callable(handler)
    db = _QuestionDb()
    dctx = SimpleNamespace(
        ctx=SimpleNamespace(db=db, config={"FAQ_TRACKING_ENABLED": True}),
        text="签到！！！",
        uid=42,
        chat_id=42,
    )

    assert handler(dctx)
    assert db.questions == [{
        "uid": 42,
        "chat_id": 42,
        "question_text": "签到！！！",
        "mode": "normal",
        "intent": "external_feature",
        "keyword_tag": "",
        "question_category": "other",
        "is_convert": 0,
        "ai_reply_summary": "",
        "faq_hit_id": 0,
        "answer_source": "delegated",
        "answer_ref": "other_bot_feature",
    }]

    dctx.text = "怎么订阅会员"
    assert not handler(dctx)
    assert len(db.questions) == 1


def test_active_preset_question_families_keep_single_conversion_target():
    from modules.keyword_trigger import KeywordTrigger

    names = {
        "至臻全享群说明", "VIP订阅权益说明", "定制规则说明",
        "联系与社交解锁", "会员加入入口", "预览入口",
        "会员包年咨询", "已购会员定制承接",
    }
    active_rules = KeywordTrigger(_QuestionDb(), config={})._effective_special_rules()
    rules = [rule for rule in active_rules if rule["name"] in names]
    assert {rule["name"] for rule in rules} == names
    assert not {
        "签到积分福利", "积分兑换说明", "签到九十天兑换", "会员兑换未进群",
    } & {rule["name"] for rule in active_rules}

    for rule in rules:
        texts = [rule["base_reply"]]
        texts.extend(item["base_reply"] for item in rule.get("followup_replies", []))
        for text in texts:
            target = rule["conversion_target"]
            if target == "preview":
                assert "@morychannelbot" not in text.lower()
            elif target == "subscribe":
                assert "@moryselect" not in text.lower()
            else:
                assert "@moryselect" not in text.lower()
                assert "@morychannelbot" not in text.lower()


def test_static_early_rules_do_not_intercept_explicit_purchase():
    from modules.keyword_trigger import KeywordTrigger

    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=_ReplyRecorder(),
        ai=_NoReplyAi(),
        config={"SPECIAL_AUTO_REPLIES": [{
            "name": "价格咨询",
            "enabled": True,
            "keywords": ["多少钱", "定制视频"],
            "conversion_target": "preview",
            "base_reply": "以 @moryselect 预览为准。",
        }]},
    )

    assert trigger._match_special_rule("我要下单") is None
    assert trigger._match_special_rule("我要定制视频") is None
    assert trigger._match_special_rule("定制视频是什么") is None
    price_rule = trigger._match_special_rule("多少钱")
    assert price_rule and price_rule["conversion_target"] == "preview"


def test_config_can_disable_same_named_builtin_rule():
    from modules.keyword_trigger import KeywordTrigger

    trigger = KeywordTrigger(
        _QuestionDb(),
        mory_bot=_ReplyRecorder(),
        ai=_NoReplyAi(),
        config={
            "SPECIAL_AUTO_REPLIES": [{
                "name": "助理唤醒",
                "enabled": False,
                "keywords": ["助理出来"],
            }],
        },
    )

    assert not trigger.handle_message(
        "助理出来",
        -1001,
        _message("助理出来"),
        object(),
    )


def test_faq_match_consumes_highest_priority_list_entry():
    from core.handlers.ai_handlers import _try_faq_match

    db = _QuestionDb()
    answer, faq_id = _try_faq_match(
        db,
        {"FAQ_AUTO_REPLY_ENABLED": True},
        _NoReplyAi(),
        "积分能换什么",
        "normal",
        {},
    )

    assert answer == "签到积分可兑换VIP月卡等福利。"
    assert faq_id == 7
    assert db.faq_hits == [7]


def test_question_detection_and_handoff_rules():
    from core.handlers.ai_reply_handler import (
        _build_unresolved_handoff_markup,
        _looks_like_question,
        _should_offer_handoff,
    )

    assert _looks_like_question("签到积分有什么福利有什么")
    assert _looks_like_question("是定制视频的美女博主吗")
    assert not _looks_like_question("哈哈哈")
    assert _should_offer_handoff(
        "",
        faq_hit_id=0,
        ai_attempted=True,
    )
    assert _should_offer_handoff(
        "这个我不确定，建议问 Mory。",
        faq_hit_id=0,
        ai_attempted=True,
    )
    assert not _should_offer_handoff(
        "已经说清楚了。",
        faq_hit_id=3,
        ai_attempted=True,
    )

    markup = _build_unresolved_handoff_markup()
    assert len(markup.keyboard) == 1
    assert [button.text for button in markup.keyboard[0]] == ["联系 Mory"]
    assert [button.url for button in markup.keyboard[0]] == [
        "https://t.me/Moryfansbot",
    ]


def test_delayed_reply_preserves_custom_handoff_buttons(monkeypatch):
    from core import message_dispatcher

    class _ImmediateTimer:
        def __init__(self, _delay, callback):
            self.callback = callback
            self.daemon = False

        def start(self):
            self.callback()

    class _Bot:
        def __init__(self):
            self.edits = []

        def send_chat_action(self, *_args, **_kwargs):
            return None

        def edit_message_reply_markup(self, **kwargs):
            self.edits.append(kwargs)

    monkeypatch.setattr(message_dispatcher.threading, "Timer", _ImmediateTimer)
    bot = _Bot()
    recorder = _ReplyRecorder()
    markup = object()

    message_dispatcher._delayed_reply(
        bot,
        -1001,
        _message("问题"),
        "去联系 Mory。",
        0,
        recorder,
        is_priv=False,
        reply_markup=markup,
    )

    assert recorder.replies[0][1]["reply_markup"] is markup
    assert bot.edits == []


def test_daily_question_summary_separates_unresolved_and_faq_misses():
    from tasks.analytics.faq_distill_task import _build_daily_question_summary

    summary = _build_daily_question_summary([
        {
            "question_text": "这个能不能定制",
            "ai_reply_summary": "[UNRESOLVED] 不确定具体交付时间",
            "faq_hit_id": 0,
        },
        {
            "question_text": "积分能换什么",
            "ai_reply_summary": "积分可换福利",
            "faq_hit_id": 0,
        },
        {
            "question_text": "怎么订阅",
            "ai_reply_summary": "去自助下单",
            "faq_hit_id": 9,
        },
    ])

    assert "共记录 3 条｜FAQ命中 1 条｜预设命中 0 条｜入口直达 0 条｜待优化 1 条" in summary
    assert "待老板优化：" in summary
    assert "这个能不能定制" in summary
    assert "AI已答但FAQ/预设未命中：" in summary
    assert "积分能换什么" in summary


def test_daily_question_summary_counts_preset_and_direct_without_false_misses():
    from tasks.analytics.faq_distill_task import _build_daily_question_summary

    summary = _build_daily_question_summary([
        {
            "question_text": "可以约吗",
            "ai_reply_summary": "按当前社交解锁说明操作。",
            "faq_hit_id": 0,
            "answer_source": "preset",
            "answer_ref": "联系与社交解锁",
        },
        {
            "question_text": "怎么订阅",
            "ai_reply_summary": "去自助入口。",
            "faq_hit_id": 0,
            "answer_source": "direct_access",
            "answer_ref": "subscribe",
        },
        {
            "question_text": "这是什么新问题",
            "ai_reply_summary": "模型正常回答。",
            "faq_hit_id": 0,
            "answer_source": "ai",
            "answer_ref": "normal",
        },
    ])

    assert "预设命中 1 条｜入口直达 1 条｜待优化 0 条" in summary
    assert "AI已答但FAQ/预设未命中：" in summary
    assert "这是什么新问题" in summary
    assert "可以约吗" not in summary
    assert "怎么订阅" not in summary


def test_daily_question_summary_keeps_delegated_records_out_of_mory_optimization():
    from tasks.analytics.faq_distill_task import _build_daily_question_summary

    summary = _build_daily_question_summary([
        {
            "question_text": "签到！！！",
            "ai_reply_summary": "",
            "faq_hit_id": 0,
            "answer_source": "delegated",
            "answer_ref": "other_bot_feature",
        },
        {
            "question_text": "新的会员问题",
            "ai_reply_summary": "模型正常回答。",
            "faq_hit_id": 0,
            "answer_source": "ai",
            "answer_ref": "normal",
        },
    ])

    assert "共记录 1 条" in summary
    assert "其他机器人事项 1 条" in summary
    assert "签到！！！" not in summary
    assert "新的会员问题" in summary


def test_p10_answer_provenance_priorities_are_stable():
    from core.handlers.ai_reply_handler import _resolve_answer_provenance

    base = {
        "faq_hit_id": 0,
        "direct_access_handled": False,
        "direct_access_order": False,
        "needs_handoff": False,
        "ai_attempted": True,
        "response": "正常回答",
        "mode": "normal",
        "is_priv": True,
    }
    assert _resolve_answer_provenance(**base) == ("ai", "normal")
    assert _resolve_answer_provenance(**{**base, "faq_hit_id": 7}) == ("faq", "7")
    assert _resolve_answer_provenance(**{
        **base,
        "direct_access_handled": True,
        "direct_access_order": True,
    }) == ("direct_access", "subscribe")
    assert _resolve_answer_provenance(**{
        **base,
        "faq_hit_id": 7,
        "needs_handoff": True,
    }) == ("unresolved", "handoff")


def test_daily_question_summary_excludes_commands_and_model_fallback():
    from tasks.analytics.faq_distill_task import _build_daily_question_summary

    summary = _build_daily_question_summary([
        {
            "question_text": "/myid",
            "ai_reply_summary": "[UNRESOLVED] 这个我不乱说，直接问 @Moryfansbot。",
            "faq_hit_id": 0,
        },
        {
            "question_text": "/me@afoolGroupBot",
            "ai_reply_summary": "早啊～这是有事情要问我嘛",
            "faq_hit_id": 0,
        },
        {
            "question_text": "真牛",
            "ai_reply_summary": "[UNRESOLVED] 这个我不乱说，直接问 @Moryfansbot。",
            "faq_hit_id": 0,
        },
    ])

    assert "共记录 3 条｜FAQ命中 0 条｜预设命中 0 条｜入口直达 0 条｜待优化 0 条" in summary
    assert "待老板优化：" not in summary
    assert "AI已答但FAQ/预设未命中：" not in summary
    assert "/myid" not in summary
    assert "/me@afoolGroupBot" not in summary
    assert "真牛" not in summary


def test_daily_question_summary_excludes_plain_smalltalk_but_keeps_real_requests():
    from tasks.analytics.faq_distill_task import _build_daily_question_summary

    questions = [
        {
            "question_text": "你在干嘛",
            "ai_reply_summary": "在处理消息。",
            "faq_hit_id": 0,
        },
        {
            "question_text": "你忙吗？",
            "ai_reply_summary": "在。",
            "faq_hit_id": 0,
        },
        {
            "question_text": "你在干嘛帮我查积分",
            "ai_reply_summary": "还没查到。",
            "faq_hit_id": 0,
        },
        {
            "question_text": "积分怎么兑换会员",
            "ai_reply_summary": "按积分商城操作。",
            "faq_hit_id": 0,
        },
    ]

    summary = _build_daily_question_summary(questions)
    assert "共记录 4 条｜FAQ命中 0 条｜预设命中 0 条｜入口直达 0 条｜待优化 0 条" in summary
    assert "你在干嘛\n" not in summary
    assert "你忙吗" not in summary
    assert "你在干嘛帮我查积分" in summary
    assert "积分怎么兑换会员" in summary


def test_daily_summary_job_sends_to_admin():
    from tasks.analytics.faq_distill_task import FaqDistillTask

    class _Db:
        def get_questions(self, **_kwargs):
            return [{
                "question_text": "不知道怎么买",
                "ai_reply_summary": "[UNRESOLVED] 不确定",
                "faq_hit_id": 0,
            }]

    class _Bot:
        def __init__(self):
            self.sent = []

        def send_message(self, chat_id, text):
            self.sent.append((chat_id, text))

    rm = SimpleNamespace(
        config={
            "FAQ_TRACKING_ENABLED": True,
            "FAQ_DISTILL_INTERVAL": 86400,
            "ADMIN_ID": 777,
        },
        db=_Db(),
        bot=_Bot(),
    )
    task = FaqDistillTask(rm)

    schedules = {item["job_id"]: item for item in task.schedule()}
    assert schedules["faq_daily_question_summary"]["hour"] == 23
    assert schedules["faq_daily_question_summary"]["minute"] == 50

    task.run({"operation": "daily_summary"})
    assert rm.bot.sent[0][0] == 777
    assert "不知道怎么买" in rm.bot.sent[0][1]


def test_example_config_enables_requested_auto_answers():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )
    rules = {item["name"]: item for item in config["SPECIAL_AUTO_REPLIES"]}

    assert config["FAQ_AUTO_REPLY_ENABLED"] is True
    assert rules["助理唤醒"]["enabled"] is True
    assert rules["助理唤醒"]["conversion_target"] == "none"
    assert {"价格咨询", "福利咨询", "内容咨询"} <= set(rules)
    for name in ("价格咨询", "福利咨询", "内容咨询"):
        rule = rules[name]
        assert rule["enabled"] is True
        assert rule["conversion_target"] == "preview"
        assert rule["required_terms"] == ["@moryselect"]
        rendered = f"{rule['polish_prompt']} {rule['base_reply']}"
        assert "@MorychannelBot" not in rendered
        assert "@Moryfansbot" not in rendered
    assert "定制咨询" not in rules


def test_example_static_reply_config_does_not_assert_unverified_product_facts():
    config = json.loads(
        (Path(__file__).parents[2] / "config.json.example").read_text(encoding="utf-8")
    )

    slang_text = " ".join(config["SLANG_DICT"].values())
    assert all(term not in slang_text for term in ("4K母版", "三群", "1v1", "独家", "手慢无", "会员权益"))
    special_text = " ".join(
        f"{item['polish_prompt']} {item['base_reply']}"
        for item in config["SPECIAL_AUTO_REPLIES"]
    )
    assert all(term not in special_text for term in ("VIP月卡", "Mory确认", "手慢无"))
