"""SSH 消费者统一 key-first 入口的回归测试。"""

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
