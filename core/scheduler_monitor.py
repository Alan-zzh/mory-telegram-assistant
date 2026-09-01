# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/scheduler_monitor.py  ·  APScheduler 任务监控（v5.23.0 P2-6）       ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 监听 APScheduler 事件（成功/失败/延误）                              ║
║    2. 内存指标统计 + scheduler_metrics 表持久化                            ║
║    3. 提供 get_scheduler_stats() 供 Dashboard /api/scheduler/stats 调用    ║
║                                                                            ║
║  使用：                                                                    ║
║    from core.scheduler_monitor import attach_to_scheduler                  ║
║    attach_to_scheduler(scheduler)                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("scheduler_monitor")

_CST = timezone(timedelta(hours=8))

# 全局指标存储（线程安全）
_metrics_lock = threading.Lock()
_metrics = {
    "jobs": defaultdict(dict),  # {job_id: {last_run, last_status_at, last_status, counts...}}
    "total_success": 0,
    "total_fail": 0,
    "total_miss": 0,
    "started_at": 0,
}
_metrics_hydrated = False


def load_scheduler_metrics(db) -> int:
    """从持久化表恢复跨重启指标，只补当前进程尚未观察到的任务。"""
    global _metrics_hydrated
    if db is None:
        return 0
    try:
        with db.lock:
            rows = db.conn.execute(
                "SELECT job_id, last_status, success_count, fail_count, miss_count, "
                "last_run, last_status_at, last_duration, last_error FROM scheduler_metrics"
            ).fetchall()
    except Exception as exc:
        if "no such table: scheduler_metrics" in str(exc).lower():
            # 首次运行尚无历史基线，等价于成功读取空表。
            with _metrics_lock:
                for info in _metrics["jobs"].values():
                    info["_persisted_loaded"] = True
                _metrics_hydrated = True
            return 0
        logger.debug(f"调度指标恢复跳过: {exc}")
        return 0

    restored = 0
    persisted_job_ids = {row[0] for row in rows}
    with _metrics_lock:
        for row in rows:
            job_id = row[0]
            if job_id in _metrics["jobs"]:
                current = _metrics["jobs"][job_id]
                if current.get("_persisted_loaded"):
                    continue
                # 当前状态优先，但持久累计值要作为基线合并，避免晚水合后归零。
                current["success_count"] = int(row[2] or 0) + int(current.get("success_count", 0))
                current["fail_count"] = int(row[3] or 0) + int(current.get("fail_count", 0))
                current["miss_count"] = int(row[4] or 0) + int(current.get("miss_count", 0))
                current["_persisted_loaded"] = True
                restored += 1
                continue
            _metrics["jobs"][job_id] = {
                "last_status": row[1] or "",
                "success_count": int(row[2] or 0),
                "fail_count": int(row[3] or 0),
                "miss_count": int(row[4] or 0),
                "last_run": int(row[5] or 0),
                "last_status_at": int(row[6] or 0),
                "last_duration": int(row[7] or 0),
                "last_error": row[8] or "",
                "_persisted_loaded": True,
            }
            restored += 1
        # 成功读取后，表中不存在的当前任务已确定没有历史基线。
        for job_id, info in _metrics["jobs"].items():
            if job_id not in persisted_job_ids:
                info["_persisted_loaded"] = True
        _metrics["total_success"] = sum(int(info.get("success_count", 0)) for info in _metrics["jobs"].values())
        _metrics["total_fail"] = sum(int(info.get("fail_count", 0)) for info in _metrics["jobs"].values())
        _metrics["total_miss"] = sum(int(info.get("miss_count", 0)) for info in _metrics["jobs"].values())
        _metrics_hydrated = True
    if restored:
        logger.info(f"✅ 调度指标已从数据库恢复: {restored} 个任务")
    return restored


def attach_to_scheduler(scheduler, db=None):
    """恢复跨进程指标并附加 APScheduler 事件监听器。"""
    try:
        from apscheduler.events import (
            EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
        )
    except ImportError:
        logger.warning("APScheduler 未安装，调度监控无法启动")
        return

    load_scheduler_metrics(db)
    with _metrics_lock:
        _metrics["started_at"] = int(time.time())

    def _on_job_event(event):
        """任务事件回调"""
        job_id = event.job_id
        now_ts = int(time.time())

        with _metrics_lock:
            job_info = _metrics["jobs"][job_id]
            if "_persisted_loaded" not in job_info:
                # 成功水合后的新任务没有历史基线；水合失败期间的新任务等待晚水合合并。
                job_info["_persisted_loaded"] = _metrics_hydrated

            if event.code == EVENT_JOB_EXECUTED:
                # 成功执行
                job_info["last_status"] = "success"
                job_info["success_count"] = job_info.get("success_count", 0) + 1
                _metrics["total_success"] += 1
                # 计算执行耗时（如果有 scheduled_time）
                if hasattr(event, "scheduled_time") and event.scheduled_time:
                    try:
                        scheduled_ts = event.scheduled_time.timestamp()
                        duration = now_ts - int(scheduled_ts)
                        job_info["last_duration"] = duration
                    except Exception as e:
                        logger.debug(f"计算 last_duration 失败: {e}")
                job_info["last_run"] = now_ts
                job_info["last_status_at"] = now_ts
                logger.debug(f"[Scheduler] 任务成功: {job_id}")

            elif event.code == EVENT_JOB_ERROR:
                # 执行出错
                job_info["last_status"] = "error"
                job_info["fail_count"] = job_info.get("fail_count", 0) + 1
                job_info["last_error"] = str(event.exception)[:200] if event.exception else "unknown"
                job_info["last_run"] = now_ts
                job_info["last_status_at"] = now_ts
                _metrics["total_fail"] += 1
                logger.warning(f"[Scheduler] 任务失败: {job_id} | 错误: {job_info['last_error']}")

            elif event.code == EVENT_JOB_MISSED:
                # 任务延误被丢弃
                job_info["last_status"] = "missed"
                job_info["miss_count"] = job_info.get("miss_count", 0) + 1
                job_info["last_miss"] = now_ts
                job_info["last_status_at"] = now_ts
                _metrics["total_miss"] += 1
                logger.warning(f"[Scheduler] 任务延误丢弃: {job_id}")

    # 注册监听器
    scheduler.add_listener(_on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    logger.info("✅ 调度监控已附加（监听 EXECUTED/ERROR/MISSED 事件）")


def get_scheduler_stats() -> dict:
    """获取调度器统计指标"""
    with _metrics_lock:
        jobs = {}
        for job_id, info in _metrics["jobs"].items():
            jobs[job_id] = dict(info)

        return {
            "started_at": _metrics["started_at"],
            "uptime_seconds": int(time.time()) - _metrics["started_at"] if _metrics["started_at"] else 0,
            "total_success": _metrics["total_success"],
            "total_fail": _metrics["total_fail"],
            "total_miss": _metrics["total_miss"],
            "job_count": len(jobs),
            "jobs": jobs,
        }


def get_job_list(scheduler) -> list:
    """获取调度器当前所有任务列表"""
    jobs = []
    try:
        for job in scheduler.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "name": job.name or job.id,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "未调度",
                "trigger": str(job.trigger),
                "max_instances": getattr(job, "max_instances", 1),
                "coalesce": getattr(job, "coalesce", True),
            })
    except Exception as e:
        logger.debug(f"获取任务列表失败: {e}")
    return jobs


def sync_metrics_to_db(db) -> int:
    """[v5.24.0 阶段3-D] 将内存指标批量刷盘到 scheduler_metrics 表

    采用 REPLACE INTO 单次批量更新，避免高频实时写入给 DB 增加负担。
    由定时任务每 5 分钟调用一次，服务异常重启最多丢失 5 分钟统计数据。

    Args:
        db: DB 实例

    Returns:
        写入的 job 记录数
    """
    try:
        # 未恢复历史基线前禁止 REPLACE 覆盖累计计数；数据库恢复后再落盘。
        load_scheduler_metrics(db)
        with _metrics_lock:
            if not _metrics_hydrated:
                raise RuntimeError("scheduler_metrics 持久化水合不可用，拒绝覆盖历史计数")
            jobs_snapshot = {jid: dict(info) for jid, info in _metrics["jobs"].items()}
            totals = {
                "total_success": _metrics["total_success"],
                "total_fail": _metrics["total_fail"],
                "total_miss": _metrics["total_miss"],
            }

        if not jobs_snapshot:
            return 0

        with db.lock:
            c = db.conn.cursor()
            now_ts = int(time.time())
            for job_id, info in jobs_snapshot.items():
                c.execute("""
                    REPLACE INTO scheduler_metrics
                    (job_id, last_status, success_count, fail_count, miss_count,
                     last_run, last_status_at, last_duration, last_error, synced_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    job_id,
                    info.get("last_status", ""),
                    int(info.get("success_count") or 0),
                    int(info.get("fail_count") or 0),
                    int(info.get("miss_count") or 0),
                    int(info.get("last_run") or 0),
                    int(info.get("last_status_at") or 0),
                    int(info.get("last_duration") or 0),
                    info.get("last_error", "")[:500],
                    now_ts,
                ))
            db.conn.commit()
        logger.debug(f"[Scheduler] 指标落盘完成: {len(jobs_snapshot)} 个任务")
        return len(jobs_snapshot)
    except Exception as e:
        logger.error(f"调度指标落盘失败: {e}")
        raise


# 【v5.31.1 第四层防御】关键用户可感知任务的预期执行时间表
# 格式：job_id 前缀 → spec dict
#   - deadline 模式（每日时间点）：{deadline_hour, deadline_minute, desc}
#       监控逻辑：当前时间 > (deadline + 30min 宽限)，且该 job 今天未成功执行 → CRITICAL 告警
#   - interval 模式（高频周期）：{interval_minutes, desc}
#       监控逻辑：上次成功执行距今 > interval_minutes * 2 → CRITICAL 告警
# 注：broadcast_* 和 greeting_* 的具体时间由 config.json 决定，这里只设一个保守的"当日必须执行"截止时间
_CRITICAL_JOBS = {
    # 生产唯一主动内容栏目：实际时间从 MYSTIC_BROADCAST_CONFIG 读取；
    # 此处为默认时间 + 1 小时宽限，动态配置会在 check 时覆盖。
    "mystic_morning": {"deadline_hour": 10, "deadline_minute": 5, "desc": "早间今日黄历(09:05)"},
    "mystic_afternoon": {"deadline_hour": 14, "deadline_minute": 5, "desc": "午间三张塔罗(13:05)"},
    "mystic_evening": {"deadline_hour": 21, "deadline_minute": 35, "desc": "晚间易经一卦(20:35)"},
    # 问候：早安 8:05 / 午安 12:35 / 晚安 23:05 — 所有问候最晚 23:35 前应执行至少一次（如果开启）
    "greeting_morning": {"deadline_hour": 9, "deadline_minute": 0, "desc": "早安问候(8:05)"},
    "greeting_afternoon": {"deadline_hour": 13, "deadline_minute": 30, "desc": "午安问候(12:35)"},
    "greeting_evening": {"deadline_hour": 23, "deadline_minute": 40, "desc": "晚安问候(23:05)"},
    # 播报：早 10:00 / 午 14:30 / 晚 19:00 / 夜 22:30 — 所有播报最晚 23:00 前应执行
    # 【v5.31.2 hotfix P1-1】job_id 必须与 config.json.example SCHEDULED_BROADCASTS.id 一致：
    #   bc_id=morning_nudge / afternoon_tease / evening_warm / night_hook
    #   实际注册的 job_id = "broadcast_" + bc_id（v5.38.69 前由 auto_tasks 注册，现见
    #   tasks/broadcast/greeting_task.py 与 modules/scheduled_broadcast 的统一调度链）
    "broadcast_morning_nudge": {"deadline_hour": 11, "deadline_minute": 0, "desc": "晨间播报(10:00)"},
    "broadcast_afternoon_tease": {"deadline_hour": 15, "deadline_minute": 30, "desc": "下午茶播报(14:30)"},
    "broadcast_evening_warm": {"deadline_hour": 20, "deadline_minute": 0, "desc": "傍晚播报(19:00)"},
    "broadcast_night_hook": {"deadline_hour": 23, "deadline_minute": 30, "desc": "夜间播报(22:30)"},
    # 【v5.31.2 P1-Task07】业务关键任务
    # 【v5.31.2 审计复扫修复】监控模式与实际调度对齐（行号指向 v5.38.69 已拆除的 auto_tasks.py，
    #   仅作历史依据注记；现行调度真相以 tasks/ 各任务 schedule() 为准）：
    #   - cart_recovery: 每5分钟（cron minute="*/5"），原 deadline 03:00 会导致监控盲区 13h
    #   - backup: 每小时:15，原 deadline 04:00 监控了错误任务
    #   - daily_backup: 每日03:00，原 _CRITICAL_JOBS 未监控此任务
    #   - health_check: 每日3次（10/16/22点），原 interval=5 会导致每天误报
    "cart_recovery": {"interval_minutes": 5, "desc": "购物车挽回(每5分钟)"},
    "backup": {"interval_minutes": 60, "desc": "每小时备份(:15)"},
    "daily_backup": {"deadline_hour": 4, "deadline_minute": 0, "desc": "每日数据库备份(03:00)"},
    "health_check": {"deadline_hour": 23, "deadline_minute": 50, "desc": "健康检查(每日10/16/22点)"},
    # 【v5.31.2 hotfix P1-2】删除不存在的 job_id (ad_cleanup/write_queue_flush/llm_cost_flush)，
    #   这三个任务在旧 auto_tasks.py 中没有对应的 _job_ 函数和 add_job 调用，
    #   保留会导致每天 false alarm。
    # 【v5.31.2 hotfix P1-2】补加真实存在的 interval 模式任务：
    #   - sync_scheduler_metrics (每5分钟刷调度指标到 DB)
    #   - flush_alert_summary (每5分钟刷告警摘要)
    "sync_scheduler_metrics": {"interval_minutes": 5, "desc": "调度指标刷盘(每5分钟)"},
    "flush_alert_summary": {"interval_minutes": 5, "desc": "告警摘要刷盘(每5分钟)"},
}

# 已告警的 job（避免每 30 分钟重复告警，每天重置一次）
# 【v5.31.2 P1-Task08】持久化到 system_states 表（key="alerted_jobs"），重启不丢、告警风暴不复发
_alerted_jobs = set()
_alerted_date = None
_ALERTED_JOBS_DB_KEY = "alerted_jobs"


def _load_alerted_jobs_from_db(db) -> None:
    """【v5.31.2 P1-Task08】从 system_states 表加载 _alerted_jobs 持久化状态

    仅当 DB 中存储的日期等于今天时才合并到内存；跨天状态视为过期丢弃。
    DB 异常不影响监控主流程。

    存储格式：JSON {"date": "YYYY-MM-DD", "jobs": ["job_id1", ...]}
    """
    global _alerted_jobs, _alerted_date
    if db is None:
        return
    try:
        raw = db.get_system_state(_ALERTED_JOBS_DB_KEY)
        if not raw:
            return
        import json
        data = json.loads(raw)
        stored_date = data.get("date")
        stored_jobs = data.get("jobs", [])
        if stored_date == _alerted_date and isinstance(stored_jobs, list):
            _alerted_jobs |= set(stored_jobs)
            logger.debug(f"[Scheduler] 从 DB 恢复 _alerted_jobs: {len(stored_jobs)} 项 (date={stored_date})")
    except Exception as e:
        logger.debug(f"[Scheduler] 加载 _alerted_jobs 持久化状态失败: {e}")


def _save_alerted_jobs_to_db(db) -> None:
    """【v5.31.2 P1-Task08】将 _alerted_jobs 持久化到 system_states 表

    保存当前 _alerted_jobs + _alerted_date，重启后可恢复。
    DB 异常不影响监控主流程。
    """
    global _alerted_jobs, _alerted_date
    if db is None:
        return
    try:
        import json
        payload = {
            "date": _alerted_date,
            "jobs": sorted(list(_alerted_jobs)),
        }
        db.set_system_state(_ALERTED_JOBS_DB_KEY, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"[Scheduler] 保存 _alerted_jobs 持久化状态失败: {e}")


def _is_job_disabled_by_config(job_id: str, config) -> bool:
    """【v5.31.2 审计复扫修复 WARN-1】根据 config 判断该 job 对应的功能是否被禁用

    避免对管理员主动关闭的功能（如问候/播报）误报"未执行"告警。

    判断规则（与 tasks/support/critical_tasks._is_greeting_enabled 保持一致）：
    - greeting_morning  → GREETING_CONFIG.morning_enabled，回退 AUTO_GREETING
    - greeting_afternoon→ GREETING_CONFIG.afternoon_enabled，回退 AUTO_GREETING
    - greeting_evening  → GREETING_CONFIG.evening_enabled，回退 AUTO_GOODNIGHT / AUTO_GREETING
    - broadcast_*       → SCHEDULED_BROADCASTS 中对应 bc_id 的 enabled 字段
    - mystic_*          → MYSTIC_BROADCAST_CONFIG.enabled
    - cart_recovery     → CART_RECOVERY_CONFIG.enabled
    - daily_backup      → DAILY_BACKUP_ENABLED
    - 其他基础设施 job  → 永不禁用

    Args:
        job_id: 任务 ID（如 greeting_morning / broadcast_morning_nudge）
        config: 配置 dict（None 视为所有功能启用，不阻塞监控）

    Returns:
        True 表示该功能被禁用，应跳过监控
    """
    if config is None:
        return False  # 调用方未传 config，向后兼容（不跳过任何任务）
    try:
        if job_id.startswith("greeting_"):
            # 与 tasks/support/critical_tasks._is_greeting_enabled 逻辑一致
            cfg = config.get("GREETING_CONFIG", {}) if isinstance(config, dict) else {}
            period = job_id[len("greeting_"):]  # morning / afternoon / evening
            key_map = {
                "morning": "morning_enabled",
                "afternoon": "afternoon_enabled",
                "evening": "evening_enabled",
            }
            key = key_map.get(period)
            if key and key in cfg:
                return not bool(cfg.get(key))
            # 回退到 AUTO_GREETING / AUTO_GOODNIGHT
            if period == "evening":
                return not bool(config.get("AUTO_GOODNIGHT", config.get("AUTO_GREETING", False)))
            return not bool(config.get("AUTO_GREETING", False))
        if job_id.startswith("broadcast_"):
            bc_id = job_id[len("broadcast_"):]
            broadcasts = config.get("SCHEDULED_BROADCASTS", []) or []
            if not isinstance(broadcasts, list):
                return False
            for bc in broadcasts:
                if isinstance(bc, dict) and bc.get("id") == bc_id:
                    return not bool(bc.get("enabled", True))
            # 配置中找不到该 bc_id，视为禁用（避免对已删除的播报任务误告警）
            return True
        if job_id.startswith("mystic_"):
            mystic_cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) if isinstance(config, dict) else {}
            return not bool(isinstance(mystic_cfg, dict) and mystic_cfg.get("enabled", False))
        if job_id == "cart_recovery":
            cart_cfg = config.get("CART_RECOVERY_CONFIG", {}) if isinstance(config, dict) else {}
            return not bool(isinstance(cart_cfg, dict) and cart_cfg.get("enabled", False))
        if job_id == "daily_backup":
            return not bool(config.get("DAILY_BACKUP_ENABLED", False))
        # 无独立开关的基础设施任务永不通过 config 跳过。
        return False
    except Exception:
        return False


def check_critical_jobs_health(scheduler=None, config=None, db=None):
    """【v5.31.1 第四层防御】检查关键用户可感知任务是否按时执行

    监控逻辑：
    1. 遍历 _CRITICAL_JOBS 中定义的关键任务
    2. 【WARN-1 修复】跳过被 config 禁用的功能对应任务（greeting_*/broadcast_*）
    3. deadline 模式：当前时间已超过截止时间（含宽限），且该 job 今天未成功执行 → 告警
    4. interval 模式：上次成功执行距今超过 interval_minutes * 2 → 告警
    5. 用 _alerted_jobs 防重复告警（每天重置）
    6. 【P1-Task08】_alerted_jobs 持久化到 system_states 表，重启不丢、告警风暴不复发

    Args:
        scheduler: APScheduler 实例（可选，用于获取 job 的 next_run_time）
        config: 配置 dict（可选，用于检查开关状态，跳过被禁用功能的监控）
        db: DB 实例（可选，用于 _alerted_jobs 持久化到 system_states 表）
    """
    global _alerted_jobs, _alerted_date
    now = datetime.now(_CST)
    today_str = now.strftime("%Y-%m-%d")
    now_ts = int(now.timestamp())

    # 每天重置告警状态
    if _alerted_date != today_str:
        _alerted_jobs = set()
        _alerted_date = today_str
        # 【P1-Task08】跨天重置后，从 DB 恢复今天的告警状态（重启场景：内存清零但 DB 仍在）
        _load_alerted_jobs_from_db(db)

    # attach 阶段若数据库短暂不可用，健康检查仍可补载持久证据。
    load_scheduler_metrics(db)
    with _metrics_lock:
        if db is not None and not _metrics_hydrated:
            raise RuntimeError("scheduler_metrics 不可用，无法判定关键任务健康状态")
        jobs_snapshot = {jid: dict(info) for jid, info in _metrics["jobs"].items()}

    alerts = []
    all_ok = True

    # 广播任务监控项动态生成：SCHEDULED_BROADCASTS 的 id 随管理员配置变化，
    # 硬编码 _CRITICAL_JOBS 里的 broadcast_* 会与生产 id 错位造成监控盲区。
    # job_id = "broadcast_" + bc_id（历史：v5.38.69 前 auto_tasks._register_scheduled_broadcasts；
    # 现行注册链见 tasks/maintenance/scheduled_broadcast_task.py）
    jobs = dict(_CRITICAL_JOBS)
    if isinstance(config, dict):
        mystic_cfg = config.get("MYSTIC_BROADCAST_CONFIG", {}) or {}
        if isinstance(mystic_cfg, dict) and mystic_cfg.get("enabled", False):
            mystic_specs = (
                ("morning", "mystic_morning", "早间今日黄历"),
                ("afternoon", "mystic_afternoon", "午间三张塔罗"),
                ("evening", "mystic_evening", "晚间易经一卦"),
            )
            for period, job_id, desc in mystic_specs:
                raw_time = str(mystic_cfg.get(f"{period}_time", "") or "")
                try:
                    hour_text, minute_text = raw_time.split(":", 1)
                    hour = int(hour_text)
                    minute = int(minute_text)
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        raise ValueError(raw_time)
                except (TypeError, ValueError):
                    continue
                deadline_total = hour * 60 + minute + 60
                jobs[job_id] = {
                    "deadline_hour": (deadline_total // 60) % 24,
                    "deadline_minute": deadline_total % 60,
                    "desc": f"{desc}({raw_time})",
                }
        broadcast_list = config.get("SCHEDULED_BROADCASTS", []) or []
        if isinstance(broadcast_list, list):
            for bc in broadcast_list:
                if not isinstance(bc, dict):
                    continue
                bc_id = str(bc.get("id", "") or "").strip()
                if not bc_id or not bool(bc.get("enabled", True)):
                    continue
                try:
                    b_hour = int(bc.get("hour", 0) or 0)
                    b_min = int(bc.get("minute", 0) or 0)
                except (TypeError, ValueError):
                    continue
                job_broadcast_id = f"broadcast_{bc_id}"
                # 截止时间 = 播报时间 + 1 小时宽限
                dl_hour = (b_hour + 1) % 24
                jobs[job_broadcast_id] = {
                    "deadline_hour": dl_hour,
                    "deadline_minute": b_min,
                    "desc": f"定点播报({bc_id} {b_hour:02d}:{b_min:02d})",
                }

    for job_id, spec in jobs.items():
        if job_id in _alerted_jobs:
            continue
        # 【WARN-1 修复】跳过被 config 禁用的功能对应任务，避免对主动关闭的功能误告警
        if _is_job_disabled_by_config(job_id, config):
            continue

        # 【P1-Task07】interval 模式：高频任务基于时间间隔判断
        # 上次成功执行距今超过 interval_minutes * 2 即告警
        if "interval_minutes" in spec:
            interval_min = spec["interval_minutes"]
            threshold_sec = interval_min * 2 * 60
            job_info = jobs_snapshot.get(job_id, {})
            last_run = job_info.get("last_run", 0)
            last_status = job_info.get("last_status", "")

            if last_run > 0 and last_status == "success" and (now_ts - last_run) <= threshold_sec:
                continue  # 最近一次执行在阈值内，正常

            gap_desc = f"距上次执行{(now_ts - last_run) // 60}分钟" if last_run > 0 else "从未执行"
            alerts.append(
                f"🚨 关键任务未执行: {spec['desc']} (job_id={job_id}, interval={interval_min}min, {gap_desc}, last_status={last_status})"
            )
            _alerted_jobs.add(job_id)
            all_ok = False
            continue

        # deadline 模式（原逻辑）：基于每日时间点判断
        deadline = now.replace(hour=spec["deadline_hour"], minute=spec["deadline_minute"], second=0, microsecond=0)
        if now < deadline:
            continue  # 还没到截止时间，不检查

        # 检查该 job 今天是否成功执行过
        job_info = jobs_snapshot.get(job_id, {})
        last_run = job_info.get("last_run", 0)
        last_status = job_info.get("last_status", "")

        if last_run > 0:
            last_run_dt = datetime.fromtimestamp(last_run, tz=_CST)
            if last_run_dt.strftime("%Y-%m-%d") == today_str and last_status == "success":
                continue  # 今天已成功执行，正常

        # 没执行过或执行失败 → 告警
        alerts.append(f"🚨 关键任务未执行: {spec['desc']} (job_id={job_id}, 截止={spec['deadline_hour']:02d}:{spec['deadline_minute']:02d}, last_status={last_status})")
        _alerted_jobs.add(job_id)
        all_ok = False

    if alerts:
        for a in alerts:
            logger.critical(a)
        # 【P1-Task08】告警后持久化 _alerted_jobs，重启不丢、告警风暴不复发
        _save_alerted_jobs_to_db(db)
    elif now.hour >= 0 and now.minute >= 0:  # 每次检查都记录正常状态（debug 级别）
        logger.debug("✅ 关键任务健康检查通过：所有到点任务均已执行")

    return all_ok
