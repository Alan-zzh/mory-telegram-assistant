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


def test_builtin_points_answer_uses_preview_and_custom_concept_is_not_static_order():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config={})

    points_msg = "签到积分有什么福利"
    video_msg = "定制视频是什么"
    assert trigger.handle_message(points_msg, -1001, _message(points_msg), object())
    assert not trigger.handle_message(video_msg, -1001, _message(video_msg), object())

    assert "@moryselect" in recorder.replies[0][0]
    assert "VIP月卡" not in recorder.replies[0][0]
    assert "@Moryfansbot" not in recorder.replies[0][0]
    assert len(recorder.replies) == 1


def test_preset_question_families_answer_new_points_questions_without_llm():
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
            "name": "旧积分咨询",
            "topic": "积分",
            "enabled": True,
            "keywords": ["积分"],
            "conversion_target": "none",
            "base_reply": "旧的泛化回答",
        }]},
    )

    text = "积分怎么使用"
    assert trigger.handle_message(text, -1001, _message(text), object())
    reply = recorder.replies[-1][0]
    assert "14900" in reply
    assert "积分商城" in reply
    assert "至臻精选会员" in reply
    assert "旧的泛化回答" not in reply
    assert "@moryselect" not in reply.lower()
    assert "@morychannelbot" not in reply.lower()
    assert db.business_context[-1][1]["conversion_target"] == "none"


def test_preset_question_family_followups_stay_bound_to_previous_topic():
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
    assert trigger.handle_message(
        followup.text,
        followup.chat.id,
        followup,
        object(),
        conversation_history=points_history,
    )
    assert recorder.replies[-1][0].startswith("当前门槛是 14900 积分")

    rule = trigger._match_special_rule("门槛多少？", conversation_history=points_history)
    assert rule["name"] == "积分兑换说明"
    assert rule["base_reply"].startswith("当前门槛是 14900 积分")
    assert trigger._match_special_rule("门槛多少？", conversation_history=[]) is None


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
        "兑换成功但没进群": ("订单号文字和成功凭证截图", "三个群"),
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
        "积分兑换说明": (
            "积分怎么兑换会员", "签到积分怎么用", "积分兑换会员需要多少分",
            "我有14900积分怎么换", "签到多久能换会员",
        ),
        "签到九十天兑换": (
            "签到九十天可以换吗", "连续签到三个月能换会员吗", "我签了90天能换VIP吗",
        ),
        "会员兑换未进群": (
            "我兑换会员了怎么还没进群", "积分换完怎么没拉我进群", "兑换成功了没收到群链接",
        ),
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
        "我的积分有多少": "积分咨询",
        "签到有什么奖励": "签到奖励咨询",
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


def test_new_preset_question_families_keep_single_conversion_target():
    from modules.keyword_trigger import _DEFAULT_SPECIAL_AUTO_REPLIES

    names = {
        "积分兑换说明", "签到九十天兑换", "会员兑换未进群",
        "至臻全享群说明", "VIP订阅权益说明", "定制规则说明",
        "联系与社交解锁",
    }
    rules = [rule for rule in _DEFAULT_SPECIAL_AUTO_REPLIES if rule["name"] in names]
    assert {rule["name"] for rule in rules} == names

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

    assert "共记录 3 条｜FAQ命中 1 条｜待优化 1 条" in summary
    assert "待老板优化：" in summary
    assert "这个能不能定制" in summary
    assert "AI已答但FAQ未命中：" in summary
    assert "积分能换什么" in summary


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

    assert "共记录 3 条｜FAQ命中 0 条｜待优化 0 条" in summary
    assert "待老板优化：" not in summary
    assert "AI已答但FAQ未命中：" not in summary
    assert "/myid" not in summary
    assert "/me@afoolGroupBot" not in summary
    assert "真牛" not in summary


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
