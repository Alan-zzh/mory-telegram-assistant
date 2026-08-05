# -*- coding: utf-8 -*-
"""深夜问候（night）档位调度测试。

覆盖 v5.38.26 tasks/broadcast/greeting_task.py 的 night 档：
- GREETING_CONFIG.night_enabled=false（或缺失）→ 只有 3 档（早/午/晚）
- night_enabled=true → 额外含 greeting_night 档，时间读 night_time（默认 22:30）
- 用构造的 fake rm.config 测（参照 test_task_outcome_recovery.py 的 SimpleNamespace 方式）
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tasks.broadcast.greeting_task import GreetingTask

BASE_JOB_IDS = ["greeting_morning", "greeting_afternoon", "greeting_evening"]


def _build_task(config: dict) -> GreetingTask:
    """用构造的 fake rm.config 创建 GreetingTask（schedule() 只读 self.rm.config）。"""
    rm = SimpleNamespace(config=config)
    return GreetingTask(rm)


def test_schedule_three_jobs_when_night_disabled():
    """night_enabled=false → 只有早/午/晚 3 档，无 greeting_night。"""
    task = _build_task({"GREETING_CONFIG": {"night_enabled": False}})
    jobs = task.schedule()
    job_ids = [j["job_id"] for j in jobs]
    assert job_ids == BASE_JOB_IDS, f"期望 3 档 {BASE_JOB_IDS}，实际 {job_ids}"
    # 每档必须是 cron 触发器且带 period 参数
    for job in jobs:
        assert job["trigger"] == "cron"
        assert job["params"]["period"] in ("morning", "afternoon", "evening")


def test_schedule_three_jobs_when_config_missing():
    """GREETING_CONFIG 缺失（含空配置）→ night 默认关闭，仍只有 3 档。"""
    for config in ({}, {"GREETING_CONFIG": {}}):
        task = _build_task(config)
        job_ids = [j["job_id"] for j in task.schedule()]
        assert job_ids == BASE_JOB_IDS, f"config={config} 时实际 {job_ids}"


def test_schedule_includes_night_job_when_enabled():
    """night_enabled=true → 含 greeting_night 档，时间读 night_time，period=night。"""
    task = _build_task({"GREETING_CONFIG": {"night_enabled": True, "night_time": "23:30"}})
    jobs = task.schedule()
    job_ids = [j["job_id"] for j in jobs]
    assert job_ids == BASE_JOB_IDS + ["greeting_night"], f"实际 {job_ids}"
    night_job = next(j for j in jobs if j["job_id"] == "greeting_night")
    assert night_job["params"] == {"period": "night"}
    assert (night_job["hour"], night_job["minute"]) == (23, 30)


def test_schedule_night_uses_default_time_when_not_configured():
    """night_enabled=true 且未配 night_time → 用默认 22:30。"""
    task = _build_task({"GREETING_CONFIG": {"night_enabled": True}})
    night_job = next(j for j in task.schedule() if j["job_id"] == "greeting_night")
    assert (night_job["hour"], night_job["minute"]) == (22, 30)
