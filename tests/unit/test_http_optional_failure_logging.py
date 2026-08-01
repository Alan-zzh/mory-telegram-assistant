# -*- coding: utf-8 -*-
"""可选外部信号失败时不升级为系统 ERROR。"""

import pytest

from core.http_client import HTTPClient, HTTPRequestError


def test_optional_request_can_suppress_final_error_log(monkeypatch):
    client = HTTPClient({"retry_times": 0, "enable_logging": True})
    monkeypatch.setattr(client, "_do_request", lambda _params: (_ for _ in ()).throw(TimeoutError("slow")))
    logged = []
    monkeypatch.setattr("core.http_client.logger.error", lambda message: logged.append(message))

    with pytest.raises(HTTPRequestError, match="HTTP请求失败"):
        client.get("https://optional.example", log_final_failure=False)

    assert logged == []
