from types import SimpleNamespace

import pytest

from tasks.maintenance.startup_history_cleanup_task import StartupHistoryCleanupTask


class _FakeDB:
    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.states = {}
        self.query_modes = []

    def get_system_state(self, key, default=None):
        return self.states.get(key, default)

    def set_system_state(self, key, value):
        self.states[key] = value

    def get_blacklisted_ad_cleanup_candidates(
        self, chat_id, *, include_deleted, limit_per_user
    ):
        self.query_modes.append(include_deleted)
        if include_deleted:
            return list(self.candidates)
        return [row for row in self.candidates if not row.get("deleted")]


def _task(db, config=None):
    rm = SimpleNamespace(
        bot=object(),
        db=db,
        config=config or {"GROUP_ID": -1001},
    )
    return StartupHistoryCleanupTask(rm)


def test_first_run_builds_baseline_then_restart_only_queries_pending(monkeypatch):
    db = _FakeDB([{"msg_id": 10, "deleted": 1}])
    deleted = []

    def _already_absent(bot, database, chat_id, msg_id):
        deleted.append((chat_id, msg_id))
        return {
            "status": "already_absent",
            "deleted": False,
            "evidence_persisted": True,
            "deletion_persisted": True,
        }

    monkeypatch.setattr(
        "modules.ad_enforcement.delete_confirmed_ad_message",
        _already_absent,
    )

    task = _task(db)
    task.run()
    task.run()

    assert db.query_modes == [True, False]
    assert deleted == [(-1001, 10)]
    assert any(key.startswith("startup_history_cleanup_verified_v1:") for key in db.states)


def test_failed_deletion_does_not_create_trusted_baseline(monkeypatch):
    db = _FakeDB([{"msg_id": 10, "deleted": 0}])
    monkeypatch.setattr(
        "modules.ad_enforcement.delete_confirmed_ad_message",
        lambda *args: {
            "status": "failed",
            "deleted": False,
            "evidence_persisted": True,
            "deletion_persisted": False,
        },
    )

    with pytest.raises(ExceptionGroup, match="启动历史清理任务失败"):
        _task(db).run()

    assert db.states == {}


def test_unpersisted_delete_result_does_not_create_trusted_baseline(monkeypatch):
    db = _FakeDB([{"msg_id": 10, "deleted": 0}])
    monkeypatch.setattr(
        "modules.ad_enforcement.delete_confirmed_ad_message",
        lambda *args: {
            "status": "already_absent",
            "deleted": False,
            "evidence_persisted": True,
            "deletion_persisted": False,
        },
    )

    with pytest.raises(ExceptionGroup, match="启动历史清理任务失败"):
        _task(db).run()

    assert db.states == {}


def test_invalid_candidate_does_not_create_trusted_baseline(monkeypatch):
    db = _FakeDB([{"msg_id": 0, "deleted": 0}])
    monkeypatch.setattr(
        "modules.ad_enforcement.delete_confirmed_ad_message",
        lambda *args: pytest.fail("invalid candidate must not call Telegram"),
    )

    with pytest.raises(ExceptionGroup, match="启动历史清理任务失败"):
        _task(db).run()

    assert db.states == {}


def test_baseline_write_failure_remains_visible(monkeypatch):
    class _WriteFailDB(_FakeDB):
        def set_system_state(self, key, value):
            raise RuntimeError("database is locked")

    db = _WriteFailDB([])

    with pytest.raises(ExceptionGroup, match="启动历史清理任务失败"):
        _task(db).run()

    assert db.states == {}


def test_multi_group_failure_only_persists_successful_group_baseline():
    class _PartialFailDB(_FakeDB):
        def get_blacklisted_ad_cleanup_candidates(
            self, chat_id, *, include_deleted, limit_per_user
        ):
            if chat_id == -1002:
                raise RuntimeError("candidate query failed")
            return []

    db = _PartialFailDB([])

    with pytest.raises(ExceptionGroup, match="启动历史清理任务失败"):
        _task(db, {"MANAGED_GROUPS": [-1001, -1002]}).run()

    assert "startup_history_cleanup_verified_v1:-1001" in db.states
    assert "startup_history_cleanup_verified_v1:-1002" not in db.states


def test_incremental_cleanup_drains_multiple_batches(monkeypatch):
    class _PagedDB(_FakeDB):
        def __init__(self):
            super().__init__([])
            self.states["startup_history_cleanup_verified_v1:-1001"] = "1"
            self.batches = [
                [{"msg_id": 10, "deleted": 0}],
                [{"msg_id": 11, "deleted": 0}],
                [],
            ]

        def get_blacklisted_ad_cleanup_candidates(
            self, chat_id, *, include_deleted, limit_per_user
        ):
            assert include_deleted is False
            return self.batches.pop(0)

    db = _PagedDB()
    deleted = []

    def _delete(bot, database, chat_id, msg_id):
        deleted.append(msg_id)
        return {
            "status": "deleted",
            "deleted": True,
            "evidence_persisted": True,
            "deletion_persisted": True,
        }

    monkeypatch.setattr("modules.ad_enforcement.delete_confirmed_ad_message", _delete)

    _task(db).run()

    assert deleted == [10, 11]
    assert db.batches == []


def test_invalid_baseline_value_fails_closed_to_full_verification(monkeypatch):
    db = _FakeDB([])
    db.states["startup_history_cleanup_verified_v1:-1001"] = "invalid"
    monkeypatch.setattr(
        "modules.ad_enforcement.delete_confirmed_ad_message",
        lambda *args: pytest.fail("empty full verification must not call Telegram"),
    )

    _task(db).run()

    assert db.query_modes == [True]
    assert db.states["startup_history_cleanup_verified_v1:-1001"].isdigit()
