# -*- coding: utf-8 -*-
"""[Codex] 部署配置合并必须保护敏感值，但业务配置应以本地为准。"""

import os
import sys

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
        "NEWS_BROADCAST_CONFIG": {"enabled": True, "preferred_source": "real_first"},
    }
    vps_cfg = {
        "RELAY_MODE_ENABLED": False,
        "BLIND_BOX_COST": 30,
        "NEWS_BROADCAST_CONFIG": {"enabled": False, "preferred_source": "trendradar_first"},
    }

    merged = safe_merge_config(local_cfg, vps_cfg)

    assert merged["RELAY_MODE_ENABLED"] is True
    assert merged["BLIND_BOX_COST"] == 35
    assert merged["NEWS_BROADCAST_CONFIG"]["preferred_source"] == "real_first"


def test_deploy_manifest_excludes_sync_conflicts_and_includes_truth_docs():
    import deploy_vps

    assert all(".sync-conflict-" not in path for path in deploy_vps.UPLOAD_FILES)
    assert {
        "AGENTS.md",
        "README.md",
        "AI_DEBUG_HISTORY.md",
        "CHANGELOG.md",
        "VERSION.md",
        "project_snapshot.md",
    }.issubset(set(deploy_vps.UPLOAD_FILES))
    assert {
        "migrations/versions/0002_reply_style_samples.py",
        "migrations/versions/0003_business_conversation_context.py",
        "tasks/maintenance/conversation_context_cleanup_task.py",
    }.issubset(set(deploy_vps.UPLOAD_FILES))
