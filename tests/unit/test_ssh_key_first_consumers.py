"""SSH 消费者统一 key-first 入口的回归测试。"""

from pathlib import Path

import paramiko

from dashboard import helpers
from scripts import cleanup_vps_full


class _Stream:
    def __init__(self, value=b"", exit_code=0):
        self.value = value
        self.closed = False
        self.channel = self
        self.exit_code = exit_code

    def read(self):
        return self.value

    def close(self):
        self.closed = True

    def recv_exit_status(self):
        return self.exit_code


class _Client:
    def __init__(self, *, stderr=b"", exit_code=0):
        self.stdin = _Stream()
        self.stdout = _Stream(b"ok", exit_code=exit_code)
        self.stderr = _Stream(stderr)
        self.exec_calls = []
        self.closed = False

    def exec_command(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        return self.stdin, self.stdout, self.stderr

    def close(self):
        self.closed = True


class _StatusClient(_Client):
    def __init__(self, status_output):
        super().__init__()
        self.status_output = status_output

    def exec_command(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        command = args[0]
        if command.startswith("if systemctl is-active"):
            return _Stream(), _Stream(self.status_output), _Stream()
        if command.startswith("uptime"):
            return _Stream(), _Stream(b"up 3 days"), _Stream()
        raise AssertionError(f"unexpected command: {command}")


class _MediaStatusClient(_Client):
    def exec_command(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        command = args[0]
        if "grep mory_media" in command:
            return _Stream(), _Stream(b"ubuntu 4242 1 0 00:00 ? 00:00 python mory_media /home/ubuntu/mory_assistant/main.py"), _Stream()
        if command.startswith("ps -p 4242"):
            return _Stream(), _Stream(b"20480"), _Stream()
        if command.startswith("uptime"):
            return _Stream(), _Stream(b"up 3 days"), _Stream()
        raise AssertionError(f"unexpected command: {command}")


def test_dashboard_ssh_exec_uses_central_entrypoint_and_closes_streams(monkeypatch):
    client = _Client()
    calls = []
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(
        helpers,
        "ssh_connect",
        lambda value, timeout=15: calls.append((value, timeout)),
    )

    stdout, stderr = helpers.ssh_exec("printf ok", timeout=9)

    assert calls == [(client, 9)]
    assert stdout == "ok"
    assert stderr == ""
    assert client.exec_calls == [(('printf ok',), {'timeout': 9})]
    assert client.stdin.closed is True
    assert client.stdout.closed is True
    assert client.stderr.closed is True
    assert client.closed is True


def test_cleanup_sudo_uses_nopasswd_without_pty_or_password_write():
    client = _Client()

    output = cleanup_vps_full._sudo_run(client, "sudo -n id -u", timeout=11)

    assert output == "ok"
    assert client.exec_calls == [
        (("sudo -n id -u",), {"timeout": 11, "get_pty": False})
    ]
    assert client.stdin.value == b""
    assert client.stdin.closed is True
    assert client.stdout.closed is True
    assert client.stderr.closed is True


def test_cleanup_sudo_rejection_raises_instead_of_reporting_success():
    client = _Client(stderr=b"sudo: a password is required", exit_code=1)

    import pytest

    with pytest.raises(RuntimeError, match=r"exit=1"):
        cleanup_vps_full._sudo_run(client, "sudo -n install source target")


def test_cleanup_logrotate_tempfile_uses_linux_lf():
    temp_path = Path(cleanup_vps_full._write_logrotate_tempfile())
    try:
        content = temp_path.read_bytes()
    finally:
        temp_path.unlink()

    assert content == cleanup_vps_full.LOGROTATE_CONF.encode("utf-8")
    assert b"\r\n" not in content
    assert content.endswith(b"}\n")


def test_dashboard_main_status_uses_systemd_pid_and_memory(monkeypatch):
    client = _StatusClient(b"2971288 51600\n")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(helpers, "ssh_connect", lambda value, timeout=10: None)
    monkeypatch.setenv("DASHBOARD_MODE", "main")
    helpers._vps_cache.update({"data": None, "updated_at": 0})

    result = helpers.get_vps_status()

    assert result["bot_running"] is True
    assert result["bot_pid"] == "2971288"
    assert result["bot_memory"] == "50 MB"
    assert result["uptime"] == "up 3 days"
    assert client.exec_calls[0][0][0].startswith("if systemctl is-active --quiet mory-assistant")


def test_dashboard_main_status_stays_offline_when_systemd_has_no_pid(monkeypatch):
    client = _StatusClient(b"")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(helpers, "ssh_connect", lambda value, timeout=10: None)
    monkeypatch.setenv("DASHBOARD_MODE", "main")
    helpers._vps_cache.update({"data": None, "updated_at": 0})

    result = helpers.get_vps_status()

    assert result["bot_running"] is False
    assert result["bot_pid"] is None


def test_dashboard_media_status_keeps_existing_process_probe(monkeypatch):
    client = _MediaStatusClient()
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    monkeypatch.setattr(helpers, "ssh_connect", lambda value, timeout=10: None)
    monkeypatch.setenv("DASHBOARD_MODE", "media")
    helpers._vps_cache.update({"data": None, "updated_at": 0})

    result = helpers.get_vps_status()

    assert result["bot_running"] is True
    assert result["bot_pid"] == "4242"
    assert result["bot_memory"] == "20 MB"
    assert all("systemctl" not in call[0][0] for call in client.exec_calls)
