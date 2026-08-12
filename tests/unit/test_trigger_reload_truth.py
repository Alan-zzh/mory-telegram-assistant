"""场景触发器热重载与配置 fallback 回归测试。"""

from types import SimpleNamespace
import time

from modules.triggers.base import refresh_trigger_jobs
from modules.triggers.cold_group import ColdGroupTrigger
from modules.triggers.night_hint import NightHintTrigger


class _Scheduler:
    def __init__(self):
        self.jobs = {}

    def add_job(self, func, **kwargs):
        job_id = kwargs["id"]
        if job_id in self.jobs and not kwargs.get("replace_existing"):
            raise RuntimeError("duplicate job")
        self.jobs[job_id] = {"func": func, **kwargs}

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]


def test_trigger_register_removes_existing_job_when_disabled():
    scheduler = _Scheduler()
    scheduler.jobs[ColdGroupTrigger.job_id] = {"stale": True}
    rm = SimpleNamespace(config={"COLD_GROUP_TRIGGER_ENABLED": False})

    ColdGroupTrigger().register(scheduler, rm)

    assert ColdGroupTrigger.job_id not in scheduler.jobs


def test_trigger_register_replaces_existing_job_when_enabled():
    scheduler = _Scheduler()
    scheduler.jobs[ColdGroupTrigger.job_id] = {"stale": True}
    rm = SimpleNamespace(config={"COLD_GROUP_TRIGGER_ENABLED": True})

    ColdGroupTrigger().register(scheduler, rm)

    assert scheduler.jobs[ColdGroupTrigger.job_id]["replace_existing"] is True
    assert scheduler.jobs[ColdGroupTrigger.job_id]["minutes"] == 5


def test_refresh_trigger_jobs_is_idempotent_for_true_to_false_reload():
    scheduler = _Scheduler()
    rm = SimpleNamespace(config={
        "COLD_GROUP_TRIGGER_ENABLED": True,
        "NIGHT_HINT_TRIGGER_ENABLED": True,
    })

    refresh_trigger_jobs(scheduler, rm, (ColdGroupTrigger, NightHintTrigger))
    assert set(scheduler.jobs) == {"cold_group_breaker", "night_private_hint"}

    rm.config.update({
        "COLD_GROUP_TRIGGER_ENABLED": False,
        "NIGHT_HINT_TRIGGER_ENABLED": False,
    })
    refresh_trigger_jobs(scheduler, rm, (ColdGroupTrigger, NightHintTrigger))
    assert scheduler.jobs == {}


def test_cold_group_fallbacks_match_example_and_limit_one_message():
    sent = []

    class _Conn:
        def execute(self, *_args):
            class _Rows:
                def fetchall(self):
                    return [(1, int(time.time()) - 3600), (2, int(time.time()) - 3600)]

                def fetchone(self):
                    return None

            return _Rows()

    class _AI:
        def ask(self, *_args, **_kwargs):
            return "冷场了，谁来接一句？"

    class _Bot:
        def send_message(self, chat_id, reply):
            sent.append((chat_id, reply))

    rm = SimpleNamespace(
        config={"COLD_GROUP_TRIGGER_ENABLED": True},
        db=SimpleNamespace(conn=_Conn()),
        ai=_AI(),
        bot=_Bot(),
    )
    trigger = ColdGroupTrigger()
    assert trigger.should_fire(rm) is True
    trigger.execute(rm)

    # fallback max_per_run=1 (config.json.example), not the old value 3.
    assert len(sent) == 1


def test_night_hint_fallback_limits_one_user():
    sent = []

    class _AI:
        def ask(self, *_args, **_kwargs):
            return "夜深了，愿你今晚睡得安稳。"

    class _Bot:
        def send_message(self, uid, reply):
            sent.append((uid, reply))

    class _DB:
        def get_user_persona_profile(self, _uid):
            return {}

        class _Conn:
            def execute(self, *_args):
                class _Rows:
                    def fetchone(self):
                        return None

                return _Rows()

        conn = _Conn()

    rm = SimpleNamespace(
        config={
            "NIGHT_HINT_TRIGGER_ENABLED": True,
            "NIGHT_HINT_NEUTRAL_REMINDER_ENABLED": True,
        },
        db=_DB(),
        ai=_AI(),
        bot=_Bot(),
    )
    trigger = NightHintTrigger()
    trigger._pending_users = [1, 2]
    trigger.execute(rm)

    # fallback max_per_run=1 (config.json.example), not the old value 2.
    assert len(sent) == 1


def test_dashboard_scene_bool_parser_does_not_treat_string_false_as_true():
    from dashboard.api.config_api import (
        ALLOWED_CONFIG_FIELDS,
        _parse_scene_bool,
    )

    assert _parse_scene_bool("false") is False
    assert _parse_scene_bool("true") is True
    assert _parse_scene_bool("unexpected") is None
    assert "NIGHT_HINT_NEUTRAL_REMINDER_ENABLED" in ALLOWED_CONFIG_FIELDS
