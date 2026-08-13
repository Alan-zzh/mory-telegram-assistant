import sqlite3
import time
from types import SimpleNamespace

from core.db_repos.config_repo import ConfigRepo


def _repo(tmp_path):
    conn = sqlite3.connect(tmp_path / "onboarding.db")
    conn.execute(
        """CREATE TABLE onboarding_deliveries (
            uid INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            surface TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            claimed_at INTEGER NOT NULL,
            delivered_at INTEGER,
            PRIMARY KEY (uid, chat_id, surface)
        )"""
    )
    db = SimpleNamespace(conn=conn, lock=__import__("threading").RLock())
    return ConfigRepo(db), conn


def test_onboarding_delivery_claim_complete_and_restart_persistence(tmp_path):
    repo, conn = _repo(tmp_path)
    key = (42, -100, "group_mention")

    assert repo.has_onboarding_delivery(*key) is False
    assert repo.claim_onboarding_delivery(*key) is True
    assert repo.claim_onboarding_delivery(*key) is False
    assert repo.complete_onboarding_delivery(*key) is True
    assert repo.has_onboarding_delivery(*key) is True
    conn.close()

    reopened = sqlite3.connect(tmp_path / "onboarding.db")
    db = SimpleNamespace(conn=reopened, lock=__import__("threading").RLock())
    assert ConfigRepo(db).has_onboarding_delivery(*key) is True
    assert ConfigRepo(db).claim_onboarding_delivery(*key) is False
    reopened.close()


def test_onboarding_failed_send_releases_and_stale_pending_recovers(tmp_path):
    repo, conn = _repo(tmp_path)
    key = (43, -100, "group_mention")

    assert repo.claim_onboarding_delivery(*key) is True
    assert repo.release_onboarding_delivery(*key) is True
    assert repo.claim_onboarding_delivery(*key) is True
    conn.execute(
        "UPDATE onboarding_deliveries SET claimed_at=? WHERE uid=? AND chat_id=? AND surface=?",
        (int(time.time()) - 300, *key),
    )
    conn.commit()
    assert repo.claim_onboarding_delivery(*key) is True
    conn.close()


def test_onboarding_is_scoped_per_user_and_group(tmp_path):
    repo, conn = _repo(tmp_path)
    assert repo.claim_onboarding_delivery(42, -100, "group_mention") is True
    assert repo.complete_onboarding_delivery(42, -100, "group_mention") is True
    assert repo.claim_onboarding_delivery(42, -200, "group_mention") is True
    assert repo.claim_onboarding_delivery(43, -100, "group_mention") is True
    conn.close()
