"""Dashboard 风格样本接口必须适配 sqlite3.Connection。"""

import sqlite3

from flask import Flask


def _set_role(client, role: str):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = role
        session["username"] = f"test_{role}"


def test_reply_style_sample_dashboard_workflow_uses_sqlite_connection(monkeypatch, tmp_path):
    import dashboard.api.quality_api as quality_api

    conn = sqlite3.connect(tmp_path / "reply_evolution.db")
    # Dashboard 实际返回的是 Connection，而非 core.database.DB。
    monkeypatch.setattr(quality_api, "get_db", lambda: conn)

    app = Flask(__name__)
    app.secret_key = "test-dashboard-secret"
    app.config["TESTING"] = True
    app.register_blueprint(quality_api.quality_bp)
    client = app.test_client()

    _set_role(client, "viewer")
    denied = client.post(
        "/api/quality/reply-style-samples",
        json={"label": "viewer", "style_text": "先接住对方的话，再自然回复。"},
    )
    assert denied.status_code == 403

    _set_role(client, "admin")
    created = client.post(
        "/api/quality/reply-style-samples",
        json={"label": "自然承接", "style_text": "先接住对方的话，再自然回复。"},
    )
    assert created.status_code == 201
    sample_id = created.get_json()["data"]["id"]

    reviewed = client.post(
        f"/api/quality/reply-style-samples/{sample_id}/review",
        json={"status": "approved", "enabled": False},
    )
    assert reviewed.status_code == 200
    assert reviewed.get_json()["data"]["enabled"] is False

    enabled = client.post(
        f"/api/quality/reply-style-samples/{sample_id}/enabled",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.get_json()["data"]["enabled"] is True

    listed = client.get("/api/quality/reply-style-samples?status=approved")
    assert listed.status_code == 200
    assert listed.get_json()["data"] == [{
        "id": sample_id,
        "label": "自然承接",
        "style_text": "先接住对方的话，再自然回复。",
        "status": "approved",
        "enabled": 1,
        "created_by": "test_admin",
        "reviewed_by": "test_admin",
        "created_at": listed.get_json()["data"][0]["created_at"],
        "reviewed_at": listed.get_json()["data"][0]["reviewed_at"],
        "review_note": "",
    }]
    conn.close()
