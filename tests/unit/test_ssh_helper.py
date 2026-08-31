"""SSH helper 的 sudo 输入与敏感输出回归测试。"""

import importlib.util
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ssh_helper_under_test",
    ROOT / "scripts" / "ssh_helper.py",
)
assert SPEC and SPEC.loader
ssh_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ssh_helper)


class _FakeStream:
    def __init__(self, text="", exit_code=0):
        self._data = text.encode("utf-8")
        self.channel = type(
            "_Channel",
            (),
            {"recv_exit_status": lambda _self: exit_code},
        )()

    def read(self):
        return self._data


class _FakeStdin:
    def __init__(self):
        self.writes = []
        self.flush_count = 0

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        self.flush_count += 1


class _FakeClient:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStream(stdout, exit_code)
        self.stderr = _FakeStream(stderr)
        self.exec_calls = []
        self.connect_calls = []
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, *args, **kwargs):
        self.connect_calls.append((args, kwargs))

    def exec_command(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        return self.stdin, self.stdout, self.stderr

    def close(self):
        self.closed = True


def _patch_client(monkeypatch, client, password="unit-sudo-secret"):
    monkeypatch.setattr(ssh_helper, "PASS", password)
    monkeypatch.setattr(ssh_helper.paramiko, "SSHClient", lambda: client)


def test_root_command_uses_non_pty_and_writes_password_only_to_stdin(monkeypatch):
    password = "unit-sudo-secret"
    client = _FakeClient(
        stdout=f"command output {password}",
        stderr=f"warning {password}",
        exit_code=3,
    )
    _patch_client(monkeypatch, client, password)

    stdout, stderr, exit_code = ssh_helper.run_ssh("id", timeout=13, as_root=True)

    command, kwargs = client.exec_calls[0]
    assert kwargs == {"timeout": 13, "get_pty": False}
    assert command[0].startswith("sudo -S -p '' bash -c ")
    assert password not in command[0]
    assert client.stdin.writes == [password + "\n"]
    assert client.stdin.flush_count == 1
    assert password not in stdout
    assert password not in stderr
    assert stdout == "command output [REDACTED]"
    assert stderr == "warning [REDACTED]"
    assert exit_code == 3
    assert client.closed is True


def test_root_command_posix_quotes_multiline_and_single_quotes(monkeypatch):
    client = _FakeClient(stdout="ok")
    _patch_client(monkeypatch, client)
    remote = "printf '%s\\n' \"it's safe\"\nprintf done"

    stdout, stderr, exit_code = ssh_helper.run_ssh(remote, as_root=True)

    command, kwargs = client.exec_calls[0]
    assert command == (f"sudo -S -p '' bash -c {shlex.quote(remote)}",)
    assert kwargs == {"timeout": 60, "get_pty": False}
    assert stdout == "ok"
    assert stderr == ""
    assert exit_code == 0


def test_non_root_command_does_not_send_sudo_password_and_stays_non_pty(monkeypatch):
    password = "unit-sudo-secret"
    client = _FakeClient(stdout=f"normal {password}")
    _patch_client(monkeypatch, client, password)

    stdout, stderr, exit_code = ssh_helper.run_ssh("printf ok", as_root=False)

    command, kwargs = client.exec_calls[0]
    assert command == ("printf ok",)
    assert kwargs == {"timeout": 60, "get_pty": False}
    assert client.stdin.writes == []
    assert client.stdin.flush_count == 0
    assert password not in stdout
    assert stderr == ""
    assert exit_code == 0


def test_connection_failure_is_redacted_and_closes_client(monkeypatch):
    password = "unit-sudo-secret"
    client = _FakeClient()

    def fail_connect(*_args, **_kwargs):
        raise RuntimeError(f"connection detail {password}")

    client.connect = fail_connect
    _patch_client(monkeypatch, client, password)

    stdout, stderr, exit_code = ssh_helper.run_ssh("id", as_root=True)

    assert stdout == ""
    assert stderr == "SSH connect failed: connection detail [REDACTED]"
    assert password not in stderr
    assert exit_code == -1
    assert client.exec_calls == []
    assert client.closed is True


def test_exec_failure_is_redacted(monkeypatch):
    password = "unit-sudo-secret"
    client = _FakeClient()

    def fail_exec(*_args, **_kwargs):
        raise RuntimeError(f"execution detail {password}")

    client.exec_command = fail_exec
    _patch_client(monkeypatch, client, password)

    stdout, stderr, exit_code = ssh_helper.run_ssh("id", as_root=True)

    assert stdout == ""
    assert stderr == "exec failed: execution detail [REDACTED]"
    assert password not in stderr
    assert exit_code == -1
    assert client.closed is True
