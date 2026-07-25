from datetime import datetime

import pytest

from core import ai_engine


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _config():
    return {
        "API_KEY": "test-key",
        "BASE_URL": "https://example.invalid/v1/chat/completions",
        "MAX_TOKENS": 32,
        "MODEL_POOLS": {
            "llm": [
                {"name": "fallback-a", "expire": "2099-12-31"},
                {"name": "fallback-b", "expire": "2099-12-31"},
            ],
            "llm_light": [
                {"name": "light-a", "expire": "2099-12-31"},
            ],
            "llm_standard": [
                {"name": "standard-a", "expire": "2099-12-31"},
            ],
            "llm_premium": [
                {"name": "premium-a", "expire": "2099-12-31"},
            ],
        },
        "MODE_ROUTING": {
            "morning": "llm_light",
            "normal": "llm_standard",
        },
        "BLACKLISTED_MODELS": [],
    }


def _engine(monkeypatch):
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    return ai_engine.AIEngine(_config())


def test_model_expire_date_is_valid_through_same_day(monkeypatch):
    engine = _engine(monkeypatch)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 2, 23, 59, 59)

    monkeypatch.setattr(ai_engine, "datetime", _FixedDateTime)

    assert engine._is_model_expired({"name": "same-day", "expire": "2026-07-02"}) is False
    assert engine._is_model_expired({"name": "yesterday", "expire": "2026-07-01"}) is True


def test_runtime_pools_skip_expired_and_blacklisted_models(monkeypatch):
    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 3, 9, 0, 0)

    cfg = _config()
    cfg["BLACKLISTED_MODELS"] = ["glm-5.2"]
    cfg["MODEL_POOLS"]["llm_standard"] = [
        {"name": "expired-a", "expire": "2026-07-02"},
        {"name": "glm-5.2", "expire": "2026-09-15"},
        {"name": "standard-ok", "expire": "2099-12-31"},
    ]
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "datetime", _FixedDateTime)
    engine = ai_engine.AIEngine(cfg)

    names = [m["name"] for m in engine._tier_pools["llm_standard"]]

    assert names == ["standard-ok"]
    assert engine._retry_model_count_for("llm_standard") >= 1
    assert "expired-a" in engine.blacklisted


def test_ask_switches_model_after_empty_content(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        if json["model"] == "light-a":
            return _FakeResponse(200, {"choices": [{"message": {"content": ""}}]})
        return _FakeResponse(200, {"choices": [{"message": {"content": "早安，今天继续稳稳推进。"}}]})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("早安测试", mode="morning", retry=1)

    assert result == "早安，今天继续稳稳推进。"
    assert calls[:2] == ["light-a", "standard-a"]


def test_ask_returns_fallback_when_all_requests_fail(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("全部失败测试", mode="normal", retry=1, is_priv=True)

    assert result == ""
    assert "模型" not in result
    assert "服务" not in result


def test_ask_does_not_emit_humanized_failure_phrase(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    for mode in ("normal", "tarot", "treehole", "feedback"):
        result = engine.ask("别再发尴尬兜底", mode=mode, retry=1, is_priv=True)
        assert result == ""
        assert "走神" not in result
        assert "等会儿再接" not in result


def test_ask_convert_failure_returns_fixed_access_entry(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("怎么买", mode="convert", retry=1, is_priv=False)

    assert "@MorychannelBot" in result
    assert "@moryselect" in result
    assert "走神" not in result


def test_ask_silences_normal_group_when_all_requests_fail(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("群聊普通闲聊失败测试", mode="normal", retry=1, is_priv=False)

    assert result == ""


def test_realtime_mode_skips_thinking_only_model_and_disables_thinking(monkeypatch):
    cfg = _config()
    cfg["MODEL_POOLS"]["llm_light"] = [
        {
            "name": "thinking-only",
            "expire": "2099-12-31",
            "enable_thinking": True,
        },
        {
            "name": "fast-model",
            "expire": "2099-12-31",
            "enable_thinking": False,
        },
    ]
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    engine = ai_engine.AIEngine(cfg)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "早。先挑一件真正要紧的事做。"}}]},
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("早安", mode="morning", retry=1)

    assert result == "早。先挑一件真正要紧的事做。"
    assert [call["model"] for call in calls] == ["fast-model"]
    assert calls[0]["enable_thinking"] is False


def test_greeting_mode_skips_code_specialized_models(monkeypatch):
    """粉丝群问候不能降级到 code/coder 专用模型。"""
    cfg = _config()
    cfg["MODEL_POOLS"]["llm_light"] = [
        {"name": "kimi-k2.7-code", "expire": "2099-12-31"},
        {"name": "qwen-chat", "expire": "2099-12-31"},
    ]
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    engine = ai_engine.AIEngine(cfg)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "午安呀，你们今天过得怎么样？来群里跟我说句话。"}}]},
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("午安", mode="afternoon", retry=1)

    assert result == "午安呀，你们今天过得怎么样？来群里跟我说句话。"
    assert calls == ["qwen-chat"]


def test_greeting_rejects_code_model_from_secondary_router(monkeypatch):
    """ModelRouter/A-B/成本覆盖也不能在请求前把问候改回 code 模型。"""
    import core.model_router as model_router

    cfg = _config()
    cfg["MODEL_ROUTER_ENABLED"] = True
    cfg["MODEL_POOLS"]["llm_light"] = [
        {"name": "qwen-chat", "expire": "2099-12-31"},
    ]
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        model_router,
        "route_model",
        lambda *_args: ("https://example.invalid/v1/chat/completions", "", "kimi-k2.7-code"),
    )
    engine = ai_engine.AIEngine(cfg)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "午安。今天过得怎么样，来群里跟我说说。"}}]},
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("午安", mode="afternoon", retry=1)

    assert result == "午安。今天过得怎么样，来群里跟我说说。"
    assert calls == ["qwen-chat"]


def test_stage_direction_filter_keeps_only_normal_chat_text():
    raw = "（托腮看窗外，听到提示音才回过神来）在呀～怎么啦，想我了？还是有什么事想跟我说？"

    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == "在呀～怎么啦，想我了？还是有什么事想跟我说？"
    # 混合回复可以直接清掉旁白，不需要额外消耗一次模型请求。
    assert triggered is False


def test_stage_direction_filter_preserves_factual_parentheses_and_plain_emphasis():
    raw = "（北京时间）明天八点开始，*重点*是别迟到；（长期低头会加重颈椎压力）。"

    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == raw
    assert triggered is False


def test_stage_direction_filter_handles_square_bracket_variants():
    raw = "【轻轻挑眉】[歪头看你]行啊，这次听你的。"

    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == "行啊，这次听你的。"
    assert triggered is False


def test_stage_only_reply_requests_retry_instead_of_sending_empty_text():
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2("*歪头看你*")

    assert cleaned == ""
    assert triggered is True


def test_persona_fragments_ignore_legacy_body_language_config(monkeypatch):
    cfg = _config()
    cfg["PERSONA_FRAGMENTS"] = {
        "mood_expressions": ["语气自然"],
        "reaction_styles": ["直接回应"],
        "body_language": ["*托着下巴想了想*"],
    }
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    engine = ai_engine.AIEngine(cfg)

    dynamic = engine._get_dynamic_fragments(seed=1)
    contextual = engine._get_context_aware_fragments("在吗", seed=1)

    assert "托着下巴" not in dynamic
    assert "托着下巴" not in contextual
    assert "语气基调" in dynamic
    assert "回应方式" in dynamic


def test_build_persona_keeps_traits_but_removes_legacy_action_instructions(monkeypatch):
    cfg = _config()
    cfg["BASE_PERSONA"] = (
        "底色是清冷、小傲娇、温柔。\n"
        "- 偶尔用*动作*模拟肢体语言：*歪头看你*\n"
        "- 肢体暗示：*凑近* / *假装生气扭头*"
    )
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    engine = ai_engine.AIEngine(cfg)

    prompt = engine._build_persona(
        "normal",
        seed=7,
        is_priv=True,
        message="在吗",
        model_name="qwen-plus",
    )

    assert "清冷、小傲娇、温柔" in prompt
    assert "偶尔用*动作*" not in prompt
    assert "肢体暗示" not in prompt
    assert "最终回复格式（最高优先级）" in prompt
    assert "只回复对方会直接看到的聊天正文" in prompt
    assert "对方没先调情就不要擅自加“想我了”" in prompt


def test_ask_strips_brain_scene_and_sends_normal_reply(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json)
        return _FakeResponse(
            200,
            {
                "choices": [{
                    "message": {
                        "content": (
                            "（托腮看窗外，听到提示音才回过神来）"
                            "在呀～怎么啦，想我了？还是有什么事想跟我说？"
                        )
                    }
                }]
            },
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("在吗", mode="normal", retry=1, is_priv=True)

    assert result == "在呀～怎么啦，想我了？还是有什么事想跟我说？"
    assert len(calls) == 1
    assert "最终回复格式（最高优先级）" in calls[0]["messages"][0]["content"]


def test_cached_reply_also_passes_stage_direction_filter(monkeypatch):
    engine = _engine(monkeypatch)

    class _Cache:
        @staticmethod
        def get(_question, _mode):
            return "（托腮看窗外）在呀，怎么啦？"

    class _Circuit:
        @staticmethod
        def is_available(_model):
            return True

    class _Optimizer:
        enabled = True
        cache = _Cache()
        circuit = _Circuit()

    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: _Optimizer())
    monkeypatch.setattr(
        ai_engine.requests,
        "post",
        lambda *_args, **_kwargs: pytest.fail("安全缓存命中时不应请求模型"),
    )

    result = engine.ask("在吗", mode="normal", retry=1, is_priv=True)

    assert result == "在呀，怎么啦？"
