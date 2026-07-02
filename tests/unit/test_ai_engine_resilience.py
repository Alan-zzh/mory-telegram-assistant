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

    result = engine.ask("全部失败测试", mode="normal", retry=1)

    assert result
    assert "Mory" in result
