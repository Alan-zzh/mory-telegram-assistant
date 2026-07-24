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
