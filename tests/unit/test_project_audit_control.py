import json
import os
import subprocess
import sys
from pathlib import Path


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
        {"cpu_usage": "10%", "top_head": "process args with secrets", "_warn": ""},
    )

    assert filtered == {"cpu_usage": "10%", "_warn": ""}


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
