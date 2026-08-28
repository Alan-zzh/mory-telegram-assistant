from scripts.attribution_offline_replay import (
    compare_models,
    main,
    replay_last_touch,
    replay_time_decay,
)


def _event(uid, event, ts, source="", campaign_id=""):
    return {
        "uid": uid,
        "event": event,
        "ts": ts,
        "source": source,
        "campaign_id": campaign_id,
    }


def test_last_touch_uses_latest_eligible_touch_and_respects_window():
    events = [
        _event(1, "interested", 1_000, source="group"),
        _event(1, "carted", 1_100, campaign_id="campaign-b"),
        _event(1, "converted", 1_200),
        _event(2, "interested", 1_000, source="expired"),
        _event(2, "converted", 10_000),
    ]

    result = replay_last_touch(events, window_hours=1)

    assert result["total_conversions"] == 2
    assert result["channel_attributions"] == {"campaign-b": 1.0, "unknown": 1.0}
    assert result["per_user"][1]["event"] == "carted"


def test_time_decay_prefers_recent_touch_and_compare_models_is_finite():
    events = [
        _event(7, "interested", 1_000, campaign_id="old"),
        _event(7, "carted", 4_500, campaign_id="recent"),
        _event(7, "converted", 4_600),
    ]

    last_touch = replay_last_touch(events, window_hours=2)
    time_decay = replay_time_decay(events, half_life_days=1 / 24, window_hours=2)
    comparison = compare_models(last_touch, time_decay)

    assert time_decay["per_user"][7]["primary_channel"] == "recent"
    assert comparison["last_touch_total"] == 1
    assert comparison["time_decay_total"] == 1
    assert 0.0 <= comparison["js_divergence"] <= 1.0


def test_replay_without_touch_is_explicit_unknown_evidence():
    events = [_event(9, "converted", 5_000)]

    assert replay_last_touch(events)["channel_attributions"] == {"unknown": 1.0}
    assert replay_time_decay(events)["channel_attributions"] == {"unknown": 1.0}


def test_cli_without_data_returns_evidence_gap(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        ["attribution_offline_replay.py", "--db", str(tmp_path / "missing.db")],
    )

    assert main() == 2
