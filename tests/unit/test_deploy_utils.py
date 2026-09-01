# -*- coding: utf-8 -*-
"""[Codex] 部署配置合并必须保护敏感值，但业务配置应以本地为准。"""

import os
import sys
import json
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeStream:
    def __init__(self, text, exit_code=0):
        self._text = text
        self.channel = SimpleNamespace(recv_exit_status=lambda: exit_code)
        self.closed = False

    def read(self):
        return self._text.encode("utf-8")

    def close(self):
        self.closed = True


def test_dashboard_teardown_filter_is_exact_and_preserves_real_errors():
    from core.deploy_utils import filter_dashboard_teardown_noise

    known_noise = """Aug 12 host python[1]: Exception ignored in: <function _removeHandlerRef at 0x1>\nAug 12 host python[1]: Traceback (most recent call last):\nAug 12 host python[1]:   File \"/usr/lib/python3.10/logging/__init__.py\", line 845, in _removeHandlerRef\nAug 12 host python[1]:   File \"/usr/lib/python3.10/logging/__init__.py\", line 226, in _acquireLock\nAug 12 host python[1]:   File \"/home/ubuntu/.local/lib/python3.10/site-packages/gevent/thread.py\", line 54, in get_ident\nAug 12 host python[1]: RuntimeError: greenlet is being finalized\n"""
    real_failure = "Aug 12 host python[2]: Worker failed to boot\n"
    unrelated = """Aug 12 host python[3]: Exception ignored in: <function close at 0x2>\nAug 12 host python[3]: Traceback (most recent call last):\nAug 12 host python[3]: RuntimeError: database close failed\n"""

    filtered = filter_dashboard_teardown_noise(known_noise + real_failure + unrelated)

    assert "greenlet is being finalized" not in filtered
    assert "Worker failed to boot" in filtered
    assert "database close failed" in filtered


def test_scheduler_registry_receipt_tracks_current_state_without_hiding_failures():
    from core.deploy_utils import scheduler_registry_receipt_from_logs

    import json

    def record(logger, function, level, message):
        return json.dumps(
            {
                "logger": logger,
                "function": function,
                "level": level,
                "message": message,
            },
            ensure_ascii=False,
        )

    begin_1 = record(
        "tasks.task_scheduler",
        "begin_scheduler_reconciliation",
        "INFO",
        "SCHEDULER_RECONCILE_BEGIN mode=startup generation=1",
    )
    complete_1 = record(
        "tasks.task_scheduler",
        "complete_scheduler_reconciliation",
        "INFO",
        "SCHEDULER_RECONCILE_OK mode=startup generation=1 managed_jobs=41 "
        "scene_triggers=reconciled dynamic_jobs=not_observed",
    )

    code, receipt = scheduler_registry_receipt_from_logs(begin_1 + "\n" + complete_1)
    assert code == 0
    assert receipt.startswith("SCHEDULER_REGISTRY_OK")
    assert "managed_jobs=41" in receipt
    assert "dynamic_jobs:not_observed" in receipt
    assert "direct_registry:false" in receipt

    assert scheduler_registry_receipt_from_logs("普通启动日志") == (
        2,
        "SCHEDULER_RECONCILIATION_RECEIPT_MISSING",
    )
    assert scheduler_registry_receipt_from_logs(begin_1) == (
        1,
        "SCHEDULER_RECONCILIATION_INCOMPLETE mode=startup generation=1",
    )

    failure_cases = {
        "task_registration_failed": record(
            "tasks.task_scheduler", "_register_tasks", "ERROR", "任意注册错误"
        ),
        "scene_trigger_refresh_failed": record(
            "modules.triggers.base", "refresh_trigger_jobs", "ERROR", "任意触发器错误"
        ),
        "scheduler_rollback_failed": record(
            "bot_initializer", "_apply_reloaded_config", "CRITICAL", "任意回滚错误"
        ),
    }
    for reason, failure_record in failure_cases.items():
        code, receipt = scheduler_registry_receipt_from_logs(
            begin_1 + "\n" + complete_1 + "\n" + failure_record
        )
        assert code == 1
        assert reason in receipt

    begin_2 = record(
        "tasks.task_scheduler",
        "begin_scheduler_reconciliation",
        "INFO",
        "SCHEDULER_RECONCILE_BEGIN mode=reload generation=2",
    )
    complete_2 = record(
        "tasks.task_scheduler",
        "complete_scheduler_reconciliation",
        "INFO",
        "SCHEDULER_RECONCILE_OK mode=reload generation=2 managed_jobs=40 "
        "scene_triggers=reconciled dynamic_jobs=not_observed",
    )

    # 新一轮已经开始却未落最终成功回执时必须失败，不能沿用旧绿灯。
    code, receipt = scheduler_registry_receipt_from_logs(
        begin_1 + "\n" + complete_1 + "\n" + begin_2
    )
    assert code == 1
    assert receipt == "SCHEDULER_RECONCILIATION_INCOMPLETE mode=reload generation=2"

    # 失败后完整重建成功属于已恢复历史；最后成功回执之后无失败即可通过。
    code, receipt = scheduler_registry_receipt_from_logs(
        begin_1
        + "\n"
        + complete_1
        + "\n"
        + failure_cases["scene_trigger_refresh_failed"]
        + "\n"
        + begin_2
        + "\n"
        + complete_2
    )
    assert code == 0
    assert "managed_jobs=40" in receipt

    # 用户消息、错误来源、错误级别和非 JSON 行都不能伪造成功或失败。
    forged_messages = [
        record(
            "core.message_dispatcher",
            "dispatch_message",
            "INFO",
            "SCHEDULER_RECONCILE_OK mode=reload generation=999 managed_jobs=999 "
            "scene_triggers=reconciled dynamic_jobs=not_observed",
        ),
        record(
            "core.message_dispatcher",
            "dispatch_message",
            "INFO",
            "调度回滚失败",
        ),
        record(
            "tasks.task_scheduler",
            "wrong_function",
            "INFO",
            "SCHEDULER_RECONCILE_BEGIN mode=reload generation=999",
        ),
        "not-json SCHEDULER_RECONCILE_BEGIN mode=reload generation=999",
    ]
    code, receipt = scheduler_registry_receipt_from_logs(
        begin_1 + "\n" + complete_1 + "\n" + "\n".join(forged_messages)
    )
    assert code == 0
    assert "managed_jobs=41" in receipt


def test_scheduler_reconciliation_logs_form_an_authenticated_receipt(caplog):
    """生产 JsonFormatter 的真实 logger/function/level 必须能被分类器认证。"""
    import logging

    from core.deploy_utils import scheduler_registry_receipt_from_logs
    from core.logging_util import JsonFormatter
    from tasks.task_scheduler import (
        begin_scheduler_reconciliation,
        complete_scheduler_reconciliation,
    )

    scheduler = type("Scheduler", (), {"_registered_job_ids": {"a", "b"}})()
    caplog.set_level(logging.INFO, logger="tasks.task_scheduler")

    generation = begin_scheduler_reconciliation(scheduler, "startup")
    complete_scheduler_reconciliation(scheduler, "startup", generation)

    formatter = JsonFormatter()
    log_text = "\n".join(
        formatter.format(record)
        for record in caplog.records
        if record.name == "tasks.task_scheduler"
    )
    code, receipt = scheduler_registry_receipt_from_logs(log_text)
    assert code == 0
    assert "managed_jobs=2" in receipt


def test_dashboard_runtime_probe_uses_exact_lock_versions():
    """探针命令必须使用 requirements.lock 的精确版本（独立解析 lock，不硬编码）。"""
    import re
    from pathlib import Path

    import deploy_vps

    versions = deploy_vps._locked_dashboard_versions()
    command = deploy_vps._dashboard_runtime_probe_command()

    lock_text = (Path(deploy_vps.ROOT) / "requirements.lock").read_text(encoding="utf-8")
    expected = {}
    for pkg in ("gunicorn", "gevent"):
        match = re.search(rf"^{pkg}==([0-9][\w.]*)", lock_text, re.MULTILINE)
        assert match, f"{pkg} 必须在 requirements.lock 中有精确钉版"
        expected[pkg] = match.group(1)

    assert versions == expected
    assert "DASHBOARD_RUNTIME_LOCK_OK" in command
    for pkg, ver in expected.items():
        assert pkg in command
        assert ver in command


def test_safe_merge_config_keeps_protected_fields_from_vps():
    from core.deploy_utils import safe_merge_config

    local_cfg = {
        "TOKEN": "local-token",
        "API_KEY": "local-key",
        "RELAY_MODE_ENABLED": True,
    }
    vps_cfg = {
        "TOKEN": "remote-token",
        "API_KEY": "remote-key",
        "RELAY_MODE_ENABLED": False,
    }

    merged = safe_merge_config(local_cfg, vps_cfg)

    assert merged["TOKEN"] == "remote-token"
    assert merged["API_KEY"] == "remote-key"
    assert merged["RELAY_MODE_ENABLED"] is True


def test_safe_merge_config_updates_non_protected_fields_from_local():
    from core.deploy_utils import safe_merge_config

    local_cfg = {
        "RELAY_MODE_ENABLED": True,
        "BLIND_BOX_COST": 35,
        "MYSTIC_BROADCAST_CONFIG": {"enabled": True, "morning_time": "09:05"},
    }
    vps_cfg = {
        "RELAY_MODE_ENABLED": False,
        "BLIND_BOX_COST": 30,
        "MYSTIC_BROADCAST_CONFIG": {"enabled": False, "morning_time": "10:00"},
    }

    merged = safe_merge_config(local_cfg, vps_cfg)

    assert merged["RELAY_MODE_ENABLED"] is True
    assert merged["BLIND_BOX_COST"] == 35
    assert merged["MYSTIC_BROADCAST_CONFIG"]["morning_time"] == "09:05"


def test_safe_merge_config_removes_confirmed_dead_config_fields():
    from core.deploy_utils import safe_merge_config

    merged = safe_merge_config({}, {"STATS_REPORT_CONFIG": {"enabled": True}})

    assert "STATS_REPORT_CONFIG" not in merged


def test_safe_upload_config_uses_private_backup_and_atomic_replace():
    """部署配置必须先私有备份，再通过同文件系统原子替换落盘。"""
    from core.deploy_utils import safe_upload_config

    class MemorySFTP:
        def __init__(self):
            self.files = {
                "/remote/config.json": json.dumps({"TOKEN": "remote", "FEATURE": False}),
            }
            self.modes = {"/remote/config.json": 0o600}
            self.dirs = {"/remote"}
            self.put_paths = []
            self.rename_calls = []

        def get(self, remote, local):
            Path(local).write_text(self.files[remote], encoding="utf-8")

        def put(self, local, remote):
            self.files[remote] = Path(local).read_text(encoding="utf-8")
            self.put_paths.append(remote)

        def stat(self, path):
            if path in self.files:
                return SimpleNamespace(st_mode=self.modes.get(path, 0o644))
            if path in self.dirs:
                return SimpleNamespace(st_mode=self.modes.get(path, 0o700))
            raise FileNotFoundError(path)

        def mkdir(self, path):
            self.dirs.add(path)

        def chmod(self, path, mode):
            self.modes[path] = mode

        def posix_rename(self, source, target):
            self.rename_calls.append((source, target))
            self.files[target] = self.files.pop(source)
            self.modes[target] = self.modes.pop(source)

        def remove(self, path):
            self.files.pop(path, None)

    sftp = MemorySFTP()
    merged = safe_upload_config(sftp, {"TOKEN": "local", "FEATURE": True}, "/remote")

    assert merged["TOKEN"] == "remote"
    assert merged["FEATURE"] is True
    assert "/remote/config.json" not in sftp.put_paths
    assert len(sftp.rename_calls) == 1
    source, target = sftp.rename_calls[0]
    assert source.startswith("/remote/.deploy-staging/config.json.")
    assert target == "/remote/config.json"
    assert sftp.modes["/remote/config.json"] == 0o600
    backup_paths = [path for path in sftp.files if path.startswith("/remote/backups/config_")]
    assert len(backup_paths) == 1
    assert sftp.modes[backup_paths[0]] == 0o600


def test_runtime_sync_cannot_restore_legacy_auto_greeting_switches():
    from core.deploy_utils import sync_runtime_fields_from_vps

    local = {"AUTO_GREETING": False, "AUTO_GOODNIGHT": False}
    remote = {"AUTO_GREETING": True, "AUTO_GOODNIGHT": True}

    merged, synced = sync_runtime_fields_from_vps(local, remote)

    assert merged == {"AUTO_GREETING": False, "AUTO_GOODNIGHT": False}
    assert "AUTO_GREETING" not in synced
    assert "AUTO_GOODNIGHT" not in synced


def test_runtime_sync_cannot_restore_old_model_state():
    from core.deploy_utils import sync_runtime_fields_from_vps

    local = {
        "CURRENT_MODEL_INDEX": 0,
        "BLACKLISTED_MODELS": [],
        "BLACKLISTED_MODELS_TS": {},
    }
    remote = {
        "CURRENT_MODEL_INDEX": 3,
        "BLACKLISTED_MODELS": ["removed-model"],
        "BLACKLISTED_MODELS_TS": {"removed-model": 1},
    }

    merged, synced = sync_runtime_fields_from_vps(local, remote)

    assert merged == local
    assert "CURRENT_MODEL_INDEX" not in synced
    assert "BLACKLISTED_MODELS" not in synced
    assert "BLACKLISTED_MODELS_TS" not in synced


def test_deploy_manifest_excludes_sync_conflicts_and_includes_truth_docs():
    import deploy_vps

    assert all(".sync-conflict-" not in path for path in deploy_vps.UPLOAD_FILES)
    # 公开文档随部署上传（VERSION.md 是版本说明，非内部规则）
    assert {
        "README.md",
        "CHANGELOG.md",
        "VERSION.md",
    }.issubset(set(deploy_vps.UPLOAD_FILES))
    # 内部文档不上传 VPS，避免暴露安全策略、踩坑病历和模块清单
    assert {
        "AGENTS.md",
        "AI_DEBUG_HISTORY.md",
        "project_snapshot.md",
    }.isdisjoint(set(deploy_vps.UPLOAD_FILES))
    assert {
        "migrations/versions/0002_reply_style_samples.py",
        "migrations/versions/0003_business_conversation_context.py",
        "tasks/maintenance/conversation_context_cleanup_task.py",
    }.issubset(set(deploy_vps.UPLOAD_FILES))


def test_skip_path_fragments_hits_quarantine_execution_tmp():
    """[v5.38.17 Graph Mode] 新增路径片段黑名单 _quarantine_ / EXECUTION_ / _tmp_ 必须命中，
    同时确保原 runtime/cache/logs 等仍在黑名单里。"""
    import deploy_vps

    # 构造命中场景的相对路径（与 _collect_upload_files 中 as_posix() 格式一致）
    hit_cases = (
        "_quarantine_/orphan_review.json",
        "docs/archive/EXECUTION_LOG.md",
        "runtime/_tmp_/cache_snapshot.db",
    )
    for rel in hit_cases:
        assert any(frag in rel for frag in deploy_vps.SKIP_PATH_FRAGMENTS), (
            f"SKIP_PATH_FRAGMENTS 应命中但未命中: {rel}"
        )

    # 确认原黑名单继续生效（回归 guard）
    legacy_hits = (
        "runtime/cache/some_image.png",
        "runtime/logs/bot.log",
        "__pycache__/core.cpython-312.pyc",
        ".git/config",
    )
    for rel in legacy_hits:
        assert any(frag in rel for frag in deploy_vps.SKIP_PATH_FRAGMENTS), (
            f"Legacy SKIP_PATH_FRAGMENTS 应命中但未命中: {rel}"
        )

    # 不应该命中的正常路径（负样本）
    safe_cases = (
        "core/ai_engine.py",
        "modules/content.py",
        "tasks/analytics/daily_report_task.py",
        "VERSION.md",
    )
    for rel in safe_cases:
        assert not any(frag in rel for frag in deploy_vps.SKIP_PATH_FRAGMENTS), (
            f"SKIP_PATH_FRAGMENTS 不应命中正常路径: {rel}"
        )


def test_exclude_names_hits_execution_root_docs():
    """[v5.38.17 Graph Mode] EXCLUDE_NAMES 必须精确包含 EXECUTION_LOG.md / EXECUTION_REPORT.md，
    避免根目录过程流水文件误上传 VPS。"""
    import deploy_vps

    required = {"EXECUTION_LOG.md", "EXECUTION_REPORT.md"}
    missing = required - deploy_vps.EXCLUDE_NAMES
    assert not missing, f"EXCLUDE_NAMES 缺少关键保护项: {sorted(missing)}"

    # 核心保护项仍在（回归 guard）
    legacy_required = {"config.json", ".env", "mory.db", "deploy_vps.py", ".sync-conflict-"}
    missing_legacy = legacy_required - deploy_vps.EXCLUDE_NAMES
    assert not missing_legacy, f"EXCLUDE_NAMES 缺少历史保护项: {sorted(missing_legacy)}"


def test_resilient_upload_reconnects_and_retries_current_chunk(monkeypatch):
    import deploy_vps

    closed = []
    first_client = SimpleNamespace(close=lambda: closed.append("client-1"))
    first_sftp = SimpleNamespace(close=lambda: closed.append("sftp-1"))
    second_client = SimpleNamespace(close=lambda: closed.append("client-2"))
    second_sftp = SimpleNamespace(close=lambda: closed.append("sftp-2"))
    calls = []

    def fake_upload(sftp, _root, _vps_path, files, progress_cb=None):
        calls.append((sftp, tuple(files)))
        if len(calls) == 1:
            raise ConnectionError("dropped")
        if progress_cb:
            progress_cb(len(files), len(files))
        return [item[0] for item in files]

    monkeypatch.setattr(deploy_vps, "upload_files", fake_upload)
    monkeypatch.setattr(
        deploy_vps,
        "_open_deploy_connection",
        lambda: (second_client, second_sftp),
    )
    monkeypatch.setattr(deploy_vps.time, "sleep", lambda _seconds: None)

    client, sftp, uploaded = deploy_vps._upload_files_resilient(
        first_client,
        first_sftp,
        [("a.py", "/remote/a.py"), ("b.py", "/remote/b.py")],
        chunk_size=2,
        max_attempts=2,
    )

    assert (client, sftp) == (second_client, second_sftp)
    assert uploaded == ["a.py", "b.py"]
    assert len(calls) == 2
    assert closed == ["sftp-1", "client-1"]


def test_deploy_hash_preflight_only_returns_changed_files(monkeypatch, tmp_path):
    import deploy_vps

    (tmp_path / "same.py").write_text("same\n", encoding="utf-8")
    (tmp_path / "changed.py").write_text("changed\n", encoding="utf-8")
    monkeypatch.setattr(deploy_vps, "ROOT", tmp_path)
    monkeypatch.setattr(deploy_vps, "VPS_PATH", "/remote")
    monkeypatch.setattr(deploy_vps, "ensure_remote_dir", lambda _sftp, _path: None)

    class ManifestSFTP:
        def __init__(self):
            self.manifest = None
            self.removed = []

        def chmod(self, _path, _mode):
            pass

        def put(self, local, _remote):
            self.manifest = json.loads(Path(local).read_text(encoding="utf-8"))

        def remove(self, remote):
            self.removed.append(remote)

    class Client:
        def exec_command(self, command, timeout=120):
            assert "python3 -c" in command
            return _FakeStream(""), _FakeStream('["changed.py"]'), _FakeStream("")

    sftp = ManifestSFTP()
    result = deploy_vps._filter_changed_uploads(
        Client(),
        sftp,
        [
            ("same.py", "/remote/same.py"),
            ("changed.py", "/remote/changed.py"),
        ],
    )

    assert result == [("changed.py", "/remote/changed.py")]
    assert set(sftp.manifest) == {"same.py", "changed.py"}
    assert len(sftp.removed) == 1


def test_deploy_hash_preflight_rejects_unexpected_remote_path(monkeypatch, tmp_path):
    import deploy_vps

    (tmp_path / "safe.py").write_text("safe\n", encoding="utf-8")
    monkeypatch.setattr(deploy_vps, "ROOT", tmp_path)
    monkeypatch.setattr(deploy_vps, "VPS_PATH", "/remote")
    monkeypatch.setattr(deploy_vps, "ensure_remote_dir", lambda _sftp, _path: None)

    sftp = SimpleNamespace(
        chmod=lambda *_args: None,
        put=lambda *_args: None,
        remove=lambda *_args: None,
    )
    client = SimpleNamespace(
        exec_command=lambda *_args, **_kwargs: (
            _FakeStream(""),
            _FakeStream('["../escape.py"]'),
            _FakeStream(""),
        )
    )

    import pytest

    with pytest.raises(RuntimeError, match="清单外路径"):
        deploy_vps._filter_changed_uploads(
            client,
            sftp,
            [("safe.py", "/remote/safe.py")],
        )


def test_deploy_hash_preflight_reconnects_after_connection_drop(monkeypatch):
    import deploy_vps

    closed = []
    first_client = SimpleNamespace(close=lambda: closed.append("client-1"))
    first_sftp = SimpleNamespace(close=lambda: closed.append("sftp-1"))
    second_client = SimpleNamespace(close=lambda: closed.append("client-2"))
    second_sftp = SimpleNamespace(close=lambda: closed.append("sftp-2"))
    calls = []

    def fake_filter(client, sftp, files):
        calls.append((client, sftp, tuple(files)))
        if len(calls) == 1:
            raise ConnectionError("dropped")
        return [("changed.py", "/remote/changed.py")]

    monkeypatch.setattr(deploy_vps, "_filter_changed_uploads", fake_filter)
    monkeypatch.setattr(
        deploy_vps,
        "_open_deploy_connection",
        lambda: (second_client, second_sftp),
    )
    monkeypatch.setattr(deploy_vps.time, "sleep", lambda _seconds: None)

    client, sftp, changed = deploy_vps._filter_changed_uploads_resilient(
        first_client,
        first_sftp,
        [("changed.py", "/remote/changed.py")],
        max_attempts=2,
    )

    assert (client, sftp) == (second_client, second_sftp)
    assert changed == [("changed.py", "/remote/changed.py")]
    assert len(calls) == 2
    assert closed == ["sftp-1", "client-1"]


def test_deployment_exit_code_fails_closed():
    import deploy_vps

    assert deploy_vps._deployment_exit_code(True) == 0
    assert deploy_vps._deployment_exit_code(False) == 1


def test_deploy_source_gate_fails_closed_on_stale_branch(monkeypatch):
    import deploy_vps

    monkeypatch.setattr(deploy_vps, "check_git_clean", lambda: (True, "clean"))
    monkeypatch.setattr(
        deploy_vps,
        "check_head_contains_main",
        lambda: (False, "stale branch"),
    )

    assert deploy_vps._deploy_source_gate() == (False, "stale branch")


def test_systemd_install_command_sets_root_owner_and_fixed_mode():
    import deploy_vps

    command = deploy_vps._service_install_command("mory-assistant.service")

    assert "install -o root -g root -m 0644" in command
    assert "/.deploy-staging/mory-assistant.service" in command
    assert "/tmp/mory-assistant.service" not in command
    assert "/etc/systemd/system/mory-assistant.service" in command


def test_code_snapshot_excludes_credentials_and_is_private():
    import deploy_vps

    command = deploy_vps._code_backup_command()

    assert "--exclude='./.env'" in command
    assert "--exclude='./.env.*'" in command
    assert "--exclude='./config.json'" in command
    assert "chmod 0700 backups" in command
    assert "chmod 0600 backups/code_deploy_*.tar.gz" in command


def test_failed_deploy_does_not_claim_same_version_will_be_retried_or_restored():
    """Failed runtime verification must stay fail-closed and describe manual rollback truthfully."""
    import deploy_vps

    source = Path(deploy_vps.__file__).read_text(encoding="utf-8")

    assert "保险机制将重试" not in source
    assert "保险机制将自动恢复服务" not in source
    assert "_restart_services_fresh" not in source


def test_enable_command_covers_both_services():
    import deploy_vps

    command = deploy_vps._enable_services_command()

    assert "systemctl daemon-reload" in command
    assert "systemctl enable mory-assistant mory-dashboard" in command


def test_database_migration_runs_before_new_code_restart_contract():
    import shlex

    import deploy_vps

    command = deploy_vps._database_migration_command()
    script = shlex.split(command)[-1]

    assert ". ./.env" not in command
    assert "env.pop('DATABASE_URL', None)" in script
    assert "env['MORY_DB_PATH']" in script
    assert "/home/ubuntu/mory_assistant/mory.db" in script
    assert "\\home\\ubuntu" not in script
    assert "'alembic', 'upgrade', 'head'" in script
    assert "'alembic', 'current'" in script
    assert script.count("check=True") == 2
    assert "MIGRATION_OK" in script


def test_database_migration_is_guarded_by_verified_online_backup():
    import deploy_vps

    command = deploy_vps._database_backup_command()
    source = Path(deploy_vps.__file__).read_text(encoding="utf-8")

    assert "file:mory.db?mode=ro" in command
    assert "source.backup(snapshot)" in command
    assert "PRAGMA integrity_check" in command
    assert "PRAGMA foreign_key_check" in command
    assert "secrets.token_hex(8)" in command
    assert "os.chmod(stage, 0o600)" in command
    assert "os.replace(stage, target)" in command
    assert "DB_BACKUP_OK" in command
    deploy_body = source[source.index("def main"):]
    backup_call = deploy_body.index("_database_backup_command()")
    migration_call = deploy_body.index("_database_migration_command()")
    assert backup_call < migration_call


def test_runtime_permission_hardening_protects_credentials_and_watchdog():
    import deploy_vps

    command = deploy_vps._runtime_permission_hardening_command()

    assert "chmod 0600" in command
    assert ".env" in command
    assert "config.json" in command
    assert "install -o root -g root -m 0755" in command
    assert "/usr/local/lib/mory-assistant/vps_watchdog.py" in command
    assert "crontab" in command
    assert "sed '/vps_watchdog\\.py/d'" in command
    assert "grep -Fxc" in command
    assert "/tmp/mory-root-cron" not in command
    assert ".deploy-staging/root-cron.$$$$" in command


def test_deployment_verification_checks_direct_version_truth_and_permissions():
    from core.deploy_utils import _deployment_verification_checks

    checks = dict(_deployment_verification_checks("/home/ubuntu/mory_assistant"))

    assert "from version import VERSION" in checks["运行版本"]
    assert "/api/health" in checks["Health API"]
    assert "version" not in checks["Health API"].lower()
    assert "TOKEN" not in checks["配置完整性"]
    assert "API_KEY" not in checks["配置完整性"]
    assert "TG_TOKEN" in checks["凭据键"]
    assert "DASHSCOPE_KEY" in checks["凭据键"]
    assert "ENV_KEYS_OK" in checks["凭据键"]
    assert "task_execution_history" in checks["调度事实"]
    assert "scheduler_metrics" in checks["调度事实"]
    assert "DB_INTEGRITY_OK" in checks["数据库完整性"]
    assert "root:root 644" in checks["权限"]
    assert "root:root 755" in checks["权限"]
    assert "STARTUP_TIMESTAMP_UNAVAILABLE" in checks["Bot日志"]
    assert "exit 2" in checks["Bot日志"]
    assert r"\[(ERROR|CRITICAL)\]" in checks["Bot日志"]
    assert "|critical|error" not in checks["Bot日志"].lower()
    assert "critical_jobs_health_check" not in checks["Bot日志"]
    assert "failed_1h" in checks["调度事实"]
    assert "bad_metrics" in checks["调度事实"]
    assert "COALESCE(last_run,0) >= ?" in checks["调度事实"]
    assert "cumulative_metrics" in checks["调度事实"]
    assert "history_total" in checks["调度事实"]
    assert "history_latest_start" in checks["调度事实"]
    assert "transactional_tasks_only_1h" in checks["调度事实"]
    assert "ActiveEnterTimestamp" in checks["调度注册"]
    assert "-o cat" in checks["调度注册"]
    assert "scheduler_registry_receipt_from_logs" in checks["调度注册"]
    assert "SCHEDULER_REGISTRY_OK" not in checks["调度注册"]


def test_deployment_health_200_cannot_hide_version_mismatch():
    from core.deploy_utils import verify_deployment

    def exec_command(command, timeout=15):
        if "is-active" in command:
            output = "active"
        elif "/api/health" in command:
            output = "200"
        elif "from version import VERSION" in command:
            output = "v0.0.0"
        elif "SCHEDULER_REGISTRY_OK" in command:
            output = "SCHEDULER_REGISTRY_OK coverage=test"
        elif "journalctl" in command:
            output = "STARTUP_LOG_CLEAN"
        elif "ALL CONFIG OK" in command:
            output = "ALL CONFIG OK"
        elif "ENV_KEYS_OK" in command:
            output = "ENV_KEYS_OK"
        elif "DB_INTEGRITY_OK" in command:
            output = "DB_INTEGRITY_OK"
        elif "SCHEDULER_TRUTH_OK" in command:
            output = "SCHEDULER_TRUTH_OK coverage=transactional_history+historical_metrics"
        elif "PERMISSIONS_OK" in command:
            output = "PERMISSIONS_OK"
        else:
            raise AssertionError(command)
        return None, _FakeStream(output), _FakeStream("")

    ssh = SimpleNamespace(exec_command=exec_command)

    assert verify_deployment(ssh, "/home/ubuntu/mory_assistant") is False


def test_deployment_journal_evidence_gap_cannot_pass():
    from core.deploy_utils import verify_deployment

    def exec_command(command, timeout=15):
        if "is-active" in command:
            output, exit_code = "active", 0
        elif "/api/health" in command:
            output, exit_code = "200", 0
        elif "from version import VERSION" in command:
            from version import VERSION
            output, exit_code = VERSION, 0
        elif "SCHEDULER_REGISTRY_OK" in command:
            output, exit_code = "SCHEDULER_REGISTRY_OK coverage=test", 0
        elif "journalctl" in command:
            output, exit_code = "STARTUP_TIMESTAMP_UNAVAILABLE", 2
        elif "ALL CONFIG OK" in command:
            output, exit_code = "ALL CONFIG OK", 0
        elif "ENV_KEYS_OK" in command:
            output, exit_code = "ENV_KEYS_OK", 0
        elif "DB_INTEGRITY_OK" in command:
            output, exit_code = "DB_INTEGRITY_OK", 0
        elif "SCHEDULER_TRUTH_OK" in command:
            output, exit_code = "SCHEDULER_TRUTH_OK coverage=test", 0
        elif "PERMISSIONS_OK" in command:
            output, exit_code = "PERMISSIONS_OK", 0
        else:
            raise AssertionError(command)
        return None, _FakeStream(output, exit_code), _FakeStream("")

    assert verify_deployment(SimpleNamespace(exec_command=exec_command), "/home/ubuntu/mory_assistant") is False
