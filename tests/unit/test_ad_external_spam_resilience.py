# -*- coding: utf-8 -*-
"""外部广告辅助服务失败时，不得阻塞本地广告检测。"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.http_client import HTTPClient, HTTPRequestError
from modules import ad_detector as ad_detector_module
from modules.ad_detector import AdDetector, SPB_COOLDOWN_SECONDS


@pytest.fixture
def reset_spb_circuit(monkeypatch):
    """每个用例都从 CLOSED 状态开始，避免进程级状态泄漏。"""
    monkeypatch.setattr(ad_detector_module, "_spb_cooldown_until", 0.0)
    monkeypatch.setattr(ad_detector_module, "_spb_probe_in_flight", False)
    monkeypatch.setattr(ad_detector_module, "_spb_circuit_generation", 0)


def test_http_client_explicit_zero_retry_makes_one_attempt(monkeypatch):
    """retry_times=0 必须关闭默认重试。"""
    client = HTTPClient({"retry_times": 2, "enable_logging": False})
    calls = []

    def fail_once(request_params):
        calls.append(request_params)
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(client, "_do_request", fail_once)

    with pytest.raises(HTTPRequestError):
        client.get("https://example.invalid", retry_times=0)

    assert len(calls) == 1


def test_spb_failure_cools_down_different_users_and_recovers(monkeypatch, reset_spb_circuit):
    """首次失败后跳过不同用户；冷却期结束且成功时恢复端点。"""
    now = {"value": 1_000.0}
    monkeypatch.setattr(ad_detector_module.time, "monotonic", lambda: now["value"])

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if len(self.calls) == 1:
                raise HTTPRequestError("SPB unavailable")
            return {"spam_prediction": {"spam_probability": 0.9, "is_spam": True}}

    client = Client()
    monkeypatch.setattr(ad_detector_module, "get_http_client", lambda: client)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})

    assert detector._check_spb(101) == (0.0, False)
    assert detector._check_spb(202) == (0.0, False)
    assert len(client.calls) == 1
    assert client.calls[0][1] == {
        "timeout": 1,
        "retry_times": 0,
        "log_final_failure": False,
    }

    now["value"] += SPB_COOLDOWN_SECONDS + 1
    assert detector._check_spb(303) == (0.9, True)
    assert len(client.calls) == 2
    assert ad_detector_module._spb_cooldown_until == 0.0


def test_detect_continues_when_spb_fails(monkeypatch, reset_spb_circuit):
    """SPB 出错只降级辅助信号，正常文本仍完成本地检测。"""
    class FailingClient:
        def get(self, url, **kwargs):
            raise HTTPRequestError("SPB unavailable")

    monkeypatch.setattr(ad_detector_module, "get_http_client", FailingClient)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})
    monkeypatch.setattr(detector, "_check_cas", lambda _user_id: (False, ""))

    result = detector.detect(username="普通用户", msg="大家好，今天天气不错", user_id=404)

    assert result["is_ad"] is False
    assert result["score"] == 0


def test_detect_keeps_local_ad_hit_when_spb_fails(monkeypatch, reset_spb_circuit):
    """外部 SPB 失败不能削弱本地明确广告规则。"""
    class FailingClient:
        def get(self, url, **kwargs):
            raise HTTPRequestError("SPB unavailable")

    monkeypatch.setattr(ad_detector_module, "get_http_client", FailingClient)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})
    monkeypatch.setattr(detector, "_check_cas", lambda _user_id: (False, ""))

    result = detector.detect(
        username="普通用户",
        msg="加我微信，日赚千元，私信联系",
        user_id=405,
    )

    assert result["is_ad"] is True
    assert result["action"] == "ban"
    assert result["score"] >= 3


def test_spb_parse_error_releases_probe_cools_down_and_recovers(monkeypatch, reset_spb_circuit):
    """响应解析失败也必须退出 HALF_OPEN，进入冷却后可由单探针恢复。"""
    now = {"value": 2_000.0}
    monkeypatch.setattr(ad_detector_module.time, "monotonic", lambda: now["value"])

    class Client:
        def __init__(self):
            self.calls = 0

        def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"spam_prediction": {"spam_probability": "not-a-number"}}
            return {"spam_prediction": {"spam_probability": 0.9, "is_spam": True}}

    client = Client()
    monkeypatch.setattr(ad_detector_module, "get_http_client", lambda: client)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})

    assert detector._check_spb(501) == (0.0, False)
    assert ad_detector_module._spb_probe_in_flight is False
    assert ad_detector_module._spb_cooldown_until == now["value"] + SPB_COOLDOWN_SECONDS
    assert detector._check_spb(502) == (0.0, False)
    assert client.calls == 1

    now["value"] += SPB_COOLDOWN_SECONDS + 1
    assert detector._check_spb(503) == (0.9, True)
    assert client.calls == 2
    assert ad_detector_module._spb_probe_in_flight is False
    assert ad_detector_module._spb_cooldown_until == 0.0


def test_stale_spb_success_does_not_close_newer_failure(monkeypatch, reset_spb_circuit):
    """generation 变化后，晚到的成功响应不得清除较新的失败冷却。"""
    now = {"value": 3_000.0}
    monkeypatch.setattr(ad_detector_module.time, "monotonic", lambda: now["value"])

    class StaleSuccessClient:
        def get(self, url, **kwargs):
            # 在旧探针返回前，模拟另一条失败已被熔断状态记录。
            with ad_detector_module._spb_circuit_lock:
                ad_detector_module._spb_circuit_generation += 1
                ad_detector_module._spb_cooldown_until = now["value"] + SPB_COOLDOWN_SECONDS
            return {"spam_prediction": {"spam_probability": 0.9, "is_spam": True}}

    monkeypatch.setattr(ad_detector_module, "get_http_client", StaleSuccessClient)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})

    assert detector._check_spb(601) == (0.9, True)
    assert ad_detector_module._spb_cooldown_until == now["value"] + SPB_COOLDOWN_SECONDS
    assert ad_detector_module._spb_probe_in_flight is False
    assert 601 not in detector._spb_cache


def test_spb_concurrent_requests_allow_at_most_one_probe(monkeypatch, reset_spb_circuit):
    """OPEN/HALF_OPEN 的同一窗口内，32 个线程只能有一个外部请求。"""
    class BlockingFailingClient:
        def __init__(self):
            self.calls = 0
            self.started = threading.Event()
            self.release = threading.Event()

        def get(self, url, **kwargs):
            self.calls += 1
            self.started.set()
            assert self.release.wait(timeout=2), "probe was not released"
            raise HTTPRequestError("SPB unavailable")

    client = BlockingFailingClient()
    monkeypatch.setattr(ad_detector_module, "get_http_client", lambda: client)
    detector = AdDetector({"AD_RULES": {"custom_rules": []}})
    start = threading.Barrier(32)
    skipped = threading.Event()
    completed = 0
    completed_lock = threading.Lock()

    def check(user_id):
        nonlocal completed
        start.wait(timeout=2)
        result = detector._check_spb(user_id)
        with completed_lock:
            completed += 1
            if completed == 31:
                skipped.set()
        return result

    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = [executor.submit(check, user_id) for user_id in range(1, 33)]
        assert client.started.wait(timeout=2), "no SPB probe started"
        assert skipped.wait(timeout=2), "other threads did not fail open"
        assert client.calls == 1
        client.release.set()
        assert [future.result(timeout=2) for future in futures] == [(0.0, False)] * 32

    assert client.calls == 1
