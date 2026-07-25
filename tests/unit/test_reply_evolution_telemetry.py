# -*- coding: utf-8 -*-
from core.quality_evaluator import QualityEvaluator
from core.telemetry import Telemetry, TelemetryContext


class _ImmediatePool:
    def submit(self, callback):
        callback()


class _TelemetryDb:
    def __init__(self):
        self.conversations = []
        self.events = []

    def log_conversation_telemetry(self, *args):
        self.conversations.append(args)

    def log_telemetry(self, *args):
        self.events.append(args)


def _telemetry_config(raw_event_text):
    return {
        "AB_TEST_CONFIG": {"telemetry_enabled": True},
        "REPLY_EVOLUTION_CONFIG": {"raw_event_text": raw_event_text},
    }


def test_raw_event_text_false_keeps_structure_without_message_or_reply(monkeypatch):
    import core.telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module, "_telemetry_pool", _ImmediatePool())
    db = _TelemetryDb()
    telemetry = Telemetry(db, _telemetry_config(False))

    telemetry.log_conversation(
        1, -100, "persona_quality", "stable",
        "我想下单", "去 @MorychannelBot 自助完成", "purchase", 3,
    )
    telemetry.log_conversion(1, -100, "persona_quality", "stable", 9.9)
    telemetry.log_complaint(1, -100, "persona_quality", "stable", "重复推销")
    telemetry.log_group_leave(1, -100, "persona_quality", "stable")

    conversation = db.conversations[0]
    assert conversation[4:9] == ("", "", "purchase", "positive", 3)
    assert [event[4] for event in db.events] == [
        "conversion", "complaint", "group_leave"
    ]


def test_raw_event_text_true_persists_context_message_and_reply(monkeypatch):
    import core.telemetry as telemetry_module

    monkeypatch.setattr(telemetry_module, "_telemetry_pool", _ImmediatePool())
    db = _TelemetryDb()
    context = TelemetryContext(
        Telemetry(db, _telemetry_config(True)),
        user_id=2,
        chat_id=-200,
        experiment_id="persona_quality",
        variant="stable",
    )

    context.on_user_message("多少钱", intent="price")
    context.on_bot_reply("先去 @moryselect 看预览", intent="price")

    conversation = db.conversations[0]
    assert conversation[4:9] == (
        "多少钱", "先去 @moryselect 看预览", "price", "positive", 1
    )


def test_quality_prompt_uses_transparent_identity_and_stage_contract():
    evaluator = QualityEvaluator(ai=None, db=None, config={})
    prompt = evaluator._build_eval_prompt({
        "message_text": "你是真人吗",
        "bot_reply_text": "我是 Mory 的小助理。",
        "intent": "identity",
        "sentiment": "neutral",
    })

    assert "透明助理身份" in prompt
    assert "如实说明“我是 Mory 的小助理”" in prompt
    assert "不得冒充真人" in prompt
    assert "普通聊天、情绪支持、拒绝/取消、定制概念咨询：不得出现销售入口" in prompt
    assert "价格、内容、权益、想先了解：只允许引导 @moryselect" in prompt
    assert "明确购买/下单/套餐选择、确认看过预览" in prompt
    assert "只允许引导 @MorychannelBot" in prompt
    assert "每轮最多一个" in prompt
    assert "虚假稀缺" in prompt
    assert "虚假社会认同" in prompt
    assert "编造价格、福利、商品内容、定制能力、交付、人工回访" in prompt


def test_quality_evaluator_drops_empty_raw_text_before_sampling_or_prompting():
    evaluator = QualityEvaluator(
        ai=None,
        db=None,
        config={"QUALITY_EVAL_SAMPLE_RATE": 1.0},
    )
    empty = {"id": 1, "message_text": "", "bot_reply_text": "", "ts": 1}
    valid = {
        "id": 2,
        "message_text": "今天有点累",
        "bot_reply_text": "那就先歇一会儿，别硬撑。",
        "ts": 2,
    }

    assert evaluator._sample_conversations([empty]) == []
    assert evaluator._sample_conversations([empty, valid]) == [valid]
    assert evaluator._build_eval_prompt(empty) == ""
