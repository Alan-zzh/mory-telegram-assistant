# -*- coding: utf-8 -*-
"""监控与 Windows 验证门禁的回归测试。"""

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _healthy_l1_ssh_run(_client, command, timeout=10):
    """Return a complete L1 fixture so each negative case changes one signal."""
    if command.startswith("top "):
        return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
    if command == "free -m":
        return "Mem: 8000 3000 1000 0 0 4000", "", 0
    if command.startswith("df -h"):
        return "/dev/vda1 100G 59G 41G 59% /", "", 0
    if command.startswith("ss -tn"):
        return "12", "", 0
    if command == "uptime":
        return "up 1 day", "", 0
    if command == "cat /proc/loadavg":
        return "1.00 1.20 1.30 1/100 1", "", 0
    if command.startswith("systemctl show"):
        return "/system.slice/mory-assistant.service\n/system.slice/mory-dashboard.service", "", 0
    if "Memory cgroup out of memory" in command:
        return "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=0\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=0", "", 0
    raise AssertionError(command)


def test_loop_monitor_expected_version_tracks_runtime_version():
    """监控版本基线必须跟随唯一运行时版本，禁止手写旧版本。"""
    from scripts import puzan_loop_monitor
    from version import VERSION

    assert puzan_loop_monitor.EXPECTED_VERSION == VERSION


def test_app_layer_reads_remote_version_instead_of_health_payload(monkeypatch):
    """health 只判 liveness；部署版本必须直接读取 VPS version.py。"""
    from scripts import puzan_loop_monitor as monitor

    seen_commands = []

    def _ssh_run(_client, command, timeout=10):
        seen_commands.append(command)
        if "curl -sS" in command:
            return '{"status":"ok"}\n200', "", 0
        if "from version import VERSION" in command:
            return monitor.EXPECTED_VERSION, "", 0
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l3_app_check(object())

    assert status == "OK"
    assert details["health_http_code"] == "200"
    assert details["version"] == monitor.EXPECTED_VERSION
    assert details["version_source"].endswith("/version.py")
    assert any("from version import VERSION" in command for command in seen_commands)


def test_app_layer_does_not_trust_version_embedded_in_health(monkeypatch):
    """即使 health 伪带正确版本，远端 version.py 不一致仍必须告警。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if "curl -sS" in command:
            return f'{{"status":"ok","version":"{monitor.EXPECTED_VERSION}"}}\n200', "", 0
        if "from version import VERSION" in command:
            return "v0.0.0", "", 0
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l3_app_check(object())

    assert status == "WARN"
    assert details["version"] == "v0.0.0"
    assert "version_mismatch" in details["_warn"]


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

    receipt = monitor.run_single_round(1, 1, tmp_path / "monitor.log")
    output = capsys.readouterr().out

    assert "[RECOMMEND] [NEEDS_REVIEW]" in output
    assert "L6" in output
    assert "[RECOMMEND] all normal" not in output
    assert receipt["status"] == "failed"


def test_vps_layer_warns_on_recent_cgroup_oom_even_when_free_memory_recovered(monkeypatch):
    """共享主机 OOM 不能因当前 available 内存回升而从巡检中消失。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if command.startswith("top "):
            return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
        if command == "free -m":
            return "Mem: 8000 3000 1000 0 0 4000", "", 0
        if command.startswith("df -h"):
            return "/dev/vda1 100G 59G 41G 59% /", "", 0
        if command.startswith("ss -tn"):
            return "12", "", 0
        if command == "uptime":
            return "up 1 day", "", 0
        if command == "cat /proc/loadavg":
            return "1.00 1.20 1.30 1/100 1", "", 0
        if command.startswith("systemctl show"):
            return "/system.slice/mory-assistant.service\n/system.slice/mory-dashboard.service", "", 0
        if "Memory cgroup out of memory" in command:
            event = (
                "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,"
                "oom_memcg=/system.slice/docker-abcdef1234567890.scope,"
                "task_memcg=/system.slice/docker-abcdef1234567890.scope,task=chromium"
            )
            victim = "kernel: Memory cgroup out of memory: Killed process 1 (chromium)"
            body = "\n".join([event, victim] * 7)
            return "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=7\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=14\n" + body, "", 0
        if command.startswith("docker inspect"):
            return "abcdef1234567890:/steel-browser", "", 0
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "WARN"
    assert details["oom_kills_1h"] == 7
    assert details["oom_cgroup_kills_1h"] == 7
    assert details["oom_global_kills_1h"] == 0
    assert details["oom_source_mory_1h"] == 0
    assert details["oom_source_external_1h"] == 7
    assert details["oom_source_unknown_1h"] == 0
    assert details["oom_victim_mory_1h"] == 0
    assert details["oom_source_labels_1h"] == "docker:abcdef123456=7"
    assert details["oom_victim_processes_1h"] == "chromium=7"
    assert details["oom_external_containers_1h"] == "steel-browser=7"
    assert details["oom_attribution_complete"] is True
    assert details["oom_journal_ok"] is True
    assert details["oom_control_groups_available"] is True
    assert details["oom_evidence_truncated"] is False
    assert "external_oom_source_1h(7)" in details["_warn"]


def test_vps_layer_marks_mory_cgroup_oom_critical(monkeypatch):
    """Mory 自身 service cgroup 被杀必须与外部容器 OOM 分开并升级为 CRITICAL。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if command.startswith("top "):
            return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
        if command == "free -m":
            return "Mem: 8000 3000 1000 0 0 4000", "", 0
        if command.startswith("df -h"):
            return "/dev/vda1 100G 59G 41G 59% /", "", 0
        if command.startswith("ss -tn"):
            return "12", "", 0
        if command == "uptime":
            return "up 1 day", "", 0
        if command == "cat /proc/loadavg":
            return "1.00 1.20 1.30 1/100 1", "", 0
        if command.startswith("systemctl show"):
            return "/system.slice/mory-assistant.service\n/system.slice/mory-dashboard.service", "", 0
        if "Memory cgroup out of memory" in command:
            return (
                "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=1\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=2\n"
                "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,"
                "oom_memcg=/system.slice/mory-assistant.service,"
                "task_memcg=/system.slice/mory-assistant.service,task=python3\n"
                "kernel: Memory cgroup out of memory: Killed process 2 (python3)",
                "",
                0,
            )
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "CRITICAL"
    assert details["oom_kills_1h"] == 1
    assert details["oom_source_mory_1h"] == 1
    assert details["oom_source_external_1h"] == 0
    assert details["oom_victim_mory_1h"] == 1
    assert details["oom_source_labels_1h"] == "mory-assistant.service=1"
    assert "mory_oom_source(1)" in details["_crit"]
    assert "mory_oom_victim(1)" in details["_crit"]


def test_oom_parser_separates_source_victim_and_keeps_unpaired_events_unknown():
    """source 与 victim 分开；全局/无来源/无法配对事件必须留在 unknown。"""
    from scripts import puzan_loop_monitor as monitor

    details = monitor._parse_oom_journal(
        "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=2\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=2\n"
        "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=(null),"
        "task_memcg=/system.slice/mory-dashboard.service,task=python3\n"
        "kernel: Memory cgroup out of memory: Killed process 2 (python3)",
        {"/system.slice/mory-dashboard.service"},
    )

    assert details["oom_kills_1h"] == 2
    assert details["oom_source_mory_1h"] == 0
    assert details["oom_source_external_1h"] == 0
    assert details["oom_source_unknown_1h"] == 2
    assert details["oom_victim_mory_1h"] == 1
    assert details["oom_attribution_complete"] is False


def test_oom_parser_counts_global_oom_and_truncation_as_incomplete():
    """主机级 OOM 或日志截断都不能静默显示 attribution complete。"""
    from scripts import puzan_loop_monitor as monitor

    details = monitor._parse_oom_journal(
        "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=0\n__OOM_GLOBAL_TOTAL__=1\n__OOM_MATCHED_TOTAL__=2\n"
        "kernel: oom-kill:constraint=CONSTRAINT_NONE,oom_memcg=(null),"
        "task_memcg=/system.slice/mory-assistant.service,task=python3\n"
        "kernel: Out of memory: Killed process 9 (python3)",
        {"/system.slice/mory-assistant.service"},
    )

    assert details["oom_kills_1h"] == 1
    assert details["oom_global_kills_1h"] == 1
    assert details["oom_source_unknown_1h"] == 1
    assert details["oom_victim_mory_1h"] == 1
    assert details["oom_evidence_truncated"] is False
    assert details["oom_attribution_complete"] is False


def test_oom_parser_marks_external_pressure_with_mory_victim_separately():
    """外部/上级 cgroup 压力与 Mory 受害进程不能共用一个字段。"""
    from scripts import puzan_loop_monitor as monitor

    details = monitor._parse_oom_journal(
        "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=1\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=2\n"
        "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice,"
        "task_memcg=/system.slice/mory-assistant.service,task=python3\n"
        "kernel: Memory cgroup out of memory: Killed process 4 (python3)",
        {"/system.slice/mory-assistant.service"},
    )

    assert details["oom_source_mory_1h"] == 0
    assert details["oom_source_external_1h"] == 1
    assert details["oom_victim_mory_1h"] == 1
    assert details["oom_attribution_complete"] is True


def test_oom_parser_marks_extra_constraint_and_non_path_sources_unknown():
    """额外 constraint 或非绝对 cgroup 路径都必须破坏完整归因。"""
    from scripts import puzan_loop_monitor as monitor

    extra_constraint = monitor._parse_oom_journal(
        "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=1\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=3\n"
        "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=/system.slice/other.service,"
        "task_memcg=/system.slice/other.service,task=worker\n"
        "kernel: oom-kill:constraint=CONSTRAINT_NONE,oom_memcg=(null),task_memcg=(null)\n"
        "kernel: Memory cgroup out of memory: Killed process 4 (worker)",
        {"/system.slice/mory-assistant.service"},
    )
    bogus_path = monitor._parse_oom_journal(
        "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=1\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=2\n"
        "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=bogus,task_memcg=bogus,task=x\n"
        "kernel: Memory cgroup out of memory: Killed process 5 (x)",
        {"/system.slice/mory-assistant.service"},
    )

    assert extra_constraint["oom_source_external_1h"] == 1
    assert extra_constraint["oom_source_unknown_1h"] == 1
    assert extra_constraint["oom_attribution_complete"] is False
    assert bogus_path["oom_source_external_1h"] == 0
    assert bogus_path["oom_source_unknown_1h"] == 1
    assert bogus_path["oom_attribution_complete"] is False


def test_vps_layer_incomplete_oom_attribution_never_reports_ok(monkeypatch):
    """即使总数为零，只要事件证据不完整就必须保持 WARN。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if command.startswith("top "):
            return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
        if command == "free -m":
            return "Mem: 8000 3000 1000 0 0 4000", "", 0
        if command.startswith("df -h"):
            return "/dev/vda1 100G 59G 41G 59% /", "", 0
        if command.startswith("ss -tn"):
            return "12", "", 0
        if command == "uptime":
            return "up 1 day", "", 0
        if command == "cat /proc/loadavg":
            return "1.00 1.20 1.30 1/100 1", "", 0
        if command.startswith("systemctl show"):
            return "/system.slice/mory-assistant.service", "", 0
        if "Memory cgroup out of memory" in command:
            return (
                "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=0\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=1\n"
                "kernel: oom-kill:constraint=CONSTRAINT_MEMCG,oom_memcg=(null),task_memcg=(null)",
                "",
                0,
            )
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "WARN"
    assert details["oom_attribution_complete"] is False
    assert "oom_attribution_incomplete" in details["_warn"]


def test_vps_layer_zero_oom_keeps_otherwise_healthy_resources_ok(monkeypatch):
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if command.startswith("top "):
            return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
        if command == "free -m":
            return "Mem: 8000 3000 1000 0 0 4000", "", 0
        if command.startswith("df -h"):
            return "/dev/vda1 100G 59G 41G 59% /", "", 0
        if command.startswith("ss -tn"):
            return "12", "", 0
        if command == "uptime":
            return "up 1 day", "", 0
        if command == "cat /proc/loadavg":
            return "1.00 1.20 1.30 1/100 1", "", 0
        if command.startswith("systemctl show"):
            return "/system.slice/mory-assistant.service\n/system.slice/mory-dashboard.service", "", 0
        if "Memory cgroup out of memory" in command:
            return "__OOM_JOURNAL_OK__=1\n__OOM_CGROUP_TOTAL__=0\n__OOM_GLOBAL_TOTAL__=0\n__OOM_MATCHED_TOTAL__=0", "", 0
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "OK"
    assert details["oom_kills_1h"] == 0
    assert details["oom_source_mory_1h"] == 0
    assert details["oom_source_external_1h"] == 0
    assert details["oom_source_unknown_1h"] == 0
    assert details["oom_attribution_complete"] is True
    assert details["oom_journal_ok"] is True
    assert "_warn" not in details


def test_vps_layer_command_failure_is_visible_as_l1_evidence_gap(monkeypatch):
    """基础命令返回 127 时不能因其它指标正常而假绿。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(client, command, timeout=10):
        if command.startswith("top "):
            return "", "top: command not found", 127
        return _healthy_l1_ssh_run(client, command, timeout)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "WARN"
    assert details["l1_evidence_gaps"] == ["top(rc=127,stderr,cpu_missing)"]
    assert details["l1_evidence_gap_only"] is True
    assert "l1_evidence_gap=top(" in details["_warn"]


def test_vps_layer_empty_resource_output_is_visible_as_l1_evidence_gap(monkeypatch):
    """命令 exit 0 但关键输出为空时也必须标记证据缺口。"""
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(client, command, timeout=10):
        if command == "free -m":
            return "", "", 0
        return _healthy_l1_ssh_run(client, command, timeout)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "WARN"
    assert details["l1_evidence_gaps"] == ["free(mem_available_missing)"]
    assert details["l1_evidence_gap_only"] is True
    assert "l1_evidence_gap=free(" in details["_warn"]


def test_vps_layer_oom_evidence_failure_is_not_reported_healthy(monkeypatch):
    from scripts import puzan_loop_monitor as monitor

    def _ssh_run(_client, command, timeout=10):
        if command.startswith("top "):
            return "%Cpu(s): 10.0 us,  5.0 sy,  0.0 ni, 85.0 id\n", "", 0
        if command == "free -m":
            return "Mem: 8000 3000 1000 0 0 4000", "", 0
        if command.startswith("df -h"):
            return "/dev/vda1 100G 59G 41G 59% /", "", 0
        if command.startswith("ss -tn"):
            return "12", "", 0
        if command == "uptime":
            return "up 1 day", "", 0
        if command == "cat /proc/loadavg":
            return "1.00 1.20 1.30 1/100 1", "", 0
        if command.startswith("systemctl show"):
            return "", "systemctl unavailable", 1
        if "Memory cgroup out of memory" in command:
            return "", "journal unavailable", 1
        raise AssertionError(command)

    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l1_vps_check(object())

    assert status == "WARN"
    assert details["oom_kills_1h"] == "unavailable"
    assert details["oom_source_mory_1h"] == "unavailable"
    assert details["oom_source_external_1h"] == "unavailable"
    assert details["oom_source_unknown_1h"] == "unavailable"
    assert details["oom_external_containers_1h"] == "unavailable"
    assert details["oom_attribution_complete"] is False
    assert details["oom_journal_ok"] is False
    assert "oom_evidence_unavailable" in details["_warn"]


def test_loop_monitor_ssh_failure_is_evidence_gap(monkeypatch, tmp_path):
    from scripts import puzan_loop_monitor as monitor

    monkeypatch.setattr(monitor, "make_ssh_client", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    receipt = monitor.run_single_round(1, 1, tmp_path / "monitor.log")

    assert receipt["status"] == "evidence_gap"


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
        if "COUNT(*) FROM task_execution_history;" in sql:
            return "209", ""
        if "ORDER BY id DESC LIMIT 1" in sql:
            return "mystic_evening|success|1788179700", ""
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
    assert details["transactional_task_1h"] == "10"
    assert details["transactional_task_5min"] == "3"
    assert details["task_history_total"] == "209"
    assert details["task_history_latest"] == "mystic_evening|success|1788179700"
    assert details["task_history_coverage"] == "TaskTransactionManager_only"
    assert details["task_status_1h"] == {
        "success": 7,
        "failed": 2,
        "aborted": 1,
        "running": 0,
    }
    task_sql = "\n".join(sql for db_path, sql in seen_sql if db_path == monitor.MORY_DB)
    assert "task_execution_history" in task_sql
    assert "FROM task_log" not in task_sql


def test_business_layer_empty_transaction_window_keeps_explicit_coverage(monkeypatch):
    """事务窗口和历史均为空不等于调度故障，仍须明示有限覆盖。"""
    from scripts import puzan_loop_monitor as monitor

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        if "GROUP BY status" in sql or "ORDER BY id DESC LIMIT" in sql:
            return "", ""
        return "0", ""

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)

    status, details = monitor.l4_biz_check(object())

    assert status == "OK"
    assert details["transactional_task_1h"] == "0"
    assert details["task_history_total"] == "0"
    assert details["task_history_latest"] == ""
    assert details["task_history_coverage"] == "TaskTransactionManager_only"


def test_business_layer_counts_current_second_level_conversion_event(monkeypatch):
    """conversion_events 的当前事件使用秒级 Unix ts，不能再乘 1000。"""
    from scripts import puzan_loop_monitor as monitor

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE conversion_events (ts REAL)")
    db.execute("INSERT INTO conversion_events(ts) VALUES (?)", (int(time.time()),))
    db.commit()
    seen_sql = []

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        seen_sql.append(sql)
        if "FROM conversion_events" in sql:
            return str(db.execute(sql).fetchone()[0]), ""
        if "GROUP BY status" in sql:
            return "success|1", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "heartbeat|success|0", ""
        return "0", ""

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)

    status, details = monitor.l4_biz_check(object())

    conversion_sql = next(sql for sql in seen_sql if "FROM conversion_events" in sql)
    assert status == "OK"
    assert details["conversion_1h"] == "1"
    assert "*1000" not in conversion_sql
    assert "strftime('%s', datetime('now', '-1 hour'))" in conversion_sql


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
        if "last_status IN" in sql:
            return "job_b|error|2|0|1786200000|upstream timeout", ""
        if "AS error_scope" in sql and "last_status_at" in sql:
            return "job_b|error|2|0|1786200000|1786200000|current|upstream timeout", ""
        if "AS error_scope" in sql:
            return "job_b|error|2|0|1786200000|current|upstream timeout", ""
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
    assert details["transactional_failed_1h"] == 2
    assert details["transactional_task_status_1h"]["failed"] == 2
    assert details["task_history_coverage"] == "TaskTransactionManager_only"
    assert details["stale_running_30m"] == 0
    assert "persisted_task_failures=2" in details["_warn"]
    assert details["fail_log_10min"] == "(none)"
    assert details["fail_log_10min_count"] == 0
    assert any("task_execution_history" in sql for sql in seen_sql)
    assert any("scheduler_metrics" in sql for sql in seen_sql)


def test_scheduler_journal_filter_does_not_treat_failed_false_as_failure(monkeypatch):
    """INFO 字段 fetch_failed=False 不得被宽泛 fail 子串筛选成任务故障。"""
    from scripts import puzan_loop_monitor as monitor

    seen_commands = []

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        if "GROUP BY status" in sql:
            return "success|8", ""
        if "status='running'" in sql:
            return "0", ""
        if "status='failed'" in sql:
            return "", ""
        if "last_status IN" in sql or "FROM scheduler_metrics" in sql:
            return "", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "heartbeat|success|2026-08-31", ""
        raise AssertionError(sql)

    def _ssh_run(_client, command, timeout=10):
        seen_commands.append(command)
        if "WatchdogUSec" in command:
            return "0", "", 0
        return "", "", 0

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)
    monkeypatch.setattr(monitor, "ssh_run", _ssh_run)

    status, details = monitor.l5_scheduler_check(object())

    journal_command = next(
        command
        for command in seen_commands
        if "journalctl" in command and "fail(ed|ure)?" in command
    )
    assert status == "OK"
    assert details["fail_log_10min_count"] == 0
    assert "fail|exception|error" not in journal_command
    assert "[^[:alnum:]_=]" in journal_command


def test_scheduler_layer_exposes_recovered_jobs_cumulative_failures(monkeypatch):
    """持久 ERROR 后恢复 SUCCESS 时，当前状态与历史原因必须明确分栏。"""
    from scripts import puzan_loop_monitor as monitor

    seen_sql = []

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        seen_sql.append(sql)
        if "GROUP BY status" in sql:
            return "success|8", ""
        if "status='running'" in sql:
            return "0", ""
        if "status='failed'" in sql:
            return "", ""
        if "last_status IN" in sql:
            return "", ""
        if "AS error_scope" in sql and "last_status_at" in sql:
            return (
                "heartbeat|success|18|0|1786200000|1786200060|historical|historical timeout",
                "",
            )
        if "AS error_scope" in sql:
            return "heartbeat|success|18|0|1786200000|historical|historical timeout", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "heartbeat|success|2026-08-31", ""
        raise AssertionError(sql)

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)
    monkeypatch.setattr(
        monitor,
        "ssh_run",
        lambda _client, _command, timeout=10: ("0", "", 0)
        if "WatchdogUSec" in _command
        else ("", "", 0),
    )

    status, details = monitor.l5_scheduler_check(object())

    assert status == "OK"
    assert details["scheduler_metrics_errors"] == ""
    assert details["scheduler_metrics_cumulative_failures"].startswith("heartbeat|success|18|")
    assert "|historical|historical timeout" in details["scheduler_metrics_cumulative_failures"]
    assert details["scheduler_metrics_failure_history"] == [{
        "job_id": "heartbeat",
        "current_status": "success",
        "cumulative_fail_count": 18,
        "cumulative_miss_count": 0,
        "last_run": 1786200000,
        "last_status_at": 1786200060,
        "error_scope": "historical",
        "last_failure_error": "historical timeout",
    }]
    current_error_sql = next(sql for sql in seen_sql if "last_status IN" in sql)
    assert "-1 hour" in current_error_sql
    assert "last_status_at" in current_error_sql
    assert "last_run" not in current_error_sql
    cumulative_sql = next(
        sql for sql in seen_sql
        if "AS error_scope" in sql and "last_status_at" not in sql
    )
    assert "AS error_scope" in cumulative_sql
    assert "COALESCE(last_run,0)" in cumulative_sql
    assert "COALESCE(fail_count,0)" in cumulative_sql
    assert "COALESCE(miss_count,0)" in cumulative_sql
    assert "char(13)" in cumulative_sql
    assert "char(10)" in cumulative_sql
    assert cumulative_sql.index("last_status='error'") < cumulative_sql.index("COALESCE(last_error,'')=''")


def test_scheduler_layer_warns_for_first_missed_event_by_status_time(monkeypatch):
    from scripts import puzan_loop_monitor as monitor

    seen_sql = []

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        seen_sql.append(sql)
        if "GROUP BY status" in sql:
            return "", ""
        if "status='running'" in sql:
            return "0", ""
        if "status='failed'" in sql:
            return "", ""
        if "last_status IN" in sql:
            return "never_ran|missed|0|1|1786200100|", ""
        if "AS error_scope" in sql and "last_status_at" in sql:
            return "never_ran|missed|0|1|0|1786200100|none|", ""
        if "AS error_scope" in sql:
            return "never_ran|missed|0|1|0|none|", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "", ""
        raise AssertionError(sql)

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)
    monkeypatch.setattr(
        monitor,
        "ssh_run",
        lambda _client, command, timeout=10: ("0", "", 0)
        if "WatchdogUSec" in command else ("", "", 0),
    )

    status, details = monitor.l5_scheduler_check(object())

    assert status == "WARN"
    assert details["scheduler_metrics_errors"].startswith("never_ran|missed|0|1|")
    assert details["scheduler_metrics_failure_history"] == [{
        "job_id": "never_ran",
        "current_status": "missed",
        "cumulative_fail_count": 0,
        "cumulative_miss_count": 1,
        "last_run": 0,
        "last_status_at": 1786200100,
        "error_scope": "none",
        "last_failure_error": "",
    }]
    current_sql = next(sql for sql in seen_sql if "last_status IN" in sql)
    assert "COALESCE(last_status_at,0)" in current_sql
    assert "COALESCE(last_run,0)" not in current_sql


def test_scheduler_error_scope_keeps_current_error_when_text_is_empty():
    from scripts import puzan_loop_monitor as monitor

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metrics(last_status TEXT, last_error TEXT)")
    conn.executemany(
        "INSERT INTO metrics VALUES (?, ?)",
        [("error", ""), ("success", "old failure"), ("success", "")],
    )

    scopes = [
        row[0]
        for row in conn.execute(
            f"SELECT {monitor.SCHEDULER_ERROR_SCOPE_SQL} FROM metrics ORDER BY rowid"
        )
    ]

    assert scopes == ["current", "historical", "none"]


def test_scheduler_failure_history_normalizes_persisted_error_then_success():
    from scripts import puzan_loop_monitor as monitor

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE scheduler_metrics("
        "job_id TEXT PRIMARY KEY, last_status TEXT, success_count INTEGER, "
        "fail_count INTEGER, miss_count INTEGER, last_run INTEGER, "
        "last_status_at INTEGER, last_error TEXT)"
    )
    conn.execute(
        "INSERT INTO scheduler_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "heartbeat", "error", 0, 1, 0,
            1786199900, 1786199900, "database locked",
        ),
    )
    conn.execute(
        "UPDATE scheduler_metrics SET last_status='success', success_count=1, "
        "last_run=1786200000, last_status_at=1786200060 WHERE job_id='heartbeat'"
    )
    row = conn.execute(
        "SELECT job_id, last_status, COALESCE(fail_count,0), COALESCE(miss_count,0), "
        "COALESCE(last_run,0), COALESCE(last_status_at,0), "
        f"{monitor.SCHEDULER_ERROR_SCOPE_SQL}, COALESCE(last_error,'') "
        "FROM scheduler_metrics"
    ).fetchone()

    history = monitor._parse_scheduler_failure_history(
        "|".join(str(value) for value in row)
    )

    assert history == [{
        "job_id": "heartbeat",
        "current_status": "success",
        "cumulative_fail_count": 1,
        "cumulative_miss_count": 0,
        "last_run": 1786200000,
        "last_status_at": 1786200060,
        "error_scope": "historical",
        "last_failure_error": "database locked",
    }]


def test_scheduler_failure_history_preserves_pipe_in_historical_error():
    from scripts import puzan_loop_monitor as monitor

    history = monitor._parse_scheduler_failure_history(
        "vote_kick|success|2|0|1786200001|1786200061|historical|database locked | retry exhausted"
    )

    assert history == [{
        "job_id": "vote_kick",
        "current_status": "success",
        "cumulative_fail_count": 2,
        "cumulative_miss_count": 0,
        "last_run": 1786200001,
        "last_status_at": 1786200061,
        "error_scope": "historical",
        "last_failure_error": "database locked | retry exhausted",
    }]


def test_scheduler_failure_history_coalesces_null_counts():
    from scripts import puzan_loop_monitor as monitor

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE scheduler_metrics("
        "job_id TEXT, last_status TEXT, fail_count INTEGER, miss_count INTEGER, "
        "last_run INTEGER, last_status_at INTEGER, last_error TEXT)"
    )
    conn.execute(
        "INSERT INTO scheduler_metrics VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("null_counts", "missed", None, 1, None, 1786200200, None),
    )
    row = conn.execute(
        "SELECT job_id, last_status, COALESCE(fail_count,0), COALESCE(miss_count,0), "
        "COALESCE(last_run,0), COALESCE(last_status_at,0), "
        f"{monitor.SCHEDULER_ERROR_SCOPE_SQL}, COALESCE(last_error,'') "
        "FROM scheduler_metrics WHERE COALESCE(fail_count,0) > 0 "
        "OR COALESCE(miss_count,0) > 0"
    ).fetchone()

    history = monitor._parse_scheduler_failure_history(
        "|".join(str(value) for value in row)
    )

    assert history[0]["cumulative_fail_count"] == 0
    assert history[0]["cumulative_miss_count"] == 1
    assert history[0]["last_run"] == 0
    assert history[0]["last_status_at"] == 1786200200


def test_scheduler_layer_fails_closed_when_failure_history_is_malformed(monkeypatch):
    from scripts import puzan_loop_monitor as monitor

    def _sqlite_query(_client, _db_path, sql, timeout=20):
        if "GROUP BY status" in sql:
            return "success|1", ""
        if "status='running'" in sql:
            return "0", ""
        if "status='failed'" in sql or "last_status IN" in sql:
            return "", ""
        if "AS error_scope" in sql and "last_status_at" in sql:
            return (
                "heartbeat|success|not-a-count|0|1786200000|1786200060|historical|old failure",
                "",
            )
        if "AS error_scope" in sql:
            return "heartbeat|success|1|0|1786200000|historical|old failure", ""
        if "ORDER BY id DESC LIMIT 10" in sql:
            return "heartbeat|success|2026-08-31", ""
        raise AssertionError(sql)

    monkeypatch.setattr(monitor, "sqlite_query", _sqlite_query)
    monkeypatch.setattr(monitor, "ssh_run", lambda *_args, **_kwargs: ("", "", 0))

    status, details = monitor.l5_scheduler_check(object())

    assert status == "ERROR"
    assert details["scheduler_metrics_failure_history"] == []
    assert "scheduler_metrics_failure_history_parse_failed" in details["_crit"]


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
