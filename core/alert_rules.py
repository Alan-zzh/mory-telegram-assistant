# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/alert_rules.py  ·  告警规则与阈值定义（v5.24.0 阶段1-B）           ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 定义各业务指标的告警检查函数（返回 None 正常 / dict 异常）          ║
║    2. run_health_check() 遍历所有规则，触发则调 send_alert                ║
║                                                                            ║
║  规则清单：                                                                ║
║    - WriteQueue 积压：qsize > 50 WARNING，> 150 CRITICAL                  ║
║    - AI 穿帮触发：sanitize_retry 触发 → WARNING                            ║
║    - 调度任务失败：scheduler_monitor 失败 → CRITICAL                       ║
║    - Dashboard 重启次数：NRestarts > 3 → WARNING                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import traceback
from typing import Optional, Callable

from core.logging_util import get_logger
from core.alert_bot import send_alert

logger = get_logger("alert_rules")

# 阈值常量
# 调度失败告警：只看最近 _SCHED_FAIL_WINDOW 秒内主动失败的任务
# （v5.38.14 修复：原 total_fail 累计值不重置，导致任一历史失败永久误告警）
_SCHED_FAIL_WINDOW = 1800       # 30 分钟窗口
_SCHED_FAIL_ACTIVE_THRESHOLD = 1  # 窗口内主动失败任务数 >= 此值才告警
_DASH_RESTART_THRESHOLD = 3  # Dashboard 重启次数告警阈值


def check_scheduler_failures() -> Optional[dict]:
    """
    检查调度任务近期失败情况。
    v5.38.14 修复：原实现使用累计 total_fail（启动至今不重置），
    导致任一历史失败触发永久误告警。现改为只看最近 _SCHED_FAIL_WINDOW
    秒内 last_status==error 的任务；任务恢复成功后告警自动解除。
    """
    try:
        from core.scheduler_monitor import get_scheduler_stats
        stats = get_scheduler_stats()
        jobs = stats.get("jobs", {})
        now = int(time.time())
        # 收集窗口内主动失败的任务（last_status==error 且 last_run 在窗口内）
        active_failed = {}
        for jid, info in jobs.items():
            if info.get("last_status") != "error":
                continue
            last_run = int(info.get("last_run", 0) or 0)
            if last_run and (now - last_run) <= _SCHED_FAIL_WINDOW:
                active_failed[jid] = info

        if len(active_failed) >= _SCHED_FAIL_ACTIVE_THRESHOLD:
            # 摘要：任务名 + 失败次数 + 最近错误 + 距今秒数
            summary = []
            for jid, info in list(active_failed.items())[:5]:
                ago = now - int(info.get("last_run", 0) or 0)
                summary.append(f"{jid}(失败{info.get('fail_count',0)}次/{ago}s前)")
            return {
                "level": "CRITICAL",
                "title": "调度任务失败告警",
                "message": (
                    f"近{_SCHED_FAIL_WINDOW//60}分钟内有 {len(active_failed)} 个任务主动失败: "
                    + "; ".join(summary)
                ),
                "context": {
                    "active_failed_count": len(active_failed),
                    "window_seconds": _SCHED_FAIL_WINDOW,
                    "total_fail_cumulative": stats.get("total_fail", 0),
                    "total_miss": stats.get("total_miss", 0),
                    "failed_jobs": {
                        jid: {
                            "fail_count": info.get("fail_count", 0),
                            "last_error": info.get("last_error", ""),
                            "last_run_ago_seconds": now - int(info.get("last_run", 0) or 0),
                        } for jid, info in active_failed.items()
                    },
                },
            }
    except Exception as e:
        logger.error(f"[check_scheduler_failures 异常] {type(e).__name__}: {e}")
    return None


def check_ai_leak_retry(context: dict) -> Optional[dict]:
    """
    检查 AI 穿帮触发（由调用方传入上下文）。
    context 应包含 triggered=True 及原文片段。
    """
    try:
        if not context or not context.get("triggered"):
            return None
        return {
            "level": "WARNING",
            "title": "AI 穿帮过滤触发",
            "message": f"AI 输出触发 sanitize_retry，已降温度重试。原文片段: {str(context.get('text', ''))[:100]}",
            "context": context,
        }
    except Exception as e:
        logger.error(f"[check_ai_leak_retry 异常] {type(e).__name__}: {e}")
    return None


def check_dashboard_restarts() -> Optional[dict]:
    """
    检查 Dashboard 重启次数（NRestarts）。
    通过 systemctl status 读取 NRestarts 字段。
    """
    try:
        import subprocess
        # 仅在 Linux 上检测，Windows 开发环境跳过
        import sys
        if not sys.platform.startswith("linux"):
            return None
        result = subprocess.run(
            ["systemctl", "show", "mory-dashboard", "-p", "NRestarts", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        n_restarts = int(result.stdout.strip() or "0")
        if n_restarts > _DASH_RESTART_THRESHOLD:
            return {
                "level": "WARNING",
                "title": "Dashboard 频繁重启",
                "message": f"mory-dashboard 服务重启次数 {n_restarts}（阈值 {_DASH_RESTART_THRESHOLD}），可能存在崩溃循环",
                "context": {"n_restarts": n_restarts},
            }
    except Exception as e:
        # 【v5.31.2 修复】dashboard 重启监控失效应告警
        logger.warning(f"[check_dashboard_restarts 跳过] {type(e).__name__}: {e}")
    return None


def check_anomaly_metrics() -> Optional[dict]:
    """
    检查异常检测器各指标是否触发 Z-Score 异常。
    遍历所有已注册指标，任一 is_anomaly=True → WARNING。
    """
    try:
        from core.anomaly_detector import get_anomaly_detector
        detector = get_anomaly_detector()
        anomalies = detector.detect_all()
        if not anomalies:
            return None
        # 取 Z-Score 最高的作为主告警
        worst = max(anomalies, key=lambda r: r["zscore"])
        other_names = [a["metric_name"] for a in anomalies if a["metric_name"] != worst["metric_name"]]
        message = worst["message"]
        if other_names:
            message += f"；另有 {len(other_names)} 个指标异常: {', '.join(other_names)}"
        return {
            "level": "WARNING",
            "title": f"指标异常检测：{worst['metric_name']}",
            "message": message,
            "context": {
                "anomaly_count": len(anomalies),
                "worst_metric": worst["metric_name"],
                "worst_zscore": worst["zscore"],
                "all_anomalies": [
                    {"metric": a["metric_name"], "zscore": a["zscore"], "value": a["current_value"]}
                    for a in anomalies
                ],
            },
        }
    except Exception as e:
        logger.error(f"[check_anomaly_metrics 异常] {type(e).__name__}: {e}")
    return None


# 健康检查函数注册表（无参数 check）
_HEALTH_CHECKS: list = [
    check_scheduler_failures,
    check_dashboard_restarts,
    check_anomaly_metrics,
]


def run_health_check() -> int:
    """
    定时巡检：遍历所有 check 函数，触发则调 send_alert。
    返回触发的告警数。
    """
    triggered = 0
    for check_fn in _HEALTH_CHECKS:
        try:
            alert = check_fn()
            if alert:
                send_alert(
                    level=alert.get("level", "INFO"),
                    title=alert.get("title", "未命名告警"),
                    message=alert.get("message", ""),
                    context=alert.get("context"),
                )
                triggered += 1
        except Exception as e:
            # 单个 check 失败不影响其他 check
            logger.error(
                f"[run_health_check] {getattr(check_fn, '__name__', '?')} 异常: "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()[:500]}"
            )
    if triggered > 0:
        logger.info(f"[run_health_check] 本次巡检触发 {triggered} 条告警")
    return triggered
