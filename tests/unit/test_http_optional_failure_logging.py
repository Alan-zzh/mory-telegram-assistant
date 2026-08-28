# -*- coding: utf-8 -*-
"""可选外部信号失败时不升级为系统 ERROR。"""

import pytest

from core.http_client import HTTPClient, HTTPRequestError, redact_url


def test_optional_request_can_suppress_final_error_log(monkeypatch):
    client = HTTPClient({"retry_times": 0, "enable_logging": True})
    monkeypatch.setattr(client, "_do_request", lambda _params: (_ for _ in ()).throw(TimeoutError("slow")))
    logged = []
    monkeypatch.setattr("core.http_client.logger.error", lambda message: logged.append(message))

    with pytest.raises(HTTPRequestError, match="HTTP请求失败"):
        client.get("https://optional.example", log_final_failure=False)

    assert logged == []


def test_http_failure_log_and_exception_redact_query_credentials(monkeypatch):
    """requests 异常可能回显完整 URL；日志和调用方收到的错误都不能携带 key。"""
    client = HTTPClient({"retry_times": 0, "enable_logging": True})
    secret = "weather-secret-must-not-leak"
    monkeypatch.setattr(
        client,
        "_do_request",
        lambda _params: (_ for _ in ()).throw(
            RuntimeError(f"upstream failed https://api.example.test/x?api_key={secret}")
        ),
    )
    logged = []
    monkeypatch.setattr("core.http_client.logger.error", lambda message: logged.append(message))

    with pytest.raises(HTTPRequestError) as exc_info:
        client.get("https://api.example.test/x", params={"location": "北京", "key": secret})

    assert secret not in str(exc_info.value)
    assert secret not in "\n".join(logged)
    assert "key=***" in str(exc_info.value)
    assert "api_key=***" in str(exc_info.value)


def test_http_success_log_redacts_query_credentials(monkeypatch):
    client = HTTPClient({"enable_logging": True})
    logged = []
    monkeypatch.setattr("core.http_client.logger.info", lambda message: logged.append(message))

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    import requests

    secret = "another-secret-must-not-leak"
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    assert client._do_request_with_requests(
        "GET", f"https://api.example.test/x?token={secret}", None, None, None, 1
    ) == {"ok": True}

    assert secret not in "\n".join(logged)
    assert "token=***" in logged[0]


def test_redact_url_hides_userinfo_and_sensitive_query_values():
    value = redact_url("https://alice:pass@example.test/x?city=beijing&access_token=hidden")

    assert "alice" not in value
    assert "pass" not in value
    assert "hidden" not in value
    assert "city=beijing" in value
    assert "access_token=***" in value


def test_post_does_not_retry_without_explicit_idempotency_opt_in(monkeypatch):
    client = HTTPClient({"retry_times": 2, "retry_delay": 0, "enable_logging": False})
    calls = []

    def fail(_params):
        calls.append(1)
        raise TimeoutError("result unknown")

    monkeypatch.setattr(client, "_do_request", fail)

    with pytest.raises(HTTPRequestError):
        client.post("https://api.example.test/create", retry_times=2)

    assert len(calls) == 1


def test_post_retry_requires_explicit_idempotency_opt_in(monkeypatch):
    client = HTTPClient({"retry_times": 2, "retry_delay": 0, "enable_logging": False})
    calls = []

    def fail_once(_params):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("result unknown")
        return {"ok": True}

    monkeypatch.setattr(client, "_do_request", fail_once)

    assert client.post(
        "https://api.example.test/create", retry_times=1, retry_unsafe=True
    ) == {"ok": True}
    assert len(calls) == 2


def test_get_keeps_default_retry_for_safe_read(monkeypatch):
    client = HTTPClient({"retry_times": 1, "retry_delay": 0, "enable_logging": False})
    calls = []

    def fail_once(_params):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("safe read timeout")
        return {"ok": True}

    monkeypatch.setattr(client, "_do_request", fail_once)

    assert client.get("https://api.example.test/read") == {"ok": True}
    assert len(calls) == 2
