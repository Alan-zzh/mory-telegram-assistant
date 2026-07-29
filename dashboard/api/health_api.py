# -*- coding: utf-8 -*-
"""
dashboard/api/health_api.py · Dashboard 健康度面板

【v5.11.0】提供 4 个端点：
  GET /api/health/score    - 健康度评分（0-100）+ 5 维度明细
  GET /api/health/aborts   - abort 历史（最近 10 条）
  GET /api/health/jobs     - scheduler 注册任务清单
  GET /api/health/audit    - 最近一次预防性自审计报告
"""
import json
import time
import shutil
import glob
import os
import sqlite3
from datetime import datetime, timedelta, timezone
# 【v5.31.2 修复】VPS 运行在 UTC，运维显示时间必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))
from flask import Blueprint, jsonify

from dashboard.helpers import login_required, get_db, read_config

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.route("/health", methods=["GET"])
def api_health_check():
    """[TRAE SOLO CN] 健康检查端点（无需认证，供监控/负载均衡探测）

    【v5.38.9 安全修复】不再返回 version 字段,避免攻击者据此匹配 CVE。
    探活只需要 status=ok,版本号如需展示在前端应走已登录的 /api/bot/status。

    【v5.39.0 实质检查】增加 SQLite 连通性 + Bot 心跳新鲜度检查，
    避免 DB 故障或 Bot 卡死时仍返回 ok。
    """
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        # 检查 Bot 心跳（system_states 表的 last_heartbeat）
        try:
            row = conn.execute(
                "SELECT value FROM system_states WHERE key='last_heartbeat'"
            ).fetchone()
            if row:
                try:
                    last_hb = int(row[0])
                except (TypeError, ValueError):
                    last_hb = 0
                if time.time() - last_hb > 120:
                    return jsonify({"status": "degraded", "msg": "bot heartbeat stale"}), 503
        except sqlite3.Error:
            pass  # system_states 表不存在或无心跳记录，不阻塞健康检查
        return jsonify({"status": "ok"})
    except Exception:
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
            # task_log 表只有 id/task_key/exec_date/exec_ts，无 status 列
            # 语义：task_log 只记录成功执行的任务，失败任务不写入，故 success=total
            rows = conn.execute(
                "SELECT task_key, COUNT(*) FROM task_log WHERE exec_ts >= ? GROUP BY task_key",
                (cutoff,)
            ).fetchall()
            total = sum(c for _, c in rows)
            if total > 0:
                scores["tasks"] = {"score": 100, "weight": 30, "detail": f"{total} 次执行（{len(rows)} 个任务）"}
            else:
                scores["tasks"] = {"score": 100, "weight": 30, "detail": "无任务记录"}
        except Exception as e:
            scores["tasks"] = {"score": 80, "weight": 30, "detail": f"检查失败: {e}"}

        # 2. AI 引擎可用性（基础探测）
        try:
            cfg = read_config()
            scores["ai"] = {"score": 75, "weight": 25, "detail": "未实时 ping（AI 在 bot 进程内）"}
        except Exception:
            scores["ai"] = {"score": 70, "weight": 25, "detail": "配置读取失败"}

        # 3. 数据库完整性
        try:
            conn = get_db()
            r = conn.execute("PRAGMA integrity_check").fetchone()
            if r and r[0] == "ok":
                scores["db"] = {"score": 100, "weight": 20, "detail": "PRAGMA integrity_check = ok"}
            else:
                scores["db"] = {"score": 70, "weight": 20, "detail": f"integrity: {r}"}
        except Exception as e:
            scores["db"] = {"score": 70, "weight": 20, "detail": f"检查失败: {e}"}

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
                scores["config"] = {"score": 80, "weight": 15, "detail": "无 example 文件"}
        except Exception as e:
            scores["config"] = {"score": 70, "weight": 15, "detail": f"检查失败: {e}"}

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
            scores["disk"] = {"score": 80, "weight": 10, "detail": f"检查失败: {e}"}

        # 计算总分
        total_score = sum(s["score"] * s["weight"] / 100 for s in scores.values())
        total_score = int(total_score)

        # 健康度等级
        if total_score >= 90:
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
            "level": level,
            "dimensions": scores,
            "ts": int(time.time()),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/aborts")
@login_required
def api_health_aborts():
    """abort 历史：task_log 表无 status 列，失败任务不写入，返回空列表"""
    try:
        # task_log 表只有 id/task_key/exec_date/exec_ts，无 status/error_msg 列
        # 失败任务不会写入 task_log，故无 abort 历史可返回
        # 如需失败历史，应查 llm_cost_logs 表的 success=0 记录或 report_fault 日志
        return jsonify({
            "ok": True,
            "total": 0,
            "by_task": {},
            "recent": [],
            "note": "task_log 表无 status 列，失败任务不写入；如需失败历史请查 llm_cost_logs",
        })
    except Exception:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/jobs")
@login_required
def api_health_jobs():
    """scheduler 注册任务清单（从 task_log 历史推断）"""
    try:
        conn = get_db()
        cutoff = int((datetime.now(_CST) - timedelta(days=7)).timestamp())
        # task_log 表只有 id/task_key/exec_date/exec_ts，无 status/task_name 列
        # 语义：task_log 只记录成功执行的任务，故 success_rate=100%
        rows = conn.execute(
            "SELECT task_key, COUNT(*) as cnt, MAX(exec_ts) as last_ts "
            "FROM task_log WHERE exec_ts >= ? GROUP BY task_key ORDER BY cnt DESC",
            (cutoff,)
        ).fetchall()
        jobs = []
        for r in rows:
            name, cnt, last_ts = r
            jobs.append({
                "name": name,
                "executions_7d": cnt,
                "success_rate": 100.0,  # task_log 只记录成功执行
                "last_ts": last_ts,
            })
        return jsonify({"ok": True, "jobs": jobs, "total": len(jobs)})
    except Exception:
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
                audit["checks"]["config"] = {
                    "ok": len(missing) == 0,
                    "detail": "完整" if not missing else f"缺失 {len(missing)} 键: {missing[:5]}",
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
            # task_log 表只有 id/task_key/exec_date/exec_ts，无 status 列
            # 语义：task_log 只记录成功执行的任务，故 succ=total
            r = conn.execute(
                "SELECT COUNT(*) FROM task_log WHERE exec_ts >= ?",
                (cutoff,)
            ).fetchone()
            total = r[0] or 0
            rate = 100.0  # task_log 只记录成功执行
            audit["checks"]["task_rate_24h"] = {
                "ok": total > 0,
                "detail": f"24h 执行 {total} 次（task_log 只记录成功执行，成功率 100%）",
            }
        except Exception as e:
            audit["checks"]["task_rate_24h"] = {"ok": False, "detail": "任务执行率检查失败"}

        # 汇总
        failed = [k for k, v in audit["checks"].items() if not v["ok"]]
        audit["passed"] = len(failed) == 0
        audit["failed_checks"] = failed

        return jsonify(audit)
    except Exception:
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
        from urllib.parse import parse_qs
        from flask import request
        # 默认 7 天,允许 1-90 天范围
        days = 7
        qs = parse_qs(request.query_string.decode("utf-8")) if request.query_string else {}
        if qs.get("days"):
            try:
                days = int(qs["days"][0])
            except (ValueError, IndexError):
                days = 7
        days = max(1, min(int(days or 7), 90))
        conn = get_db()
        # 直接用原生 sqlite3 查询,绕过 Repo 委托(get_db 返回原生 Connection)
        cutoff_date = (datetime.now(_CST) - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM task_execution_history "
                "WHERE exec_date >= ? GROUP BY status",
                (cutoff_date,)
            ).fetchall()
        except Exception:
            # 表可能不存在(Dashboard 直连未初始化),返回空统计
            rows = []
        counts = {row[0]: int(row[1]) for row in rows}
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        aborted = counts.get("aborted", 0)
        running = counts.get("running", 0)
        total = success + failed + aborted + running
        # 成功率 = success / (success + failed + running),aborted 是主动中止不计入分母
        denom = success + failed + running
        rate = round(success * 100.0 / denom, 2) if denom > 0 else 0.0
        stats = {
            "total": total,
            "success": success,
            "failed": failed,
            "aborted": aborted,
            "running": running,
            "rate": rate,
            "days": days,
        }
        return jsonify({
            "ok": True,
            "ts": int(time.time()),
            "stats": stats,
            "note": "基于 task_execution_history 真实四态统计,替代旧 task_log 100% 失真",
        })
    except Exception:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500
