# -*- coding: utf-8 -*-
"""[Codex] 后台设置别名路由必须共用同一套实现，避免双份逻辑再次漂移。"""

import os
import sys

from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


def _make_client():
    from dashboard.api.settings_api import settings_bp

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(settings_bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"
    return client


def test_clean_service_alias_routes_share_same_storage(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {"CLEAN_SERVICE_DEFAULT": True}

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp_old = client.get("/api/settings/cleanservice")
    resp_new = client.get("/api/settings/clean-service")
    assert resp_old.status_code == 200
    assert resp_new.status_code == 200
    assert resp_old.get_json()["data"] == {"enabled": True}
    assert resp_new.get_json()["data"] == {"enabled": True}

    save_resp = client.post("/api/settings/clean-service", json={"enabled": False})
    assert save_resp.status_code == 200
    assert store["CLEAN_SERVICE_DEFAULT"] is False


def test_dashboard_alias_routes_share_same_storage(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {"VISUAL_DASHBOARD_ENABLE": False}

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp_old = client.get("/api/settings/visual-dashboard")
    resp_new = client.get("/api/settings/dashboard")
    assert resp_old.status_code == 200
    assert resp_new.status_code == 200
    assert resp_old.get_json()["data"] == {"enabled": False}
    assert resp_new.get_json()["data"] == {"enabled": False}

    save_resp = client.post("/api/settings/dashboard", json={"enabled": True})
    assert save_resp.status_code == 200
    assert store["VISUAL_DASHBOARD_ENABLE"] is True


def test_daily_quest_and_achievement_alias_routes_share_same_handlers(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "DAILY_QUEST_CONFIG": {"enabled": False},
        "ACHIEVEMENT_CONFIG": {"enabled": True},
    }

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    assert client.get("/api/settings/dailyquest").get_json()["data"]["enabled"] is False
    assert client.get("/api/settings/daily-quest").get_json()["data"]["enabled"] is False
    assert client.get("/api/settings/achievement").get_json()["data"]["enabled"] is True
    assert client.get("/api/settings/achievements").get_json()["data"]["enabled"] is True

    assert client.post("/api/settings/dailyquest", json={"enabled": True}).status_code == 200
    assert store["DAILY_QUEST_CONFIG"]["enabled"] is True

    assert client.post("/api/settings/achievements", json={"enabled": False}).status_code == 200
    assert store["ACHIEVEMENT_CONFIG"]["enabled"] is False


def test_blind_box_and_lucky_wheel_alias_routes_share_same_storage(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "GAMES_CONFIG": {"enable": True},
        "BLIND_BOX_COST": 35,
        "BLIND_BOX_CONFIG": {"enabled": True, "cost": 35},
        "LUCKY_WHEEL_CONFIG": {"enabled": False, "cost": 18, "free_spins": 1},
    }

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    assert client.get("/api/settings/blindbox").get_json()["data"] == {"enabled": True, "cost": 35}
    assert client.get("/api/settings/blind-box").get_json()["data"] == {"enabled": True, "cost": 35}
    assert client.get("/api/settings/luckywheel").get_json()["data"] == {"enabled": False, "cost": 18, "free_spins": 1}
    assert client.get("/api/settings/lucky-wheel").get_json()["data"] == {"enabled": False, "cost": 18, "free_spins": 1}

    assert client.post("/api/settings/blind-box", json={"enabled": False, "cost": 20}).status_code == 200
    assert store["BLIND_BOX_CONFIG"] == {"enabled": False, "cost": 20}

    assert client.post("/api/settings/luckywheel", json={"enabled": True, "cost": 28, "free_spins": 3}).status_code == 200
    assert store["LUCKY_WHEEL_CONFIG"] == {"enabled": True, "cost": 28, "free_spins": 3}


def test_greeting_endpoint_uses_real_time_fields(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "GREETING_CONFIG": {
            "morning_enabled": True,
            "morning_time": "08:05",
            "afternoon_enabled": False,
            "afternoon_time": "12:35",
            "evening_enabled": True,
            "evening_time": "23:05",
        }
    }

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp = client.post("/api/settings/greeting", json={
        "morning_enabled": False,
        "morning_time": "09:10",
        "afternoon_enabled": True,
        "afternoon_time": "13:20",
        "evening_enabled": False,
        "evening_time": "22:45",
    })

    assert resp.status_code == 200
    assert store["GREETING_CONFIG"]["morning_time"] == "09:10"
    assert store["GREETING_CONFIG"]["afternoon_time"] == "13:20"
    assert store["GREETING_CONFIG"]["evening_time"] == "22:45"
    assert store["AUTO_GREETING"] is False
    assert store["AUTO_GOODNIGHT"] is False


def test_news_endpoint_uses_preferred_source_and_time_fields(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {"NEWS_BROADCAST_CONFIG": {"enabled": True, "preferred_source": "real_first", "morning_time": "09:05", "afternoon_time": "13:05", "evening_time": "20:35"}}

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp = client.post("/api/settings/news", json={
        "enabled": True,
        "preferred_source": "trendradar_first",
        "morning_time": "09:30",
        "afternoon_time": "13:40",
        "evening_time": "21:10",
    })

    assert resp.status_code == 200
    assert store["NEWS_BROADCAST_CONFIG"]["preferred_source"] == "trendradar_first"
    assert store["NEWS_BROADCAST_CONFIG"]["morning_time"] == "09:30"
    assert store["NEWS_HOUR_EVENING"] == 21


def test_mystic_endpoint_disables_news_and_saves_three_columns(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "AUTO_NEWS": True,
        "NEWS_BROADCAST_CONFIG": {"enabled": True},
        "MYSTIC_BROADCAST_CONFIG": {"enabled": False},
    }
    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)
    client = _make_client()
    resp = client.post("/api/settings/mystic", json={
        "enabled": True,
        "morning_time": "09:15",
        "morning_mode": "feng_shui",
        "afternoon_time": "13:15",
        "afternoon_mode": "tarot",
        "evening_time": "20:45",
        "evening_mode": "fortune",
    })

    assert resp.status_code == 200
    assert store["MYSTIC_BROADCAST_CONFIG"]["enabled"] is True
    assert store["MYSTIC_BROADCAST_CONFIG"]["morning_mode"] == "feng_shui"
    assert store["MYSTIC_BROADCAST_CONFIG"]["afternoon_mode"] == "tarot"
    assert store["MYSTIC_BROADCAST_CONFIG"]["evening_mode"] == "fortune"
    assert store["MYSTIC_BROADCAST_CONFIG"]["legacy_targeted_tarot_enabled"] is False
    assert store["NEWS_BROADCAST_CONFIG"]["enabled"] is False
    assert store["AUTO_NEWS"] is False


def test_antiflood_endpoint_syncs_rate_limit_and_engine_config(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "SPAM_LIMIT": {"messages_per_minute": 10, "ban_minutes": 5},
        "ANTIFLOOD_CONFIG": {"enabled": True, "window": 5, "threshold": 5, "mute_duration": 60},
    }

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp = client.post("/api/settings/antiflood", json={
        "enabled": False,
        "messages_per_minute": 18,
        "ban_minutes": 12,
        "window": 8,
        "threshold": 7,
        "mute_duration": 90,
    })

    assert resp.status_code == 200
    assert store["SPAM_LIMIT"] == {"messages_per_minute": 18, "ban_minutes": 12}
    assert store["ANTIFLOOD_CONFIG"] == {"enabled": False, "window": 8, "threshold": 7, "mute_duration": 90}


def test_cas_endpoint_supports_spamwatch_switch_and_token(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {"SPAM_WATCH_CONFIG": {"cas_enabled": False, "spamwatch_enabled": False, "spamwatch_token": ""}}

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    resp = client.post("/api/settings/cas", json={
        "cas_enabled": True,
        "spamwatch_enabled": True,
        "spamwatch_token": "abcd1234xyz9876",
    })

    assert resp.status_code == 200
    assert store["SPAM_WATCH_CONFIG"]["cas_enabled"] is True
    assert store["SPAM_WATCH_CONFIG"]["spamwatch_enabled"] is True
    assert store["SPAM_WATCH_CONFIG"]["spamwatch_token"] == "abcd1234xyz9876"


def test_null_config_blocks_can_be_saved_without_crashing(monkeypatch):
    import dashboard.api.settings_api as settings_api

    store = {
        "TIP_CONFIG": None,
        "DAILY_QUEST_CONFIG": None,
        "ACHIEVEMENT_CONFIG": None,
        "POINTS_DECAY": None,
    }

    monkeypatch.setattr(settings_api, "read_config", lambda: dict(store))

    def fake_write(cfg):
        store.clear()
        store.update(cfg)
        return True

    monkeypatch.setattr(settings_api, "write_config", fake_write)

    client = _make_client()

    assert client.post("/api/settings/tip", json={"enabled": True, "min_amount": 8}).status_code == 200
    assert store["TIP_CONFIG"] == {"enabled": True, "min_amount": 8}

    assert client.post("/api/settings/dailyquest", json={"enabled": True}).status_code == 200
    assert store["DAILY_QUEST_CONFIG"] == {"enabled": True}

    assert client.post("/api/settings/achievement", json={"enabled": True}).status_code == 200
    assert store["ACHIEVEMENT_CONFIG"] == {"enabled": True}

    assert client.post("/api/settings/pointsdecay", json={"enabled": True, "rate": 0.03, "minimum": 20}).status_code == 200
    assert store["POINTS_DECAY"] == {"enabled": True, "rate": 0.03, "minimum": 20}
