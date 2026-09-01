from pathlib import Path

from flask import Flask

import dashboard.api.group_api as group_api
import dashboard.api.settings_api as settings_api
from core.config_compat import REMOVED_CONFIG_FIELDS, compact_runtime_config
from modules.natural_cmd import ALL_CONFIGS


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _client(*blueprints):
    app = Flask(__name__)
    app.secret_key = "dead-config-retirement"
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"
    return client


def test_retired_fields_are_not_natural_language_settings():
    assert set(ALL_CONFIGS).isdisjoint(REMOVED_CONFIG_FIELDS)


def test_group_api_excludes_and_rejects_fake_limits(monkeypatch):
    monkeypatch.setattr(
        group_api,
        "read_config",
        lambda: {
            "SPAM_LIMIT": {"messages_per_minute": 10, "ban_minutes": 5},
            "BAN_DURATION_DEFAULT": 99,
            "MAX_REQUESTS_PER_USER": 999,
        },
    )
    client = _client(group_api.group_bp)

    visible = client.get("/api/group/settings").get_json()["data"]
    assert "spam_ban_duration" not in visible
    assert "max_requests_per_user" not in visible
    for key in ("BAN_DURATION_DEFAULT", "MAX_REQUESTS_PER_USER"):
        response = client.post(
            "/api/group/settings/update",
            json={"key": key, "value": 123},
        )
        assert response.status_code == 403


def test_bot_core_api_does_not_show_or_write_fake_request_limit(monkeypatch):
    store = {
        "BOT_NAME": "Mory小助理",
        "ENABLE_MESSAGE_DELETION": False,
        "MAX_REQUESTS_PER_USER": 999,
    }
    saved = {}
    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))
    monkeypatch.setattr(
        settings_api,
        "write_config",
        lambda cfg: saved.update(compact_runtime_config(cfg)) is None,
    )
    client = _client(settings_api.settings_bp)

    visible = client.get("/api/settings/bot-core").get_json()["data"]
    assert "max_requests_per_user" not in visible

    response = client.post(
        "/api/settings/bot-core",
        json={
            "bot_name": "Mory",
            "enable_message_deletion": True,
            "max_requests_per_user": 12,
        },
    )
    assert response.status_code == 200
    assert saved["BOT_NAME"] == "Mory"
    assert saved["ENABLE_MESSAGE_DELETION"] is True
    assert "MAX_REQUESTS_PER_USER" not in saved


def test_dashboard_template_has_no_retired_fake_controls():
    source = (PROJECT_ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    for key in (
        "BAN_DURATION_DEFAULT",
        "MAX_REQUESTS_PER_USER",
        "REPLY_DELAY_MIN",
        "REPLY_DELAY_MAX",
        "MAX_MSG_LENGTH",
    ):
        assert key not in source
