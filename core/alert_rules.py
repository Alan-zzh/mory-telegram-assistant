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

import traceback
from typing import Optional, Callable

from core.logging_util import get_logger
from core.alert_bot import send_alert

logger = get_logger("alert_rules")

# 阈值常量
_QSIZE_WARN = 50
_QSIZE_CRIT = 150
_SCHED_FAIL_THRESHOLD = 1   # 调度失败次数超过此值即告警
_DASH_RESTART_THRESHOLD = 3  # Dashboard 重启次数告警阈值


def check_write_queue_backlog() -> Optional[dict]:
    """
    检查 WriteQueue 积压。
    qsize > 150 → CRITICAL；> 50 → WARNING；否则 None。
    """
    try:
        from core.write_queue import write_queue
        stats = write_queue.get_stats()
        qsize = stats.get("pending", 0)
        if qsize > _QSIZE_CRIT:
            return {
                "level": "CRITICAL",
                "title": "WriteQueue 严重积压",
                "message": f"队列待处理任务 {qsize} 条（阈值 {_QSIZE_CRIT}），存在写入阻塞风险",
                "context": {"qsize": qsize, "stats": stats},
            }
        if qsize > _QSIZE_WARN:
            return {
                "level": "WARNING",
                "title": "WriteQueue 积压告警",
                "message": f"队列待处理任务 {qsize} 条（阈值 {_QSIZE_WARN}）",
                "context": {"qsize": qsize, "stats": stats},
            }
    except Exception as e:
        logger.error(f"[check_write_queue_backlog 异常] {type(e).__name__}: {e}")
    return None


def check_scheduler_failures() -> Optional[dict]:
    """
    检查调度任务失败次数。
    scheduler_monitor 统计的 total_fail 超过阈值 → CRITICAL。
    """
    try:
        from core.scheduler_monitor import get_scheduler_stats
        stats = get_scheduler_stats()
        total_fail = stats.get("total_fail", 0)
        if total_fail > _SCHED_FAIL_THRESHOLD:
            # 收集失败最严重的 job
            jobs = stats.get("jobs", {})
            failed_jobs = {
                jid: info for jid, info in jobs.items()
                if info.get("last_status") == "error"
            }
            return {
                "level": "CRITICAL",
                "title": "调度任务失败告警",
                "message": f"调度器累计失败 {total_fail} 次，最近失败任务: {list(failed_jobs.keys())[:5]}",
                "context": {
                    "total_fail": total_fail,
                    "total_miss": stats.get("total_miss", 0),
                    "failed_jobs": {
                        jid: {
                            "fail_count": info.get("fail_count", 0),
                            "last_error": info.get("last_error", ""),
                        } for jid, info in failed_jobs.items()
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
        logger.debug(f"[check_dashboard_restarts 跳过] {type(e).__name__}: {e}")
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
    check_write_queue_backlog,
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
