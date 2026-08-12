# -*- coding: utf-8 -*-
"""
dashboard/api/health_api.py · Dashboard 健康度面板

【v5.11.0】提供 4 个端点：
  GET /api/health/score    - 健康度评分（0-100）+ 5 维度明细
  GET /api/health/aborts   - abort 历史（最近 10 条）
  GET /api/health/jobs     - 近 7 日事务任务审计聚合（非 scheduler 注册表）
  GET /api/health/audit    - 最近一次预防性自审计报告
"""
import json
import time
import shutil
import glob
import os
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
# 【v5.31.2 修复】VPS 运行在 UTC，运维显示时间必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))
from flask import Blueprint, jsonify

from dashboard.helpers import login_required, get_db, read_config

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__, url_prefix="/api")


def _get_task_history_stats(conn, cutoff_ts: int) -> dict:
    """统计有 TaskTransactionManager 审计覆盖的任务四态。

    task_execution_history 不是 APScheduler 全量注册表，因此调用方必须明确
    标注 coverage=transactional_tasks，不能把它包装成全部调度任务的健康率。
    """
    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM task_execution_history "
        "WHERE start_ts >= ? GROUP BY status",
        (int(cutoff_ts),),
    ).fetchall()
    counts = {str(row[0]): int(row[1]) for row in rows}
    success = counts.get("success", 0)
    failed = counts.get("failed", 0)
    aborted = counts.get("aborted", 0)
    running = counts.get("running", 0)
    total = success + failed + aborted + running
    denom = success + failed + running
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "aborted": aborted,
        "running": running,
        "rate": round(success * 100.0 / denom, 2) if denom else None,
    }


def _get_recent_task_outcomes(conn, statuses, limit: int = 10) -> dict:
    """返回真实失败/中止记录；状态值由服务端白名单控制。"""
    allowed = [status for status in ("failed", "aborted") if status in set(statuses)]
    if not allowed:
        return {"total": 0, "by_task": {}, "recent": []}
    placeholders = ",".join("?" for _ in allowed)
    total = int(conn.execute(
        f"SELECT COUNT(*) FROM task_execution_history WHERE status IN ({placeholders})",
        allowed,
    ).fetchone()[0] or 0)
    grouped = conn.execute(
        f"SELECT task_key, COUNT(*) FROM task_execution_history "
        f"WHERE status IN ({placeholders}) GROUP BY task_key ORDER BY task_key",
        allowed,
    ).fetchall()
    rows = conn.execute(
        f"SELECT task_key,status,start_ts,end_ts,error_msg,duration_ms "
        f"FROM task_execution_history WHERE status IN ({placeholders}) "
        "ORDER BY start_ts DESC, id DESC LIMIT ?",
        [*allowed, max(1, min(int(limit), 100))],
    ).fetchall()
    recent = [{
        "task_key": str(row[0]),
        "status": str(row[1]),
        "start_ts": int(row[2] or 0),
        "end_ts": int(row[3] or 0),
        "error_msg": str(row[4] or "")[:160],
        "duration_ms": int(row[5] or 0),
    } for row in rows]
    return {
        "total": total,
        "by_task": {str(row[0]): int(row[1]) for row in grouped},
        "recent": recent,
    }


def _get_task_history_jobs(conn, cutoff_ts: int) -> list:
    """按任务聚合事务审计历史；这不是 scheduler 当前注册清单。"""
    rows = conn.execute(
        "SELECT task_key, COUNT(*) AS total, "
        "SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success, "
        "SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed, "
        "SUM(CASE WHEN status='aborted' THEN 1 ELSE 0 END) AS aborted, "
        "SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running, "
        "MAX(start_ts) AS last_ts "
        "FROM task_execution_history WHERE start_ts >= ? "
        "GROUP BY task_key ORDER BY last_ts DESC",
        (int(cutoff_ts),),
    ).fetchall()
    jobs = []
    for row in rows:
        success, failed, aborted, running = (int(row[i] or 0) for i in range(2, 6))
        denom = success + failed + running
        jobs.append({
            "name": str(row[0]),
            "executions_7d": int(row[1] or 0),
            "success": success,
            "failed": failed,
            "aborted": aborted,
            "running": running,
            "success_rate": round(success * 100.0 / denom, 2) if denom else None,
            "last_ts": int(row[6] or 0),
        })
    return jobs


@health_bp.route("/health", methods=["GET"])
def api_health_check():
    """[TRAE SOLO CN] 健康检查端点（无需认证，供监控/负载均衡探测）

    【v5.38.9 安全修复】不再返回 version 字段,避免攻击者据此匹配 CVE。
    探活只需要 status=ok,版本号如需展示在前端应走已登录的 /api/bot/status。

    增加 SQLite 连通性 + Bot 心跳新鲜度检查，
    避免 DB 故障或 Bot 卡死时仍返回 ok。
    """
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        # 检查 Bot 心跳（system_states 表的 last_heartbeat）。缺表/缺行不是
        # 健康证据，必须 fail closed，避免 Dashboard 单进程存活冒充 Bot 正常。
        try:
            row = conn.execute(
                "SELECT value FROM system_states WHERE key='last_heartbeat'"
            ).fetchone()
            if not row:
                return jsonify({"status": "degraded", "msg": "bot heartbeat missing"}), 503
            try:
                last_hb = int(row[0])
            except (TypeError, ValueError):
                last_hb = 0
            if time.time() - last_hb > 120:
                return jsonify({"status": "degraded", "msg": "bot heartbeat stale"}), 503
        except sqlite3.Error as e:
            logger.warning(f"health heartbeat 查询失败：{e}")
            return jsonify({"status": "degraded", "msg": "bot heartbeat unavailable"}), 503
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.debug(f"health root 异常：{e}")
        return jsonify({"status": "down", "msg": "db unavailable"}), 503


@health_bp.route("/health/score")
@login_required
def api_health_score():
    """健康度评分：5 维度 0-100 分"""
    try:
        scores = {}

        # 1. 任务执行率
        try:
            conn = get_db()
            cutoff = int((datetime.now(_CST) - timedelta(hours=24)).timestamp())
            stats = _get_task_history_stats(conn, cutoff)
            if stats["rate"] is None:
                scores["tasks"] = {
                    "score": None,
                    "weight": 30,
                    "known": False,
                    "detail": "24h 无事务任务审计记录，状态未知（不计为成功）",
                    "coverage": "transactional_tasks",
                }
            else:
                scores["tasks"] = {
                    "score": int(round(stats["rate"])),
                    "weight": 30,
                    "detail": (
                        f"事务任务审计 {stats['success']}/{stats['total']}，"
                        f"失败 {stats['failed']}、中止 {stats['aborted']}、运行中 {stats['running']}"
                    ),
                    "coverage": "transactional_tasks",
                }
        except Exception as e:
            logger.debug(f"health score tasks 检查异常：{e}")
            scores["tasks"] = {
                "score": None,
                "weight": 30,
                "known": False,
                "detail": "检查失败，状态未知（详情见服务器日志）",
            }

        # 2. AI 引擎可用性：Dashboard 分进程，未探测就不能编造分数。
        try:
            read_config()
            scores["ai"] = {
                "score": None,
                "weight": 25,
                "known": False,
                "detail": "未实时探测（AI 在Bot进程内），状态未知",
            }
        except Exception as e:
            logger.debug(f"health score AI 配置读取异常：{e}")
            scores["ai"] = {
                "score": None,
                "weight": 25,
                "known": False,
                "detail": "AI状态不可用（详情见服务器日志）",
            }

        # 3. 数据库完整性
        try:
            conn = get_db()
            r = conn.execute("PRAGMA integrity_check").fetchone()
            if r and r[0] == "ok":
                scores["db"] = {"score": 100, "weight": 20, "detail": "PRAGMA integrity_check = ok"}
            else:
                logger.warning(f"DB integrity check 异常：{r}")
                scores["db"] = {"score": 0, "weight": 20, "detail": "完整性检查异常（详情见服务器日志）"}
        except Exception as e:
            logger.debug(f"health score DB integrity 异常：{e}")
            scores["db"] = {"score": 0, "weight": 20, "detail": "完整性检查失败（详情见服务器日志）"}

        # 4. 配置一致性
        try:
            cfg = read_config()
            example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json.example")
            if os.path.exists(example_path):
                with open(example_path, encoding="utf-8") as f:
                    example = json.load(f)
                missing = [k for k in example.keys() if k not in cfg and k not in ("TOKEN", "ADMIN_ID")]
                if not missing:
                    scores["config"] = {"score": 100, "weight": 15, "detail": "无缺失键"}
                else:
                    scores["config"] = {"score": max(0, 100 - len(missing) * 5), "weight": 15, "detail": f"缺失 {len(missing)} 键"}
            else:
                scores["config"] = {"score": 0, "weight": 15, "detail": "无 example 文件"}
        except Exception as e:
            logger.debug(f"health score config 检查异常：{e}")
            scores["config"] = {"score": 0, "weight": 15, "detail": "配置检查失败（详情见服务器日志）"}

        # 5. 磁盘空间
        try:
            total, used, free = shutil.disk_usage("/")
            free_pct = (free / total) * 100
            if free_pct > 20:
                scores["disk"] = {"score": 100, "weight": 10, "detail": f"剩余 {free_pct:.1f}%"}
            elif free_pct > 10:
                scores["disk"] = {"score": 70, "weight": 10, "detail": f"偏紧 {free_pct:.1f}%"}
            else:
                scores["disk"] = {"score": 30, "weight": 10, "detail": f"不足 {free_pct:.1f}%"}
        except Exception as e:
            logger.debug(f"health score disk 检查异常：{e}")
            scores["disk"] = {"score": 0, "weight": 10, "detail": "磁盘检查失败（详情见服务器日志）"}

        # 只计算已知维度；任一维度未知时不返回貌似完整的总分。
        known = [s for s in scores.values() if s.get("score") is not None]
        known_weight = sum(s["weight"] for s in known)
        partial_score = int(round(
            sum(s["score"] * s["weight"] for s in known) / known_weight
        )) if known_weight else None
        has_unknown = any(s.get("score") is None for s in scores.values())
        total_score = None if has_unknown else partial_score

        # 健康度等级
        if total_score is None:
            level = "⚪ 未知"
        elif total_score >= 90:
            level = "🟢 优秀"
        elif total_score >= 75:
            level = "🟡 良好"
        elif total_score >= 60:
            level = "🟠 警告"
        else:
            level = "🔴 危险"

        return jsonify({
            "ok": True,
            "score": total_score,
            "partial_score": partial_score,
            "known_weight": known_weight,
            "level": level,
            "dimensions": scores,
            "ts": int(time.time()),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/aborts")
@login_required
def api_health_aborts():
    """真实失败与中止历史（事务任务审计表）。"""
    try:
        data = _get_recent_task_outcomes(get_db(), {"failed", "aborted"}, limit=10)
        return jsonify({
            "ok": True,
            **data,
            "coverage": "transactional_tasks",
            "note": "仅包含进入 TaskTransactionManager 的任务，不代表全部 APScheduler 作业",
        })
    except Exception as e:
        logger.debug(f"health aborts 异常：{e}")
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/jobs")
@login_required
def api_health_jobs():
    """兼容端点：返回近7日事务任务审计聚合，不冒充scheduler注册清单。"""
    try:
        conn = get_db()
        cutoff = int((datetime.now(_CST) - timedelta(days=7)).timestamp())
        jobs = _get_task_history_jobs(conn, cutoff)
        return jsonify({
            "ok": True,
            "jobs": jobs,
            "total": len(jobs),
            "source": "task_execution_history",
            "is_scheduler_registry": False,
            "note": "当前注册任务请查Bot进程内scheduler；本端点仅为事务任务执行历史",
        })
    except Exception as e:
        logger.debug(f"health jobs 异常：{e}")
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/audit")
@login_required
def api_health_audit():
    """最近一次预防性自审计报告（基于系统状态）"""
    try:
        audit = {
            "ts": int(time.time()),
            "ts_human": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "checks": {},
        }

        # 配置完整性
        try:
            cfg = read_config()
            example_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json.example")
            if os.path.exists(example_path):
                with open(example_path, encoding="utf-8") as f:
                    example = json.load(f)
                missing = [k for k in example.keys() if k not in cfg and k not in ("TOKEN", "ADMIN_ID")]
                if missing:
                    logger.warning(f"health audit config 缺失键 count={len(missing)} sample={missing[:5]}")
                audit["checks"]["config"] = {
                    "ok": len(missing) == 0,
                    "detail": "完整" if not missing else f"缺失 {len(missing)} 键（详情见服务器日志）",
                }
        except Exception as e:
            audit["checks"]["config"] = {"ok": False, "detail": "配置检查失败"}

        # 备份文件
        try:
            backup_dir = os.path.join(os.path.dirname(__file__), "..", "..", "backup")
            if os.path.isdir(backup_dir):
                backups = sorted(glob.glob(os.path.join(backup_dir, "*.db")), key=os.path.getmtime, reverse=True)
                if backups:
                    age_hours = (time.time() - os.path.getmtime(backups[0])) / 3600
                    audit["checks"]["backup"] = {
                        "ok": age_hours < 48,
                        "detail": f"最新备份 {age_hours:.1f}h 前",
                    }
                else:
                    audit["checks"]["backup"] = {"ok": False, "detail": "备份目录为空"}
        except Exception as e:
            audit["checks"]["backup"] = {"ok": False, "detail": "备份检查失败"}

        # 任务执行率
        try:
            conn = get_db()
            cutoff = int((datetime.now(_CST) - timedelta(hours=24)).timestamp())
            stats = _get_task_history_stats(conn, cutoff)
            rate = stats["rate"]
            audit["checks"]["task_rate_24h"] = {
                "ok": rate is not None and stats["failed"] == 0 and stats["running"] == 0,
                "detail": (
                    "24h 无事务任务审计记录，状态未知"
                    if rate is None else
                    f"事务任务成功率 {rate:.2f}%（成功 {stats['success']} / 失败 {stats['failed']} / "
                    f"中止 {stats['aborted']} / 运行中 {stats['running']}）"
                ),
                "coverage": "transactional_tasks",
            }
        except Exception as e:
            audit["checks"]["task_rate_24h"] = {"ok": False, "detail": "任务执行率检查失败"}

        # 汇总
        failed = [k for k, v in audit["checks"].items() if not v["ok"]]
        audit["passed"] = len(failed) == 0
        audit["failed_checks"] = failed

        return jsonify(audit)
    except Exception as e:
        logger.debug(f"health audit 异常：{e}")
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/task-success-rate")
@login_required
def api_health_task_success_rate():
    """【v5.38.9】真实任务成功率(基于 task_execution_history 审计表)

    旧版 /api/health/jobs 基于 task_log(分布式锁表,执行后 DELETE)算成功率,
    必然 100% 失真。本端点读取 TaskTransactionManager 写入的真实四态统计。

    需要登录,不在 _EXEMPT_PREFIXES 豁免列表中。

    【P0-1 修复】get_db() 返回原生 sqlite3.Connection,无 get_success_rate 方法,
    改用原生 SQL 直接查询 task_execution_history 表,绕过 Repo 委托。
    SQL 参考 task_exec_history_repo.py 的 get_success_rate 实现。
    """
    try:
        from flask import request
        # 默认 7 天,允许 1-90 天范围
        days = 7
        try:
            days = int(request.args.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(int(days or 7), 90))
        conn = get_db()
        cutoff = int((datetime.now(_CST) - timedelta(days=days)).timestamp())
        stats = _get_task_history_stats(conn, cutoff)
        stats["days"] = days
        return jsonify({
            "ok": True,
            "ts": int(time.time()),
            "stats": stats,
            "coverage": "transactional_tasks",
            "note": "真实四态统计；仅覆盖进入TaskTransactionManager的任务，不代表全部APScheduler作业",
        })
    except Exception as e:
        logger.debug(f"health task_success_rate 异常：{e}")
        return jsonify({"ok": False, "error": "任务审计数据不可用"}), 503
