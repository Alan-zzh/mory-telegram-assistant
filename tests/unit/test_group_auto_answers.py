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


def test_builtin_persona_wakeup_replies_and_keeps_conversion_entry():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config={})

    assert trigger.handle_message("助理出来", -1001, _message("助理出来"), object())
    assert recorder.replies
    assert "@MorychannelBot" in recorder.replies[0][0]
    assert db.telemetry[0][3] == "助理唤醒"


def test_builtin_points_and_custom_video_answers_cover_user_examples():
    from modules.keyword_trigger import KeywordTrigger

    db = _QuestionDb()
    recorder = _ReplyRecorder()
    trigger = KeywordTrigger(db, mory_bot=recorder, ai=_NoReplyAi(), config={})

    points_msg = "签到积分有什么福利有什么"
    video_msg = "是定制视频的美女博主吗"
    assert trigger.handle_message(points_msg, -1001, _message(points_msg), object())
    assert trigger.handle_message(video_msg, -1001, _message(video_msg), object())

    assert "VIP月卡" in recorder.replies[0][0]
    assert "@Moryfansbot" in recorder.replies[0][0]
    assert "定制视频" in recorder.replies[1][0]
    assert "Mory确认" in recorder.replies[1][0]


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
            "ai_reply_summary": "[UNRESOLVED] 这个我不乱说",
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
    assert rules["签到积分福利"]["enabled"] is True
    assert rules["福利咨询"]["enabled"] is True
    assert rules["定制咨询"]["enabled"] is True
