# -*- coding: utf-8 -*-
"""监控与 Windows 验证门禁的回归测试。"""

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_loop_monitor_expected_version_tracks_runtime_version():
    """监控版本基线必须跟随唯一运行时版本，禁止手写旧版本。"""
    from scripts import puzan_loop_monitor
    from version import VERSION

    assert puzan_loop_monitor.EXPECTED_VERSION == VERSION


def test_loop_monitor_warn_is_not_reported_as_all_normal(monkeypatch, tmp_path, capsys):
    """任一层 WARN 都必须进入最终建议，不能继续输出 all normal。"""
    from scripts import puzan_loop_monitor as monitor

    class _Client:
        def close(self):
            return None

    monkeypatch.setattr(monitor, "make_ssh_client", lambda: _Client())
    monkeypatch.setattr(monitor, "l1_vps_check", lambda _c: ("OK", {}))
    monkeypatch.setattr(
        monitor,
        "l2_service_check",
        lambda _c: ("OK", {"mory-assistant": "active", "mory-dashboard": "active"}),
    )
    monkeypatch.setattr(
        monitor,
        "l3_app_check",
        lambda _c: ("OK", {"health_raw": "ok", "version": "v-test", "home_http_code": "200"}),
    )
    monkeypatch.setattr(monitor, "l4_biz_check", lambda _c: ("OK", {}))
    monkeypatch.setattr(monitor, "l5_scheduler_check", lambda _c: ("OK", {}))
    monkeypatch.setattr(
        monitor,
        "l6_watchdog_check",
        lambda _c: (
            "WARN",
            {
                "watchdog_log_age_sec": 9999,
                "cron_tasks": "(none)",
                "legacy_cron_residue": "(none)",
                "_warn": "watchdog_log_stale(9999s); cron_missing; ",
            },
        ),
    )
    monkeypatch.setattr(
        monitor,
        "tencent_lighthouse_check",
        lambda: {"status": "ok", "instance_state": "RUNNING", "public_ip": "", "metrics_note": "test"},
    )

    monitor.run_single_round(1, 1, tmp_path / "monitor.log")
    output = capsys.readouterr().out

    assert "[RECOMMEND] [NEEDS_REVIEW]" in output
    assert "L6" in output
    assert "[RECOMMEND] all normal" not in output


def test_watchdog_layer_warns_when_cron_is_missing(monkeypatch):
    """日志即使刚更新，只要 watchdog 调度入口消失也必须告警。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if "date +%s" in command:
            return "1000", "", 0
        if "stat -c" in command:
            return "999", "", 0
        return "", "", 0

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l6_watchdog_check(object())

    assert status == "WARN"
    assert "cron_missing" in details.get("_warn", "")


def test_verify_db_methods_survives_non_utf8_parent_console():
    """Windows 非 UTF-8 父控制台下脚本仍应以 0 退出。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "ascii"
    result = subprocess.run(
        [sys.executable, "scripts/verify_db_methods.py"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def test_alembic_config_is_readable_with_windows_default_encoding():
    """alembic.ini 不应依赖 UTF-8 locale 才能解析。"""
    env = os.environ.copy()
    env.pop("PYTHONUTF8", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
