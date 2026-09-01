from types import SimpleNamespace

from flask import Flask

import dashboard.api.config_api as config_api
import dashboard.helpers as dashboard_helpers
from modules import settings_panel


class _Bot:
    def __init__(self):
        self.messages = []
        self.answers = []

    def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))

    def answer_callback_query(self, call_id, **kwargs):
        self.answers.append((call_id, kwargs))


def _dashboard_client(role):
    app = Flask(__name__)
    app.secret_key = "keyword-admin-settings"
    app.register_blueprint(config_api.config_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = role
    return client


def test_dashboard_hides_keyword_rules_from_non_admin(monkeypatch):
    monkeypatch.setattr(
        config_api,
        "read_config",
        lambda: {
            "BOT_NAME": "Mory",
            "KEYWORD_AUTO_DELETE_CONFIG": {"enabled": True, "rules": [{"keyword": "secret"}]},
        },
    )

    viewer = _dashboard_client("viewer").get("/api/config").get_json()["data"]["config"]
    admin = _dashboard_client("admin").get("/api/config").get_json()["data"]["config"]

    assert "KEYWORD_AUTO_DELETE_CONFIG" not in viewer
    assert admin["KEYWORD_AUTO_DELETE_CONFIG"]["rules"][0]["keyword"] == "secret"


def test_dashboard_cannot_expose_or_restore_retired_config_fields(monkeypatch):
    from core.config_compat import INVALID_TOP_LEVEL_CONFIG_FIELDS

    monkeypatch.setattr(
        config_api,
        "read_config",
        lambda: {
            "BOT_NAME": "Mory",
            **{key: {"legacy": True} for key in INVALID_TOP_LEVEL_CONFIG_FIELDS},
        },
    )
    assert config_api.ALLOWED_CONFIG_FIELDS.isdisjoint(INVALID_TOP_LEVEL_CONFIG_FIELDS)

    client = _dashboard_client("admin")
    visible = client.get("/api/config").get_json()["data"]["config"]
    assert set(visible).isdisjoint(INVALID_TOP_LEVEL_CONFIG_FIELDS)

    response = client.post(
        "/api/config/update",
        json={"key": "API_KEYS", "value": {"legacy": "secret"}},
    )
    assert response.status_code == 403

    pseudo_response = client.post(
        "/api/config/update",
        json={"key": "MYSTIC_BROADCAST_ENABLED", "value": True},
    )
    assert pseudo_response.status_code == 403


def test_dashboard_admin_save_normalizes_multi_rule_config(monkeypatch):
    stored = {}
    monkeypatch.setattr(config_api, "read_config", lambda: {})
    monkeypatch.setattr(config_api, "write_config", lambda cfg: stored.update(cfg) is None)
    client = _dashboard_client("admin")

    response = client.post(
        "/api/config/update",
        json={
            "key": "KEYWORD_AUTO_DELETE_CONFIG",
            "value": {
                "enabled": True,
                "rules": [
                    {"keyword": "foo", "delay_seconds": 7, "match_mode": "contains"},
                    {"keyword": "bar", "delay_seconds": 19, "match_mode": "exact"},
                ],
            },
        },
    )

    assert response.status_code == 200
    assert [rule["delay_seconds"] for rule in stored["KEYWORD_AUTO_DELETE_CONFIG"]["rules"]] == [7, 19]


def test_bot_rule_input_is_admin_only_and_saves_canonical_rules(monkeypatch):
    saved = []
    monkeypatch.setattr(settings_panel, "_save_config", lambda cfg: saved.append(cfg.copy()))
    config = {
        "ADMIN_ID": 42,
        "KEYWORD_AUTO_DELETE_CONFIG": {"enabled": True, "rules": []},
    }
    bot = _Bot()

    settings_panel._request_keyword_rule_value(bot, -1001, 42, config)
    assert settings_panel.apply_pending_value(
        bot,
        -1001,
        42,
        "/me@afoolGroupBot | 300 | exact | 否",
        config,
    ) is True
    assert config["KEYWORD_AUTO_DELETE_CONFIG"]["rules"][0]["delay_seconds"] == 300
    assert saved

    call = SimpleNamespace(
        id="cb1",
        data="settings_security_kad_add",
        from_user=SimpleNamespace(id=99),
        message=SimpleNamespace(chat=SimpleNamespace(id=-1001), message_id=1),
    )
    assert settings_panel.handle_settings_callback(bot, call, config) is True
    assert bot.answers[-1][1]["show_alert"] is True
    assert not settings_panel.has_pending_session(-1001, 99)


def test_dashboard_config_write_tightens_temp_permissions_before_replace(monkeypatch, tmp_path):
    modes = []
    replace_calls = []
    real_replace = dashboard_helpers.os.replace
    monkeypatch.setattr(dashboard_helpers, "_MORY_ROOT", str(tmp_path))
    monkeypatch.setattr(dashboard_helpers, "_signal_config_reload", lambda: None)
    monkeypatch.setattr(dashboard_helpers.os, "chmod", lambda path, mode: modes.append((path, mode)))

    def tracked_replace(source, target):
        replace_calls.append((source, target, list(modes)))
        real_replace(source, target)

    monkeypatch.setattr(dashboard_helpers.os, "replace", tracked_replace)

    assert dashboard_helpers.write_config({"KEYWORD_AUTO_DELETE_CONFIG": {"enabled": False}}) is True
    assert modes[-1][1] == 0o600
    assert replace_calls[0][2][-1][1] == 0o600
