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
    assert "expired-a" not in engine.blacklisted


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (403, {"error": {"message": "free quota exhausted"}}, True),
        (429, {"error": {"message": "rate limit exceeded"}}, False),
        (403, {"error": {"message": "permission denied"}}, False),
        (500, {"error": {"message": "quota exhausted"}}, False),
    ],
)
def test_only_explicit_quota_exhaustion_is_permanent(status, payload, expected):
    response = _FakeResponse(status, payload)

    assert ai_engine.AIEngine._is_quota_exhausted_response(response) is expected


def test_rate_limit_switches_temporarily_without_blacklisting(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        if len(calls) == 1:
            return _FakeResponse(429, {"error": {"message": "rate limit exceeded"}})
        return _FakeResponse(200, {"choices": [{"message": {"content": "临时限流后已恢复。"}}]})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("限流切换测试", mode="normal", retry=1)

    assert result == "临时限流后已恢复。"
    assert calls[:2] == ["standard-a", "light-a"]
    assert "standard-a" not in engine.blacklisted
    assert engine._recovery_pending is True


def test_explicit_quota_exhaustion_blacklists_and_switches(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        if len(calls) == 1:
            return _FakeResponse(403, {"error": {"message": "free quota exhausted"}})
        return _FakeResponse(200, {"choices": [{"message": {"content": "额度模型已切换。"}}]})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("额度切换测试", mode="normal", retry=1)

    assert result == "额度模型已切换。"
    assert calls[:2] == ["standard-a", "light-a"]
    assert "standard-a" in engine.blacklisted


def test_transient_fallback_returns_to_earliest_expiry_on_next_request(monkeypatch):
    cfg = _config()
    cfg["MODEL_POOLS"] = {
        "llm": [
            {"name": "earliest", "expire": "2099-01-01", "enable_thinking": False},
            {"name": "later", "expire": "2099-02-01", "enable_thinking": False},
        ]
    }
    cfg["CURRENT_MODEL_INDEX"] = 0
    cfg["AI_MAX_ATTEMPTS"] = 2
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    engine = ai_engine.AIEngine(cfg)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json["model"])
        if len(calls) == 1:
            raise ai_engine.requests.exceptions.Timeout()
        text = "备用模型成功。" if len(calls) == 2 else "首选模型恢复。"
        return _FakeResponse(200, {"choices": [{"message": {"content": text}}]})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    assert engine.ask("第一次", mode="normal", retry=1) == "备用模型成功。"
    assert engine.ask("第二次", mode="normal", retry=1) == "首选模型恢复。"
    assert calls == ["earliest", "later", "earliest"]
    assert cfg["CURRENT_MODEL_INDEX"] == 0
    assert engine.current_model == "earliest"


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


def test_ask_sends_recent_conversation_before_current_message(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "对，就是这个方向。"}}]},
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask(
        "就是这个味",
        mode="convert",
        retry=1,
        conversation_history=[
            {"role": "user", "content": "定制舞", "intent": "purchase_intent"},
            {"role": "assistant", "content": "这个可以做。"},
            {"role": "system", "content": "不允许注入的角色"},
        ],
    )

    assert result == "对，就是这个方向。"
    assert calls[0]["messages"][1:] == [
        {"role": "user", "content": "定制舞"},
        {"role": "assistant", "content": "这个可以做。"},
        {"role": "user", "content": "就是这个味"},
    ]


def test_semantic_cache_key_includes_recent_conversation(monkeypatch):
    class _Cache:
        def __init__(self):
            self.values = {}
            self.get_keys = []

        def get(self, question, mode):
            self.get_keys.append((question, mode))
            return self.values.get((question, mode))

        def put(self, question, mode, value):
            self.values[(question, mode)] = value

    class _Circuit:
        @staticmethod
        def is_available(_model):
            return True

        @staticmethod
        def record_success(_model):
            return None

    cache = _Cache()
    optimizer = type(
        "_Optimizer",
        (),
        {"enabled": True, "cache": cache, "circuit": _Circuit()},
    )()
    monkeypatch.setattr(ai_engine, "init_optimizer", lambda: None)
    monkeypatch.setattr(ai_engine, "_get_optimizer", lambda: optimizer)
    monkeypatch.setattr(ai_engine.time, "sleep", lambda _seconds: None)
    engine = ai_engine.AIEngine(_config())
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json)
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": f"真实请求第{len(calls)}次。"}}]},
        )

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    first = engine.ask(
        "就是这个味",
        mode="normal",
        retry=1,
        conversation_history=[{"role": "user", "content": "定制舞"}],
    )
    second = engine.ask(
        "就是这个味",
        mode="normal",
        retry=1,
        conversation_history=[{"role": "user", "content": "这首歌"}],
    )

    assert first == "真实请求第1次。"
    assert second == "真实请求第2次。"
    assert len(calls) == 2
    assert cache.get_keys[0][0] != cache.get_keys[1][0]


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


def test_ask_convert_failure_defers_single_entry_to_handler(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("怎么买", mode="convert", retry=1, is_priv=False)

    assert "@MorychannelBot" not in result
    assert "@moryselect" not in result
    assert "对应入口" in result
    assert "走神" not in result


def test_ask_silences_normal_group_when_all_requests_fail(monkeypatch):
    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("群聊普通闲聊失败测试", mode="normal", retry=1, is_priv=False)

    assert result == ""


def test_realtime_mode_uses_priority_thinking_model_with_verified_contract(monkeypatch):
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
    assert [call["model"] for call in calls] == ["thinking-only"]
    assert calls[0]["enable_thinking"] is True


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


def test_normal_persona_chat_also_skips_code_specialized_models():
    """普通人设聊天不能因前序模型超时降级到代码专用模型。"""
    assert not ai_engine.AIEngine._is_model_suitable_for_mode(
        "kimi-k2.7-code",
        "normal",
    )
    assert not ai_engine.AIEngine._is_model_suitable_for_mode(
        "some-coder-model",
        "convert",
    )
    assert ai_engine.AIEngine._is_model_suitable_for_mode(
        "kimi-k2.7-code",
        "code",
    )


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
    assert triggered is True


def test_stage_direction_filter_preserves_factual_parentheses_and_plain_emphasis():
    raw = "（北京时间）明天八点开始，*重点*是别迟到；（长期低头会加重颈椎压力）。"

    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == raw
    assert triggered is False


def test_stage_direction_filter_handles_square_bracket_variants():
    raw = "【轻轻挑眉】[歪头看你]行啊，这次听你的。"

    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == "行啊，这次听你的。"
    assert triggered is True


def test_stage_only_reply_requests_retry_instead_of_sending_empty_text():
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2("*歪头看你*")

    assert cleaned == ""
    assert triggered is True


@pytest.mark.parametrize("raw", [
    "48什么？话都不说全，你是在考我阅读理解吗",
    "这么猛？说清楚点嘛",
    "七八点？我干嘛告诉你～",
    "替你尴尬，自己玩去。",
])
def test_historical_hostile_replies_are_replaced(raw):
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == "我可能没接准你的意思，你再补一句就好。"
    assert triggered is True


@pytest.mark.parametrize("raw,expected", [
    ("*瞥一眼手机* 七八点。", "七八点。"),
    ("……没太看懂。*揉眼睛*", "……没太看懂。"),
])
def test_historical_action_narration_is_removed(raw, expected):
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

    assert cleaned == expected
    assert triggered is True


@pytest.mark.parametrize("raw", [
    "作为一个 AI，我不需要睡觉。",
    "我是机器人，没有现实生活。",
])
def test_identity_leak_is_never_sent(raw):
    cleaned, triggered = ai_engine.AIEngine._sanitize_reply_v2(raw)

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
    assert len(calls) == 2
    assert "最终回复格式（最高优先级）" in calls[0]["messages"][0]["content"]
    assert "上一条回复违反输出规范" in calls[1]["messages"][-1]["content"]


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


def test_sanitize_retry_flag_is_cleared_after_total_failure(caplog, monkeypatch):
    """穿帮自愈重试置位后若全败，兜底路径必须清理标记，下次调用仍保留自愈能力；
    且自愈重试的 payload 必须真正应用降温度与约束注入（不被重建覆盖）。"""
    engine = _engine(monkeypatch)
    calls = []

    def record_call(json):
        messages = json.get("messages", [])
        calls.append({
            "temperature": json.get("temperature"),
            "has_constraint": any(
                isinstance(m, dict) and m.get("content", "").startswith("(Constraint Warning)")
                for m in messages
            ),
        })

    def fake_post(_url, json, headers, timeout):
        record_call(json)
        # 第一次响应触发穿帮过滤（降温度重试），之后全部超时
        if len(calls) == 1:
            return _FakeResponse(200, {"choices": [{"message": {"content": "我不能帮你处理这个。"}}]})
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    first = engine.ask("第一次触发穿帮后全败", mode="normal", retry=1, is_priv=True)

    base_temp = calls[0]["temperature"]
    assert first == ""
    assert not hasattr(engine, "_sanitize_retry_done")  # 全败兜底后标记必须已清理
    # 自愈重试的第二次调用必须真正降温度并注入约束警告
    assert calls[1]["temperature"] == pytest.approx(max(0.3, base_temp * 0.5))
    assert calls[1]["has_constraint"] is True

    calls.clear()

    def fake_post_second(_url, json, headers, timeout):
        record_call(json)
        if len(calls) == 1:
            return _FakeResponse(200, {"choices": [{"message": {"content": "我不能帮你处理这个。"}}]})
        return _FakeResponse(200, {"choices": [{"message": {"content": "好，那就不提这个了。"}}]})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post_second)

    caplog.clear()
    with caplog.at_level("WARNING", logger="ai_engine"):
        second = engine.ask("第二次仍应触发自愈", mode="normal", retry=1, is_priv=True)

    assert second == "好，那就不提这个了。"
    # 若标记残留，第二次 ask 会跳过自愈重试分支，不会出现降温度日志
    assert any("降温度重试" in record.getMessage() for record in caplog.records)
    # 标记已清理：第二次 ask 的首次调用不降温度、无约束注入；重试调用才应用
    assert calls[0]["temperature"] == pytest.approx(base_temp)
    assert calls[0]["has_constraint"] is False
    assert calls[1]["temperature"] == pytest.approx(max(0.3, base_temp * 0.5))
    assert calls[1]["has_constraint"] is True


def test_sanitize_retry_flag_cleared_on_quota_exhaustion_early_exit(monkeypatch):
    """穿帮置位后模型池因 402/403 拉黑耗尽提前兜底，标记同样必须清理。"""
    engine = _engine(monkeypatch)
    calls = []

    def fake_post(_url, json, headers, timeout):
        calls.append(json.get("temperature"))
        # 第一次响应触发穿帮过滤（置位降温度重试），之后模型返回 402 被拉黑耗尽
        if len(calls) == 1:
            return _FakeResponse(200, {"choices": [{"message": {"content": "我不能帮你处理这个。"}}]})
        return _FakeResponse(402, {"error": {"message": "free quota exhausted"}})

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)

    result = engine.ask("穿帮后额度耗尽", mode="normal", retry=1, is_priv=True)

    assert result == ""
    assert not hasattr(engine, "_sanitize_retry_done")  # 池耗尽早退后标记必须已清理


def test_get_pool_info_returns_all_pools(monkeypatch):
    """get_pool_info 应返回全部模型池状态且字段完整（回归：此前 pool 未定义会 NameError）。"""
    engine = _engine(monkeypatch)

    info = engine.get_pool_info()

    for pool_name in engine.POOL_NAMES:
        assert pool_name in info, f"缺少池 {pool_name}"
        row = info[pool_name]
        assert {"total", "current", "index", "blacklisted_count", "blacklisted"} <= set(row)
    for tier_name in ("llm_light", "llm_standard", "llm_premium"):
        assert {"slow_count", "slow"} <= set(info[tier_name])


def test_failure_chain_log_carries_request_id(caplog, monkeypatch):
    """失败链日志应携带线程上下文中的 request_id 关联键，便于跨进程串联诊断。"""
    from core.logging_util import clear_logging_context, set_logging_context

    engine = _engine(monkeypatch)

    def fake_post(_url, json, headers, timeout):
        raise ai_engine.requests.exceptions.Timeout()

    monkeypatch.setattr(ai_engine.requests, "post", fake_post)
    set_logging_context(request_id="req-fix-test-0001")
    try:
        with caplog.at_level("WARNING", logger="ai_engine"):
            engine.ask("日志关联测试", mode="normal", retry=1, is_priv=True)
    finally:
        clear_logging_context()

    assert any("req-fix-test-0001" in record.getMessage() for record in caplog.records)
