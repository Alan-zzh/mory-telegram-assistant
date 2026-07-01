"""
tasks/monitoring/proactive_audit_task.py - 预防性自审计任务

每天凌晨检查 DB / config / AI / 任务 / 日志 / 磁盘 / 备份健康度。
"""

import glob
import os
import shutil
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext
from tasks.support.fault_reporter import get_fault_reporter

logger = get_logger("tasks.monitoring.proactive_audit")

_CST = timezone(timedelta(hours=8))


def _compute_health_score(rm) -> int:
    """五维度健康度评分。"""
    scores = {}
    try:
        recent_tasks = rm.db.get_recent_task_logs(hours=24) if hasattr(rm.db, 'get_recent_task_logs') else []
        if recent_tasks:
            success_rate = sum(1 for t in recent_tasks if t.get("status") == "success") / len(recent_tasks)
            scores["tasks"] = int(success_rate * 100)
        else:
            scores["tasks"] = 100
    except Exception as e:
        logger.debug(f"任务执行率评分失败: {e}")
        scores["tasks"] = 80

    try:
        if rm.ai and hasattr(rm.ai, "ping"):
            scores["ai"] = 100 if rm.ai.ping() else 50
        else:
            scores["ai"] = 75
    except Exception as e:
        logger.debug(f"AI引擎可用性检查失败: {e}")
        scores["ai"] = 60

    try:
        integrity = rm.db.check_integrity() if hasattr(rm.db, "check_integrity") else "ok"
        scores["db"] = 100 if integrity == "ok" else 70
    except Exception as e:
        logger.debug(f"数据库完整性检查失败: {e}")
        scores["db"] = 70

    try:
        config_ok = rm.config.get("TOKEN", "") and rm.config.get("ADMIN_ID", 0)
        scores["config"] = 100 if config_ok else 50
    except Exception as e:
        logger.debug(f"配置一致性检查失败: {e}")
        scores["config"] = 70

    try:
        total, used, free = shutil.disk_usage("/")
        free_pct = (free / total) * 100
        if free_pct > 20:
            scores["disk"] = 100
        elif free_pct > 10:
            scores["disk"] = 70
        else:
            scores["disk"] = 30
    except Exception as e:
        logger.debug(f"磁盘空间检查失败: {e}")
        scores["disk"] = 80

    weights = {"tasks": 0.30, "ai": 0.25, "db": 0.20, "config": 0.15, "disk": 0.10}
    return int(sum(scores[k] * weights[k] for k in scores))


class ProactiveAuditTask(BaseTask):
    """预防性自审计任务（每天 03:30）。"""

    @property
    def task_id(self) -> str:
        return "proactive_audit"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "proactive_audit",
            "trigger": "cron",
            "hour": 3,
            "minute": 30,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            issues = []

            try:
                if hasattr(self.rm.db, "check_integrity"):
                    result = self.rm.db.check_integrity()
                    if result != "ok":
                        issues.append(f"🔴 [P0] 数据库完整性异常: {result}")
            except Exception as e:
                issues.append(f"🟡 [P1] 数据库检查失败: {e}")

            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                example_path = os.path.join(base_dir, "config.json.example")
                with open(example_path, 'r', encoding='utf-8') as f:
                    example = json.load(f)
                missing = [k for k in example.keys() if k not in self.rm.config and k not in ("TOKEN", "ADMIN_ID")]
                if missing:
                    issues.append(f"🔴 [P0] 配置缺失 {len(missing)} 项: {missing[:5]}...")
            except Exception as e:
                issues.append(f"🟡 [P1] 配置检查失败: {e}")

            try:
                if self.rm.ai and hasattr(self.rm.ai, "ping"):
                    if not self.rm.ai.ping():
                        issues.append("🔴 [P0] AI 引擎不可用")
            except Exception as e:
                issues.append(f"🟡 [P1] AI 检查失败: {e}")

            try:
                if hasattr(self.rm.db, "get_recent_task_logs"):
                    recent = self.rm.db.get_recent_task_logs(hours=24)
                    if recent:
                        failed = sum(1 for t in recent if t.get("status") == "failed")
                        if failed > 0:
                            issues.append(f"🟡 [P1] 24h 内 {failed} 个任务执行失败")
            except Exception as e:
                logger.debug(f"任务执行率检查失败: {e}")

            try:
                total, used, free = shutil.disk_usage("/")
                free_pct = (free / total) * 100
                if free_pct < 10:
                    issues.append(f"🔴 [P0] 磁盘空间不足: {free_pct:.1f}%")
                elif free_pct < 20:
                    issues.append(f"🟡 [P1] 磁盘空间偏紧: {free_pct:.1f}%")
            except Exception as e:
                logger.debug(f"磁盘空间检查失败: {e}")

            try:
                backup_dir = os.path.join(base_dir, "backup")
                if not os.path.isdir(backup_dir):
                    issues.append("🔴 [P0] 备份目录不存在")
                else:
                    backups = sorted(glob.glob(os.path.join(backup_dir, "*.db")), key=os.path.getmtime, reverse=True)
                    if not backups:
                        issues.append("🔴 [P0] 备份目录为空")
                    else:
                        latest = backups[0]
                        age_hours = (time.time() - os.path.getmtime(latest)) / 3600
                        file_size = os.path.getsize(latest)
                        if age_hours >= 25 or file_size <= 0:
                            issues.append(f"🔴 [P0] 备份异常：最新备份 {age_hours:.0f} 小时前，大小 {file_size} 字节")
            except Exception as e:
                logger.debug(f"备份文件检查失败: {e}")

            health_score = _compute_health_score(self.rm)
            if health_score < 60:
                issues.append(f"🔴 [P0] 健康度过低: {health_score}")
            elif health_score < 80:
                issues.append(f"🟡 [P1] 健康度偏低: {health_score}")

            if not issues:
                report = f"✅ 自审计通过\n健康度: {health_score}/100\n所有维度正常"
            else:
                report = (
                    f"📊 自审计报告\n"
                    f"健康度: {health_score}/100\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    + "\n".join(issues)
                )

            admin_id = self.rm.config.get("ADMIN_ID", 0)
            if admin_id:
                with self.rm.locked('bot'):
                    self.rm.bot.send_message(admin_id, report)
            logger.info(f"预防性自审计完成: 健康度={health_score} 问题={len(issues)}")
        except Exception as e:
            logger.error(f"预防性自审计失败: {e}")
