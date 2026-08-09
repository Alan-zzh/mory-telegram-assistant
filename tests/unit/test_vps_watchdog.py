from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "vps_watchdog_under_test",
    _ROOT / "scripts" / "vps_watchdog.py",
)
assert _SPEC and _SPEC.loader
watchdog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(watchdog)


def test_health_requires_valid_json_status_ok(monkeypatch):
    monkeypatch.setattr(watchdog, "run", lambda *_args, **_kwargs: ('{"status":"ok"}', 0))
    assert watchdog.check_health()[0] is True

    monkeypatch.setattr(watchdog, "run", lambda *_args, **_kwargs: ('{"message":"not ok"}', 0))
    ok, detail = watchdog.check_health()
    assert ok is False
    assert "health 异常" in detail

    monkeypatch.setattr(watchdog, "run", lambda *_args, **_kwargs: ("not-json", 0))
    ok, detail = watchdog.check_health()
    assert ok is False
    assert "非法JSON" in detail


def test_run_keeps_stderr_for_restart_diagnostics(monkeypatch):
    class Result:
        stdout = ""
        stderr = "permission denied"
        returncode = 1

    monkeypatch.setattr(watchdog.subprocess, "run", lambda *_args, **_kwargs: Result())
    detail, code = watchdog.run(["systemctl", "restart", "mory-assistant"])
    assert code == 1
    assert detail == "permission denied"


def test_log_rotation_is_bounded(tmp_path, monkeypatch):
    log_file = tmp_path / "watchdog.log"
    log_file.write_text("x" * 20, encoding="utf-8")
    monkeypatch.setattr(watchdog, "LOG_FILE", str(log_file))
    monkeypatch.setattr(watchdog, "MAX_LOG_BYTES", 10)
    monkeypatch.setattr(watchdog, "LOG_BACKUPS", 2)

    watchdog.log("fresh")

    assert "fresh" in log_file.read_text(encoding="utf-8")
    assert (tmp_path / "watchdog.log.1").read_text(encoding="utf-8") == "x" * 20
    assert not (tmp_path / "watchdog.log.2").exists()
    assert not (tmp_path / "watchdog.log.3").exists()
