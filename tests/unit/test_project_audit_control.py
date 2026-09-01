import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sample_config():
    return {
        "schema_version": "mory.project-audit-config/v1",
        "production_truth": {"business_receipts": []},
        "drift": {"watched_workspace_paths": [], "remote_hash_mappings": []},
        "monthly": {"lookback_days": 30, "minimum_occurrences": 2},
    }


def test_receipt_status_and_exit_codes_do_not_fake_green():
    from scripts import project_audit_control as control

    assert control._aggregate([{"status": "pass"}, {"status": "evidence_gap"}]) == "evidence_gap"
    assert control._aggregate([{"status": "pass"}, {"status": "failed"}]) == "failed"
    assert control.EXIT_CODES == {"pass": 0, "evidence_gap": 2, "failed": 3}


def test_config_key_drift_fails_when_confirmed_removed_keys_reappear():
    from scripts import project_audit_control as control

    status, summary, evidence = control._classify_config_key_drift(
        ["MODEL_POOLS"],
        ["MODEL_POOLS", "API_KEYS", "AD_KEYWORDS"],
    )

    assert status == "failed"
    assert "confirmed removed" in summary
    assert evidence["confirmed_removed_keys_present"] == ["API_KEYS"]
    assert "AD_KEYWORDS" in evidence["extra_keys"]


def test_config_key_drift_fails_even_if_removed_key_is_declared_locally():
    from scripts import project_audit_control as control

    status, _summary, evidence = control._classify_config_key_drift(
        ["MODEL_POOLS", "API_KEYS"],
        ["MODEL_POOLS", "API_KEYS"],
    )

    assert status == "failed"
    assert evidence["extra_keys"] == []
    assert evidence["confirmed_removed_keys_present"] == ["API_KEYS"]


def test_config_key_drift_allows_visible_runtime_compatibility_keys():
    from scripts import project_audit_control as control

    status, _summary, evidence = control._classify_config_key_drift(
        ["MODEL_POOLS"],
        ["MODEL_POOLS", "AD_KEYWORDS"],
    )

    assert status == "pass"
    assert evidence["confirmed_removed_keys_present"] == []


def test_l1_missing_evidence_maps_to_gap_without_hiding_real_resource_alerts():
    from scripts import project_audit_control as control

    evidence_only = {
        "l1_evidence_gaps": ["free(mem_available_missing)"],
        "l1_evidence_gap_only": True,
    }
    real_alert_too = {
        "l1_evidence_gaps": ["free(mem_available_missing)"],
        "l1_evidence_gap_only": False,
        "_warn": "disk_usage_high(95%); l1_evidence_gap=free(mem_available_missing); ",
    }

    assert control._monitor_receipt_status("l1_resources", "WARN", evidence_only) == "evidence_gap"
    assert control._monitor_receipt_status("l1_resources", "WARN", real_alert_too) == "failed"
    assert control._monitor_receipt_status("l1_resources", "CRITICAL", evidence_only) == "failed"


def test_production_audit_preserves_l1_evidence_gap_semantics(monkeypatch):
    from core import deploy_utils
    from scripts import project_audit_control as control
    from scripts import puzan_loop_monitor as monitor

    monkeypatch.setattr(control, "_is_deployed_runtime", lambda: False)
    monkeypatch.setattr(deploy_utils, "_deployment_verification_checks", lambda _path: [])
    monkeypatch.setattr(
        monitor,
        "l1_vps_check",
        lambda _client: (
            "WARN",
            {
                "l1_evidence_gaps": ["free(mem_available_missing)"],
                "l1_evidence_gap_only": True,
                "_warn": "l1_evidence_gap=free(mem_available_missing); ",
            },
        ),
    )
    monkeypatch.setattr(monitor, "l4_biz_check", lambda _client: ("OK", {}))
    monkeypatch.setattr(monitor, "l5_scheduler_check", lambda _client: ("OK", {}))
    monkeypatch.setattr(monitor, "l6_watchdog_check", lambda _client: ("OK", {}))

    checks = control.audit_production_truth(
        _sample_config(),
        client_factory=lambda: SimpleNamespace(close=lambda: None),
    )
    l1 = next(item for item in checks if item["id"] == "production.l1_resources")

    assert l1["status"] == "evidence_gap"
    assert l1["evidence"]["l1_evidence_gap_only"] is True


def test_health_liveness_cannot_substitute_for_release_identity():
    from scripts import project_audit_control as control

    health_status, _ = control._remote_check_status("Health API", 0, "200", "")
    version_status, summary = control._remote_check_status("运行版本", 0, "v0.0.0", "")

    assert health_status == "pass"
    assert version_status == "failed"
    assert "release identity" in summary


def test_journal_collection_unavailable_is_evidence_gap():
    from scripts import project_audit_control as control

    status, _ = control._remote_check_status("Bot日志", 2, "STARTUP_TIMESTAMP_UNAVAILABLE", "")
    assert status == "evidence_gap"


def test_business_probe_is_read_only_and_checks_age():
    from scripts import project_audit_control as control

    command = control._business_receipt_command(
        "/home/ubuntu/mory_assistant",
        [{"task_key": "mystic_morning", "max_age_hours": 36}],
    )

    assert "mode=ro" in command
    assert "status='success'" in command
    assert "BUSINESS_RECEIPT_MISSING" in command
    assert "INSERT" not in command.upper()
    assert "UPDATE" not in command.upper()
    assert "DELETE" not in command.upper()


def test_monthly_audit_is_candidate_only(monkeypatch):
    from scripts import project_audit_control as control

    history = "\n".join(
        [
            "2026-08-01|aaaaaaaaaaaa|fix production deploy health",
            "2026-08-02|bbbbbbbbbbbb|audit VPS deployment truth",
        ]
    )
    monkeypatch.setattr(control, "_run_local_command", lambda *_args, **_kwargs: (0, history, ""))

    checks = control.audit_monthly(_sample_config())
    candidates = checks[0]["evidence"]["candidates"]

    assert checks[0]["status"] == "pass"
    assert candidates[0]["classification"] == "Automation"
    assert candidates[0]["action"] == "candidate_only_no_install"


def test_config_schema_fails_closed(tmp_path):
    from scripts import project_audit_control as control

    path = tmp_path / "audit.json"
    path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")

    try:
        control.load_config(path)
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("invalid schema must fail")


def test_receipt_path_maintains_profile_latest(tmp_path):
    from scripts import project_audit_control as control

    receipt = {
        "schema_version": "mory.project-audit-receipt/v1",
        "profile": "monthly",
        "status": "pass",
        "exit_code": 0,
    }
    output = tmp_path / "monthly-test.json"
    control._write_receipt(receipt, output)

    assert output.is_file()
    assert json.loads((tmp_path / "latest-monthly.json").read_text(encoding="utf-8"))["status"] == "pass"
    assert os.name == "nt" or output.stat().st_mode & 0o777 & 0o077 == 0


def test_monitor_receipt_filters_raw_process_and_log_tails():
    from scripts import project_audit_control as control

    filtered = control._filter_monitor_evidence(
        "l1_resources",
        {
            "cpu_usage": "10%",
            "l1_evidence_gaps": ["free(mem_available_missing)"],
            "l1_evidence_gap_only": True,
            "oom_kills_1h": 7,
            "oom_cgroup_kills_1h": 7,
            "oom_global_kills_1h": 0,
            "oom_source_mory_1h": 0,
            "oom_source_external_1h": 7,
            "oom_source_unknown_1h": 0,
            "oom_victim_mory_1h": 0,
            "oom_source_labels_1h": "docker:abcdef123456=7",
            "oom_victim_processes_1h": "chromium=7",
            "oom_external_containers_1h": "steel-browser=7",
            "oom_attribution_complete": True,
            "oom_journal_ok": True,
            "oom_control_groups_available": True,
            "oom_evidence_truncated": False,
            "top_head": "process args with secrets",
            "_warn": "",
        },
    )

    assert filtered == {
        "cpu_usage": "10%",
        "l1_evidence_gaps": ["free(mem_available_missing)"],
        "l1_evidence_gap_only": True,
        "oom_kills_1h": 7,
        "oom_cgroup_kills_1h": 7,
        "oom_global_kills_1h": 0,
        "oom_source_mory_1h": 0,
        "oom_source_external_1h": 7,
        "oom_source_unknown_1h": 0,
        "oom_victim_mory_1h": 0,
        "oom_source_labels_1h": "docker:abcdef123456=7",
        "oom_victim_processes_1h": "chromium=7",
        "oom_external_containers_1h": "steel-browser=7",
        "oom_attribution_complete": True,
        "oom_journal_ok": True,
        "oom_control_groups_available": True,
        "oom_evidence_truncated": False,
        "_warn": "",
    }


def test_timer_manager_defaults_to_plan_and_requires_apply(capsys):
    from scripts import manage_project_audit_timers as manager

    assert manager.main(["--action", "plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "planned_not_applied"
    assert plan["apply"] is False

    assert manager.main(["--action", "install"]) == 2
    guarded = json.loads(capsys.readouterr().out)
    assert guarded["status"] == "planned_not_applied"


def test_timer_units_render_read_only_service_contract():
    from scripts import manage_project_audit_timers as manager

    rendered = manager.render_units(
        project_root=Path("/srv/mory_assistant"),
        python_path=Path("/usr/bin/python3"),
        audit_user="mory-audit",
    )
    service = rendered[manager.SERVICE_NAME]

    assert "User=mory-audit" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "UMask=0077" in service
    assert "EnvironmentFile" not in service
    assert "project_audit_control.py --profile %i" in service
    assert "@PROJECT_ROOT@" not in service
    assert set(rendered) == set(manager.UNIT_NAMES)


def test_control_cli_direct_script_import_surface():
    result = subprocess.run(
        [sys.executable, "scripts/project_audit_control.py", "--profile", "monthly", "--no-write"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "pass"


def test_deployed_monthly_falls_back_to_changelog(monkeypatch, tmp_path):
    from scripts import project_audit_control as control

    (tmp_path / "CHANGELOG.md").write_text(
        "| 2026-08-01 | 修复 | production deploy health | files |\n"
        "| 2026-08-02 | 治理 | VPS deployment truth audit | files |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(control, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(control, "_run_local_command", lambda *_args, **_kwargs: (128, "", "not a git repository"))

    checks = control.audit_monthly(_sample_config())

    assert checks[0]["status"] == "pass"
    assert "CHANGELOG" in checks[0]["coverage"]


def test_deployed_runtime_uses_local_read_only_client(monkeypatch):
    from scripts import project_audit_control as control

    monkeypatch.setattr(control, "_is_deployed_runtime", lambda: True)
    assert isinstance(control._default_client_factory(), control._LocalReadOnlyClient)


def test_local_read_only_client_accepts_get_pty(monkeypatch):
    from types import SimpleNamespace

    from scripts import project_audit_control as control

    calls = []
    monkeypatch.setattr(
        control.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs))
        or SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
    )

    _stdin, stdout, stderr = control._LocalReadOnlyClient().exec_command(
        "printf ok",
        timeout=7,
        get_pty=True,
    )

    assert stdout.read() == b"ok\n"
    assert stderr.channel.recv_exit_status() == 0
    assert calls[0][1]["timeout"] == 7


def test_scheduler_cumulative_failures_are_kept_in_filtered_evidence():
    from scripts import project_audit_control as control

    details = {
        "scheduler_metrics_errors": "",
        "scheduler_metrics_cumulative_failures": "heartbeat|success|18|0",
        "fail_log_10min_count": 0,
        "unrelated": "drop me",
    }

    assert control._filter_monitor_evidence("l5_scheduler", details) == {
        "scheduler_metrics_errors": "",
        "scheduler_metrics_cumulative_failures": "heartbeat|success|18|0",
        "fail_log_10min_count": 0,
    }


def test_conflicting_legacy_health_and_auto_rollback_are_retired():
    import deploy_vps

    assert not (PROJECT_ROOT / "scripts" / "health_check.py").exists()
    assert not (PROJECT_ROOT / "scripts" / "auto_rollback.py").exists()
    assert not (PROJECT_ROOT / "scripts" / "rollback_config.json").exists()
    assert {
        "scripts/health_check.py",
        "scripts/auto_rollback.py",
        "scripts/rollback_config.json",
    }.issubset(set(deploy_vps.DEAD_REMOTE_FILES))


def test_deploy_manifest_contains_project_audit_static_assets():
    import deploy_vps

    assert set(deploy_vps.PROJECT_AUDIT_FILES).issubset(set(deploy_vps.UPLOAD_FILES))


def test_timer_report_dir_is_owned_by_audit_user(monkeypatch, tmp_path):
    from scripts import manage_project_audit_timers as manager

    ownership = []
    modes = []
    monkeypatch.setattr(manager, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(manager, "_resolve_audit_user", lambda _user: (123, 456))
    monkeypatch.setattr(manager.os, "chown", lambda path, uid, gid: ownership.append((Path(path), uid, gid)), raising=False)
    monkeypatch.setattr(manager.os, "chmod", lambda path, mode: modes.append((Path(path), mode)))

    report_dir = tmp_path / "runtime" / "audit-reports" / "project-automation"
    manager._prepare_report_dir(report_dir, "mory-audit")

    assert report_dir.is_dir()
    assert ownership == [(report_dir, 123, 456)]
    assert modes == [(report_dir, 0o700)]
