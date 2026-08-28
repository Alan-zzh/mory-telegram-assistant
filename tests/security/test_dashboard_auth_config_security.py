"""Dashboard 身份、RBAC 路由与配置脱敏的安全回归测试。"""

import json
import sqlite3

from flask import Flask

import dashboard.api.config_api as config_api
import dashboard.api.rbac_approval_api as rbac_approval_api
import dashboard.api.settings_api as settings_api
import dashboard.helpers as dashboard_helpers
from dashboard.audit import _summarize_payload, has_permission
from dashboard.auth import init_auth
from dashboard.rbac_guard import _infer_permission, enforce_rbac


def _permission_db():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE role_permissions (role TEXT, permission TEXT)")
    db.executemany(
        "INSERT INTO role_permissions (role, permission) VALUES (?, ?)",
        [
            ("admin", "config:write"),
            ("admin", "users:write"),
            ("viewer", "config:read"),
        ],
    )
    db.commit()
    return db


def _app(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "dashboard-security-test-secret"
    init_auth(app)
    app.register_blueprint(config_api.config_bp)
    app.register_blueprint(settings_api.settings_bp)
    app.register_blueprint(rbac_approval_api.rbac_approval_bp)
    app.before_request(enforce_rbac)

    db = _permission_db()
    monkeypatch.setattr(dashboard_helpers, "get_db", lambda: db)
    return app


def _csrf_headers(client):
    token = "csrf-test-token"
    with client.session_transaction() as session:
        session["_csrf_token"] = token
    return {"X-Requested-With": "XMLHttpRequest", "X-CSRF-Token": token}


def _set_session(client, role="admin", uid=101):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = role
        session["uid"] = uid
        session["username"] = f"test-{role}"


def test_viewer_login_cannot_claim_admin_user_id(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("DASHBOARD_VIEWER_PASSWORD", "viewer-pass-123")
    monkeypatch.delenv("DASHBOARD_VIEWER_UID", raising=False)
    monkeypatch.delenv("DASHBOARD_VIEWER_USERNAME", raising=False)
    client = _app(monkeypatch).test_client()

    response = client.post(
        "/api/login",
        json={"password": "viewer-pass-123", "user_id": 1, "username": "admin"},
    )

    assert response.status_code == 200
    assert response.get_json()["role"] == "viewer"
    with client.session_transaction() as session:
        assert session["role"] == "viewer"
        assert "uid" not in session
        assert session["username"] == "dashboard-viewer"


def test_login_binds_only_server_configured_principal(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("DASHBOARD_VIEWER_PASSWORD", "viewer-pass-123")
    monkeypatch.setenv("DASHBOARD_VIEWER_UID", "2002")
    monkeypatch.setenv("DASHBOARD_VIEWER_USERNAME", "readonly-principal")
    client = _app(monkeypatch).test_client()

    response = client.post(
        "/api/login",
        json={"password": "viewer-pass-123", "user_id": 1, "username": "forged"},
    )

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["role"] == "viewer"
        assert session["uid"] == 2002
        assert session["username"] == "readonly-principal"


def test_viewer_can_logout_without_config_write_permission(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "admin-pass-123")
    monkeypatch.setenv("DASHBOARD_VIEWER_PASSWORD", "viewer-pass-123")
    client = _app(monkeypatch).test_client()
    login = client.post("/api/login", json={"password": "viewer-pass-123"}).get_json()

    response = client.post(
        "/api/logout",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-Token": login["csrf_token"],
        },
    )

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert not session


def test_config_api_recursively_redacts_nested_credentials(monkeypatch):
    config = {
        "TOKEN": "telegram-secret",
        "MAX_TOKENS": 500,
        "NSFW_DETECT_CONFIG": {"enabled": True, "api_key": "nsfw-secret"},
        "MODEL_POOLS": [{"api_key": "model-secret", "api_key_env": "MODEL_KEY_ENV"}],
    }
    monkeypatch.setattr(config_api, "read_config", lambda: config)
    client = _app(monkeypatch).test_client()
    _set_session(client, role="viewer")

    response = client.get("/api/config")
    payload = response.get_json()["data"]["config"]

    assert "TOKEN" not in payload
    assert payload["MAX_TOKENS"] == 500
    assert payload["NSFW_DETECT_CONFIG"]["api_key"] == "***"
    assert payload["MODEL_POOLS"][0]["api_key"] == "***"
    assert payload["MODEL_POOLS"][0]["api_key_env"] == "MODEL_KEY_ENV"
    assert "nsfw-secret" not in json.dumps(payload)
    assert "model-secret" not in json.dumps(payload)


def test_config_update_rejects_nested_credential(monkeypatch):
    monkeypatch.setattr(config_api, "read_config", lambda: {})
    client = _app(monkeypatch).test_client()
    _set_session(client, role="admin")

    response = client.post(
        "/api/config/update",
        json={"key": "MODEL_POOLS", "value": [{"api_key": "must-not-persist"}]},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 400
    assert "不得通过 Dashboard" in response.get_json()["msg"]


def test_settings_never_return_or_accept_configured_credentials(monkeypatch):
    config = {
        "NSFW_DETECT_CONFIG": {"enabled": True, "threshold": 0.8, "api_key": "nsfw-secret"},
        "SPAM_WATCH_CONFIG": {"cas_enabled": True, "spamwatch_enabled": True, "spamwatch_token": "spam-secret"},
        "EXCHANGE_RATE_ENABLE": True,
        "EXCHANGE_API_KEY": "exchange-secret",
    }
    monkeypatch.setattr(settings_api, "read_config", lambda: config)
    client = _app(monkeypatch).test_client()
    _set_session(client, role="admin")

    nsfw = client.get("/api/settings/nsfw").get_json()["data"]
    cas = client.get("/api/settings/cas").get_json()["data"]
    exchange = client.get("/api/settings/exchange-rate").get_json()["data"]
    combined = json.dumps({"nsfw": nsfw, "cas": cas, "exchange": exchange})
    assert "nsfw-secret" not in combined
    assert "spam-secret" not in combined
    assert "exchange-secret" not in combined
    assert nsfw["api_key"] == "***"
    assert "spamwatch_token" not in cas
    assert "api_key" not in exchange

    headers = _csrf_headers(client)
    assert client.post("/api/settings/nsfw", json={"api_key": "x"}, headers=headers).status_code == 400
    assert client.post("/api/settings/cas", json={"spamwatch_token": "x"}, headers=headers).status_code == 400
    assert client.post("/api/settings/exchange-rate", json={"api_key": "x"}, headers=headers).status_code == 400


def test_rbac_request_and_cancel_use_trusted_session_uid(monkeypatch):
    called = []
    monkeypatch.setattr(
        rbac_approval_api,
        "create_request",
        lambda **kwargs: called.append(("create", kwargs)) or {"ok": True, "request_id": 9},
    )
    monkeypatch.setattr(
        rbac_approval_api,
        "cancel_request",
        lambda **kwargs: called.append(("cancel", kwargs)) or {"ok": True},
    )
    client = _app(monkeypatch).test_client()
    _set_session(client, role="viewer", uid=2002)
    headers = _csrf_headers(client)

    create = client.post(
        "/api/rbac/request",
        json={"target_user_id": 3003, "requested_role": "operator", "reason": "need access"},
        headers=headers,
    )
    cancel = client.post("/api/rbac/cancel", json={"request_id": 9}, headers=headers)

    assert create.status_code == 200
    assert cancel.status_code == 200
    assert called == [
        ("create", {"requester_id": 2002, "target_user_id": 3003, "requested_role": "operator", "reason": "need access"}),
        ("cancel", {"request_id": 9, "requester_id": 2002}),
    ]


def test_actual_api_path_mapping_and_dynamic_permission_fail_closed():
    assert _infer_permission("/api/settings/nsfw") == "config:write"
    assert _infer_permission("/api/faq/knowledge") == "faq:write"
    assert _infer_permission("/api/rbac/approve") == "users:write"

    db = sqlite3.connect(":memory:")
    assert has_permission("config:write", role="admin", db=db) is False
    db.execute("CREATE TABLE role_permissions (role TEXT, permission TEXT)")
    db.execute("INSERT INTO role_permissions VALUES ('admin', 'config:write')")
    assert has_permission("config:write", role="admin", db=db) is True


def test_audit_payload_redacts_nested_credentials():
    app = Flask(__name__)
    with app.test_request_context(
        "/api/config/update",
        method="POST",
        json={"value": {"api_key": "never-log-this"}, "max_tokens": 99},
    ):
        summary = _summarize_payload()

    assert "never-log-this" not in summary
    assert "***" in summary
    assert "99" in summary
