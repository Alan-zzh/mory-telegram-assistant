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


def test_business_layer_uses_execution_history_instead_of_task_lock(monkeypatch):
    """业务任务量必须来自四态历史，不能把临时防重锁当执行事实。"""
    from scripts import puzan_loop_monitor as monitor

    seen_sql = []

    def _sqlite_query(_client, db_path, sql, timeout=20):
        seen_sql.append((db_path, sql))
        if "GROUP BY status" in sql:
            return "success|7\nfailed|2\naborted|1", ""
        if "-5 minutes" in sql and "task_execution_history" in sql:
            return "3", ""
        if "task_execution_history" in sql:
            return "10", ""
        return "0", ""

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)

    status, details = monitor.l4_biz_check(object())

    assert status == "OK"
    assert details["task_1h"] == "10"
    assert details["task_5min"] == "3"
    assert details["task_status_1h"] == {
        "success": 7,
        "failed": 2,
        "aborted": 1,
        "running": 0,
    }
    task_sql = "\n".join(sql for db_path, sql in seen_sql if db_path == monitor.MORY_DB)
    assert "task_execution_history" in task_sql
    assert "FROM task_log" not in task_sql


def test_scheduler_layer_warns_from_persisted_failures_without_journal(monkeypatch):
    """即使 journal 窗口为空，持久化 failed/missed 也必须让调度层告警。"""
    from scripts import puzan_loop_monitor as monitor

    seen_sql = []

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        seen_sql.append(sql)
        if "GROUP BY status" in sql:
            return "success|8\nfailed|2", ""
        if "status='running'" in sql:
            return "0", ""
        if "status='failed'" in sql:
            return "job_b|failed|upstream timeout|1786200000", ""
        if "FROM scheduler_metrics" in sql:
            return "job_b|error|2|0|1786200000|upstream timeout", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "job_b|failed|2026-08-09", ""
        raise AssertionError(sql)

    def _ssh_run(_client, command, timeout=10):
        if "WatchdogUSec" in command:
            return "0", "", 0
        return "", "", 0

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)
    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l5_scheduler_check(object())

    assert status == "WARN"
    assert details["failed_1h"] == 2
    assert details["stale_running_30m"] == 0
    assert "persisted_task_failures=2" in details["_warn"]
    assert details["fail_log_10min"] == "(none)"
    assert any("task_execution_history" in sql for sql in seen_sql)
    assert any("scheduler_metrics" in sql for sql in seen_sql)


def test_scheduler_layer_fails_closed_when_execution_history_is_unreadable(monkeypatch):
    """四态历史不可读时不能回退成健康。"""
    from scripts import puzan_loop_monitor as monitor

    monkeypatch.setattr(
        monitor,
        "sqlite_query",
        lambda _client, _db_path, _sql, timeout=20: ("", "sqlite3 err code=1: database is locked"),
    )
    monkeypatch.setattr(monitor, "ssh_run", lambda _client, _command, timeout=10: ("", "", 0))

    status, details = monitor.l5_scheduler_check(object())

    assert status == "ERROR"
    assert "execution_history_query_failed" in details.get("_crit", "")


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
    # 【v5.38.9 修复】alembic 是部署侧依赖，本地/CI 环境可能未安装；
    # 缺失时跳过而非失败，避免误报。
    import importlib.util
    if importlib.util.find_spec("alembic") is None:
        import pytest
        pytest.skip("alembic 未安装，跳过 alembic.ini 解析测试")
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
