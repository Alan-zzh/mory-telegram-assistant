# -*- coding: utf-8 -*-
"""[Codex] 部署配置合并必须保护敏感值，但业务配置应以本地为准。"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


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


def test_runtime_sync_cannot_restore_legacy_auto_greeting_switches():
    from core.deploy_utils import sync_runtime_fields_from_vps

    local = {"AUTO_GREETING": False, "AUTO_GOODNIGHT": False}
    remote = {"AUTO_GREETING": True, "AUTO_GOODNIGHT": True}

    merged, synced = sync_runtime_fields_from_vps(local, remote)

    assert merged == {"AUTO_GREETING": False, "AUTO_GOODNIGHT": False}
    assert "AUTO_GREETING" not in synced
    assert "AUTO_GOODNIGHT" not in synced


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


def test_deployment_exit_code_fails_closed():
    import deploy_vps

    assert deploy_vps._deployment_exit_code(True) == 0
    assert deploy_vps._deployment_exit_code(False) == 1


def test_systemd_install_command_sets_root_owner_and_fixed_mode():
    import deploy_vps

    command = deploy_vps._service_install_command("mory-assistant.service")

    assert "install -o root -g root -m 0644" in command
    assert "/.deploy-staging/mory-assistant.service" in command
    assert "/tmp/mory-assistant.service" not in command
    assert "/etc/systemd/system/mory-assistant.service" in command


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
