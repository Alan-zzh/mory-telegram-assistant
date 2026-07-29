"""群自动回复六类人设合同与敌意兜底回归。"""

import json

import pytest

from core import ai_engine


def _config():
    return {
        "API_KEY": "test-key",
        "BASE_URL": "https://example.invalid/v1/chat/completions",
        "REPLY_CONTRACT_VERSION": "1.0.0",
        "PERSONA_ENGINE_ENABLED": True,
        "MODEL_POOLS": {
            "llm": [{"name": "qwen-test", "expire": "2099-12-31"}],
        },
        "BLACKLISTED_MODELS": [],
    }


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    return ai_engine.AIEngine(_config())


@pytest.mark.parametrize(
    ("message", "mode", "stage_hint", "expected"),
    [
        ("你好", "normal", "", "日常闲聊"),
        ("完整版真的是45秒？", "normal", "", "质疑挑战"),
        ("想你了", "normal", "", "轻暧昧互动"),
        ("我失恋了", "normal", "", "情绪倾诉"),
        ("有什么内容", "convert", "【意图-了解】只给 @moryselect", "好奇咨询"),
        ("我要订阅", "convert", "【意图-购买】只给 @MorychannelBot", "了解与成交"),
    ],
)
def test_group_prompt_routes_all_six_tone_contracts(
    engine,
    message,
    mode,
    stage_hint,
    expected,
):
    prompt = engine._build_persona(
        mode,
        seed=7,
        is_priv=False,
        stage_hint=stage_hint,
        message=message,
        model_name="qwen-test",
    )

    assert "全类型语气合同 v1.0.0" in prompt
    assert f"【本轮语气：{expected}】" in prompt
    assert "【渠道语气：群聊】" in prompt
    assert "温情" in prompt
    assert "轻微绿茶感" in prompt
    assert "俏皮" in prompt
    assert "纯欲" in prompt
    assert "不讽刺、不挖苦、不责怪、不命令、不赶客" in prompt


def test_private_channel_changes_weight_not_contract(engine):
    prompt = engine._build_persona(
        "normal",
        seed=8,
        is_priv=True,
        message="在吗",
        model_name="qwen-test",
    )

    assert "【本轮语气：日常闲聊】" in prompt
    assert "【渠道语气：私聊】" in prompt
    assert "不默认亲密关系" in prompt
    assert "想我了" in prompt
    assert "动作、环境、镜头、内心旁白" in prompt


def test_contract_mode_ignores_legacy_hostile_emotion_buckets(monkeypatch):
    cfg = _config()
    cfg["EMOTION_BUCKETS"] = {
        "cold": ["像在敷衍，不要给台阶"],
        "savage": ["让对方尴尬，禁止道歉"],
        "soft": ["装可怜"],
        "common": ["爱信不信"],
    }
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    engine = ai_engine.AIEngine(cfg)
    engine._ctx_is_priv = False
    engine._ctx_message = "你是机器人吗"
    engine._ctx_intimacy_score = 0

    hints = "\n".join(
        engine._get_anti_template_hint(seed=seed)
        for seed in range(1, 25)
    )

    assert "像在敷衍" not in hints
    assert "不要给台阶" not in hints
    assert "让对方尴尬" not in hints
    assert "爱信不信" not in hints
    assert "不讽刺" in json.dumps(
        engine._DEFAULT_EMOTION_BUCKETS,
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    "hostile",
    [
        "难不成我还得拿你发的这些东西证明？自己去看看，好坏你自己分辨就行。",
        "爱信不信，别再问了。",
        "问这么多干嘛，我懒得解释。",
    ],
)
def test_hostile_model_output_is_softened(hostile):
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(hostile)

    assert triggered is True
    assert cleaned == (
        "你会再确认很正常呀。我只按已经确认的信息跟你说，"
        "没把握的不会随口糊弄你。"
    )


def test_config_template_exposes_all_six_contracts():
    with open("config.json.example", encoding="utf-8") as handle:
        cfg = json.load(handle)

    contracts = cfg["DIALOGUE_TONE_CONTRACTS"]
    assert set(contracts) == {
        "shared",
        "casual",
        "curiosity",
        "flirt",
        "challenge",
        "emotional",
        "convert",
    }
    assert cfg["REPLY_CONTRACT_VERSION"] == "1.0.0"
    assert "温情" in cfg["BASE_PERSONA"]
    assert "不讽刺" in cfg["BASE_PERSONA"]
