"""中央 SSH 入口对无效密钥路径的密码回退测试。"""

from core import vps_config


class _Client:
    def __init__(self):
        self.policy = None
        self.connect_kwargs = None

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, host, **kwargs):
        self.connect_kwargs = {"host": host, **kwargs}


def test_missing_configured_key_falls_back_to_password(monkeypatch, tmp_path):
    client = _Client()
    missing_key = tmp_path / "missing-key"
    monkeypatch.setattr(vps_config, "VPS_HOST", "example.invalid")
    monkeypatch.setattr(vps_config, "VPS_PORT", 22)
    monkeypatch.setattr(vps_config, "VPS_USER", "ubuntu")
    monkeypatch.setattr(vps_config, "VPS_PASS", "fallback-secret")
    monkeypatch.setattr(vps_config, "VPS_KEY_FILES", [str(missing_key)])

    vps_config.ssh_connect(client, timeout=7)

    assert client.connect_kwargs["password"] == "fallback-secret"
    assert client.connect_kwargs["key_filename"] is None
    assert client.connect_kwargs["timeout"] == 7


def test_missing_configured_key_without_password_fails_before_connect(monkeypatch, tmp_path):
    client = _Client()
    monkeypatch.setattr(vps_config, "VPS_HOST", "example.invalid")
    monkeypatch.setattr(vps_config, "VPS_PASS", "")
    monkeypatch.setattr(vps_config, "VPS_KEY_FILES", [str(tmp_path / "missing-key")])

    import pytest

    with pytest.raises(ValueError, match="VPS_SSH_PASS / VPS_SSH_KEY"):
        vps_config.ssh_connect(client)

    assert client.connect_kwargs is None
