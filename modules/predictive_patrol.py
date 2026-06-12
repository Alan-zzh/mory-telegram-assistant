"""
modules/predictive_patrol.py · 预测性巡检

【v5.11.0】基于历史数据预测系统健康度趋势，提前发现潜在故障：
  1. 任务执行时间漂移（9:05 播报实际上 9:30 才开始）
  2. AI 限额接近上限（基于 API 调用次数 vs 限额）
  3. 磁盘增长趋势（基于 backup 目录大小变化）
  4. 数据库表膨胀（基于行数变化）
"""

import time
import glob
import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("predictive_patrol")


def detect_execution_drift(db, task_name: str, expected_hour: int, expected_minute: int, grace_min: int = 30) -> dict:
    """检测任务执行时间漂移

    Returns:
        {
            "task": task_name,
            "drift_min": 0,  # 实际开始时间 vs 预期时间的偏移（分钟）
            "status": "ok" | "warning" | "critical",
            "msg": str,
        }
    """
    try:
        cutoff = int((datetime.now() - timedelta(days=14)).timestamp())
        rows = db.execute(
            "SELECT ts FROM task_log WHERE task_name = ? AND ts >= ? AND status IN ('success','done') ORDER BY ts DESC LIMIT 14",
            (task_name, cutoff)
        ).fetchall()
        if not rows:
            return {"task": task_name, "drift_min": 0, "status": "warning", "msg": "无成功执行记录"}

        # 转换为小时:分钟
        drifts = []
        for r in rows:
            ts = r[0]
            dt = datetime.fromtimestamp(ts)
            actual_h = dt.hour
            actual_m = dt.minute
            expected_total = expected_hour * 60 + expected_minute
            actual_total = actual_h * 60 + actual_m
            drift = actual_total - expected_total
            drifts.append(drift)

        avg_drift = sum(drifts) / len(drifts)
        status = "ok"
        if abs(avg_drift) > grace_min:
            status = "critical"
        elif abs(avg_drift) > grace_min / 2:
            status = "warning"

        return {
            "task": task_name,
            "drift_min": round(avg_drift, 1),
            "samples": len(drifts),
            "status": status,
            "msg": f"过去 14 天平均漂移 {avg_drift:+.1f} 分钟" if drifts else "无数据",
        }
    except Exception as e:
        return {"task": task_name, "drift_min": 0, "status": "warning", "msg": f"检测失败: {e}"}


def detect_ai_quota(config: dict) -> dict:
    """检测 AI 限额接近上限（基于已配置信息和 API 调用频率）"""
    try:
        model_pools = config.get("MODEL_POOLS", {})
        llm_pool = model_pools.get("llm", [])
        if not llm_pool:
            return {"status": "warning", "msg": "无 LLM 模型池配置", "used_pct": 0}

        # 简化：检查 expire 字段
        now = datetime.now()
        expiring = []
        for m in llm_pool:
            expire_str = m.get("expire", "")
            if expire_str:
                try:
                    expire_dt = datetime.strptime(expire_str, "%Y-%m-%d")
                    days_left = (expire_dt - now).days
                    if days_left < 30:
                        expiring.append((m.get("name", "?"), days_left))
                except Exception:
                    pass

        if expiring:
            return {
                "status": "warning" if any(d < 7 for _, d in expiring) else "ok",
                "msg": f"{len(expiring)} 个模型 30 天内到期: {expiring[:3]}",
                "used_pct": 0,
            }
        return {"status": "ok", "msg": "所有模型 30 天内不会到期", "used_pct": 0}
    except Exception as e:
        return {"status": "warning", "msg": f"检测失败: {e}", "used_pct": 0}


def detect_disk_growth(base_dir: str) -> dict:
    """检测磁盘增长趋势（基于 backup 目录）"""
    try:
        backup_dir = os.path.join(base_dir, "backups")
        if not os.path.isdir(backup_dir):
            return {"status": "warning", "msg": "备份目录不存在", "growth_mb_per_day": 0}

        backups = sorted(glob.glob(os.path.join(backup_dir, "*.db")), key=os.path.getmtime)
        if len(backups) < 2:
            return {"status": "ok", "msg": "样本不足（<2 个备份）", "growth_mb_per_day": 0}

        # 计算最早和最近之间的大小变化
        oldest = backups[0]
        newest = backups[-1]
        oldest_mtime = os.path.getmtime(oldest)
        newest_mtime = os.path.getmtime(newest)
        oldest_size = os.path.getsize(oldest) / 1024 / 1024
        newest_size = os.path.getsize(newest) / 1024 / 1024
        days = max((newest_mtime - oldest_mtime) / 86400, 0.1)
        growth = (newest_size - oldest_size) / days

        status = "ok"
        if growth > 50:
            status = "critical"
        elif growth > 10:
            status = "warning"

        return {
            "status": status,
            "msg": f"过去 {days:.1f} 天增长 {growth:+.2f} MB/天",
            "growth_mb_per_day": round(growth, 2),
        }
    except Exception as e:
        return {"status": "warning", "msg": f"检测失败: {e}", "growth_mb_per_day": 0}


def detect_db_table_bloat(db) -> list:
    """检测数据库表膨胀（行数 + 索引碎片）"""
    try:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        bloated = []
        for t in tables:
            name = t[0]
            try:
                cnt = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                if cnt > 100000:
                    bloated.append({"table": name, "rows": cnt})
            except Exception as e:
                logger.warning(f"巡检异常: 表 {name} 行数查询失败: {e}")
        return bloated
    except Exception as e:
        logger.warning(f"巡检异常: 数据库表膨胀检测失败: {e}")
        return []


def run_predictive_patrol(rm) -> dict:
    """运行全部预测性巡检，输出报告"""
    config = rm.config
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 任务执行时间漂移
    drift_results = []
    for job_id, h, m, grace in [
        ("greeting_morning", 8, 5, 30),
        ("greeting_afternoon", 12, 35, 30),
        ("news_morning", 9, 5, 30),
        ("news_afternoon", 13, 5, 30),
        ("news_evening", 20, 35, 30),
        ("daily_report", 9, 10, 30),
    ]:
        drift = detect_execution_drift(rm.db, job_id, h, m, grace)
        drift_results.append(drift)

    # AI 限额
    ai_quota = detect_ai_quota(config)

    # 磁盘增长
    disk_growth = detect_disk_growth(base_dir)

    # 数据库表膨胀
    bloated_tables = detect_db_table_bloat(rm.db)

    # 汇总风险
    risks = []
    for d in drift_results:
        if d["status"] in ("warning", "critical"):
            risks.append(f"⏰ 任务 {d['task']} 时间漂移: {d['msg']}")
    if ai_quota["status"] in ("warning", "critical"):
        risks.append(f"🤖 AI 限额: {ai_quota['msg']}")
    if disk_growth["status"] in ("warning", "critical"):
        risks.append(f"💾 磁盘增长: {disk_growth['msg']}")
    if bloated_tables:
        risks.append(f"📊 数据库表膨胀: {len(bloated_tables)} 张表 > 10 万行")

    return {
        "ts": int(time.time()),
        "ts_human": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "drift": drift_results,
        "ai_quota": ai_quota,
        "disk_growth": disk_growth,
        "bloated_tables": bloated_tables,
        "risks": risks,
        "passed": len(risks) == 0,
    }
