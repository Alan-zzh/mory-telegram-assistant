# -*- coding: utf-8 -*-
"""问候调度：schedule() 与 execute() 统一按 enabled 过滤，避免僵尸 job。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tasks.broadcast.greeting_task import GreetingTask

BASE_JOB_IDS = ["greeting_morning", "greeting_afternoon", "greeting_evening"]


def _build_task(config: dict) -> GreetingTask:
    rm = SimpleNamespace(config=config)
    return GreetingTask(rm)


def test_schedule_empty_when_all_disabled():
    """全部关闭时 schedule 返回空，避免注册后 execute 跳过的假死。"""
    task = _build_task({"GREETING_CONFIG": {
        "morning_enabled": False,
        "afternoon_enabled": False,
        "evening_enabled": False,
        "night_enabled": False,
    }})
    assert task.schedule() == []


def test_schedule_three_jobs_when_auto_greeting_on():
    """AUTO_GREETING=true 且未显式关各档 → 早/午/晚 3 档。"""
    task = _build_task({"AUTO_GREETING": True, "GREETING_CONFIG": {"night_enabled": False}})
    jobs = task.schedule()
    job_ids = [j["job_id"] for j in jobs]
    assert job_ids == BASE_JOB_IDS, f"期望 3 档 {BASE_JOB_IDS}，实际 {job_ids}"
    for job in jobs:
        assert job["trigger"] == "cron"
        assert job["params"]["period"] in ("morning", "afternoon", "evening")


def test_schedule_empty_when_config_missing():
    """配置缺失时默认关闭，不注册任何问候 job。"""
    for config in ({}, {"GREETING_CONFIG": {}}):
        task = _build_task(config)
        assert task.schedule() == [], f"config={config} 时实际 {[j['job_id'] for j in task.schedule()]}"


def test_schedule_includes_night_job_when_enabled():
    """各档 + night 全开 → 4 档，night 时间读 night_time。"""
    task = _build_task({
        "AUTO_GREETING": True,
        "GREETING_CONFIG": {
            "morning_enabled": True,
            "afternoon_enabled": True,
            "evening_enabled": True,
            "night_enabled": True,
            "night_time": "23:30",
        },
    })
    jobs = task.schedule()
    job_ids = [j["job_id"] for j in jobs]
    assert job_ids == BASE_JOB_IDS + ["greeting_night"], f"实际 {job_ids}"
    night_job = next(j for j in jobs if j["job_id"] == "greeting_night")
    assert night_job["params"] == {"period": "night"}
    assert (night_job["hour"], night_job["minute"]) == (23, 30)


def test_schedule_night_uses_default_time_when_not_configured():
    """night_enabled=true 且未配 night_time → 用默认 22:30。"""
    task = _build_task({
        "AUTO_GREETING": True,
        "GREETING_CONFIG": {
            "morning_enabled": True,
            "afternoon_enabled": True,
            "evening_enabled": True,
            "night_enabled": True,
        },
    })
    night_job = next(j for j in task.schedule() if j["job_id"] == "greeting_night")
    assert (night_job["hour"], night_job["minute"]) == (22, 30)


def test_schedule_only_night_when_only_night_enabled():
    """仅 night 开启时只注册 night job。"""
    task = _build_task({"GREETING_CONFIG": {"night_enabled": True}})
    job_ids = [j["job_id"] for j in task.schedule()]
    assert job_ids == ["greeting_night"]
