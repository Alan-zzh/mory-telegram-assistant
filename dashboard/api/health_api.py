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
from datetime import datetime, timedelta
from flask import Blueprint, jsonify

from dashboard.helpers import login_required, get_db, read_config

health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.route("/health", methods=["GET"])
def api_health_check():
    """[TRAE SOLO CN] 健康检查端点（无需认证，供监控/负载均衡探测）"""
    try:
        from version import VERSION
        version = VERSION
    except Exception:
        version = "unknown"
    return jsonify({"status": "ok", "version": version})


@health_bp.route("/health/score")
@login_required
def api_health_score():
    """健康度评分：5 维度 0-100 分"""
    try:
        scores = {}

        # 1. 任务执行率
        try:
            conn = get_db()
            cutoff = int((datetime.now() - timedelta(hours=24)).timestamp())
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM task_log WHERE ts >= ? GROUP BY status",
                (cutoff,)
            ).fetchall()
            total = sum(c for _, c in rows)
            success = sum(c for s, c in rows if s in ("success", "done"))
            if total > 0:
                scores["tasks"] = {"score": int(success / total * 100), "weight": 30, "detail": f"{success}/{total}"}
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
    """abort 历史：读取 task_log 中的失败/abort 记录"""
    try:
        conn = get_db()
        cutoff = int((datetime.now() - timedelta(days=7)).timestamp())
        rows = conn.execute(
            "SELECT task_name, status, error_msg, ts FROM task_log WHERE ts >= ? AND status IN ('abort', 'failed') ORDER BY ts DESC LIMIT 50",
            (cutoff,)
        ).fetchall()
        aborts = [
            {"task": r[0], "status": r[1], "error": r[2], "ts": r[3]}
            for r in rows
        ]
        # 按 task 聚合
        by_task = {}
        for a in aborts:
            t = a["task"]
            by_task.setdefault(t, {"count": 0, "latest_error": "", "latest_ts": 0})
            by_task[t]["count"] += 1
            if a["ts"] > by_task[t]["latest_ts"]:
                by_task[t]["latest_error"] = a["error"]
                by_task[t]["latest_ts"] = a["ts"]
        return jsonify({
            "ok": True,
            "total": len(aborts),
            "by_task": by_task,
            "recent": aborts[:10],
        })
    except Exception:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500


@health_bp.route("/health/jobs")
@login_required
def api_health_jobs():
    """scheduler 注册任务清单（从 task_log 历史推断）"""
    try:
        conn = get_db()
        cutoff = int((datetime.now() - timedelta(days=7)).timestamp())
        rows = conn.execute(
            "SELECT task_name, COUNT(*) as cnt, MAX(ts) as last_ts, "
            "SUM(CASE WHEN status='success' OR status='done' THEN 1 ELSE 0 END) as succ "
            "FROM task_log WHERE ts >= ? GROUP BY task_name ORDER BY cnt DESC",
            (cutoff,)
        ).fetchall()
        jobs = []
        for r in rows:
            name, cnt, last_ts, succ = r
            succ = succ or 0
            jobs.append({
                "name": name,
                "executions_7d": cnt,
                "success_rate": round(succ / cnt * 100, 1) if cnt else 0,
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
            "ts_human": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
            backup_dir = os.path.join(os.path.dirname(__file__), "..", "..", "backups")
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
            cutoff = int((datetime.now() - timedelta(hours=24)).timestamp())
            r = conn.execute(
                "SELECT SUM(CASE WHEN status IN ('success','done') THEN 1 ELSE 0 END), COUNT(*) FROM task_log WHERE ts >= ?",
                (cutoff,)
            ).fetchone()
            succ, total = (r[0] or 0), (r[1] or 0)
            rate = round(succ / total * 100, 1) if total else 100
            audit["checks"]["task_rate_24h"] = {
                "ok": rate >= 80,
                "detail": f"24h 成功率 {rate}% ({succ}/{total})",
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
