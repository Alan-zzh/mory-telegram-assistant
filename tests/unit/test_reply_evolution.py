# -*- coding: utf-8 -*-
import json
import sqlite3
import importlib.util
from threading import RLock
from pathlib import Path

from core.db_repos.reply_evolution_repo import ReplyEvolutionRepo
from core.handlers.ai_reply_handler import _build_reply_evolution_hint


class _FakeDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.lock = RLock()
        self.conn.execute(
            """CREATE TABLE reply_style_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL DEFAULT '',
                style_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                enabled INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '', review_note TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL, reviewed_at INTEGER NOT NULL DEFAULT 0,
                scene TEXT NOT NULL DEFAULT 'chat'
            )"""
        )
        self.repo = ReplyEvolutionRepo(self)

    def get_approved_reply_style_samples(self, limit):
        return self.repo.get_approved_reply_style_samples(limit)


def test_style_sample_requires_explicit_approval_and_enablement():
    db = _FakeDB()
    created = db.repo.create_reply_style_sample("先回应眼前的问题，再用简短自然的话承接。", "承接")
    assert created["ok"] is True
    sample_id = created["id"]
    assert db.repo.get_approved_reply_style_samples() == []

    assert db.repo.set_reply_style_sample_enabled(sample_id, True)["ok"] is False
    reviewed = db.repo.review_reply_style_sample(sample_id, "approved", "admin", enabled=True)
    assert reviewed == {"ok": True, "status": "approved", "enabled": True}
    assert db.repo.get_approved_reply_style_samples() == ["先回应眼前的问题，再用简短自然的话承接。"]


def test_unsafe_style_sample_is_rejected_before_persistence():
    db = _FakeDB()
    result = db.repo.create_reply_style_sample("*歪头看你* 现在限时只剩最后 2 个名额", "unsafe")
    assert result["ok"] is False
    assert "动作" in result["error"] or "稀缺" in result["error"]
    assert db.repo.list_reply_style_samples() == []


def test_evolution_hint_only_uses_approved_enabled_samples():
    db = _FakeDB()
    created = db.repo.create_reply_style_sample("先把对方的问题答清楚，再自然补一句。")
    db.repo.review_reply_style_sample(created["id"], "approved", enabled=True)
    hint = _build_reply_evolution_hint(
        db,
        {"REPLY_EVOLUTION_CONFIG": {
            "enabled": True, "human_approval_required": True,
            "approved_style_samples": True, "max_prompt_samples": 3,
            "auto_apply": False, "raw_event_text": False,
        }},
    )
    assert "人工审核风格参考" in hint
    assert "先把对方的问题答清楚" in hint


def test_evolution_hint_is_current_scene_only_and_drops_fact_cta_samples():
    class _SceneDb:
        def __init__(self):
            self.scenes = []

        def get_approved_reply_style_samples(self, limit, scene=None):
            self.scenes.append(scene)
            return [
                "用户：加微信\nMory：一个月费都不支持，去 @MorychannelBot 下单。",
                "用户：在吗\nMory：在，直接说你遇到什么问题。",
            ][:limit]

    db = _SceneDb()
    hint = _build_reply_evolution_hint(
        db,
        {"REPLY_EVOLUTION_CONFIG": {
            "enabled": True, "human_approval_required": True,
            "approved_style_samples": True, "max_prompt_samples": 3,
        }},
        scene="chat",
    )
    assert db.scenes == ["chat"]
    assert "直接说你遇到什么问题" in hint
    assert "一个月费" not in hint
    assert "@MorychannelBot" not in hint


def test_reply_contract_config_is_safe_and_manual():
    root = Path(__file__).resolve().parents[2]
    # config.json 含运行时凭据且被 Git 忽略；可复现契约只检查版本化示例。
    for name in ("config.json.example",):
        cfg = json.loads((root / name).read_text(encoding="utf-8"))
        assert cfg["REPLY_CONTRACT_VERSION"] == "1.0.0"
        assert cfg["REPLY_EVOLUTION_CONFIG"] == {
            "enabled": True,
            "human_approval_required": True,
            "auto_apply": False,
            "approved_style_samples": True,
            "max_prompt_samples": 3,
            "raw_event_text": False,
        }
        assert "不声明自己是真人" in cfg["BASE_PERSONA"]
        assert "绝对不是AI" not in cfg["BASE_PERSONA"]
        assert "虚假稀缺" in cfg["BASE_PERSONA"]


def test_reply_style_samples_migration_is_idempotent_and_reversible(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    migration_path = Path(__file__).parents[2] / "migrations/versions/0002_reply_style_samples.py"
    spec = importlib.util.spec_from_file_location("reply_style_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert inspector.has_table("reply_style_samples")
        assert "idx_reply_style_samples_active" in {
            item["name"] for item in inspector.get_indexes("reply_style_samples")
        }
        migration.downgrade()
        assert not sa.inspect(connection).has_table("reply_style_samples")
