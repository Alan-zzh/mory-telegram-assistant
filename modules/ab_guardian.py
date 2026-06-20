# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/ab_guardian.py  ·  A/B 测试异常监控与自动回滚守护（v1.0）      ║
║                                                                        ║
║  功能：                                                                ║
║    1. 定时巡检 —— 每 N 分钟检查所有运行中实验的核心指标                 ║
║    2. 阈值比对 —— 退群率 delta / 投诉率 / 转化率 ratio                  ║
║    3. 自动回滚 —— 触发阈值后自动将实验状态改为 rolled_back             ║
║    4. 管理员告警 —— 回滚时通知管理员并给出原因                           ║
║                                                                        ║
║  被调用：modules/auto_tasks.py 定时任务                                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time

from core.logging_util import get_logger
from core.ab_testing import ABTestEngine, ABTestGuardian

logger = get_logger("ab_guardian")


def run_ab_guardian_job(bot, db, config: dict):
    """
    供 auto_tasks.py 调用的守护巡检任务。
    触发回滚后，通过 bot 通知管理员。
    """
    ab_cfg = config.get("AB_TEST_CONFIG", {})
    if not ab_cfg.get("enabled", False):
        return []

    guardian = ABTestGuardian(db, config)
    alerts = guardian.check_all()
    rolled_back = []

    for alert in alerts:
        eid = alert.get("experiment_id")
        alert_type = alert.get("alert_type")
        bad_variant = alert.get("bad_variant", "")
        reason = alert.get("alert_reason", "")

        logger.warning(f"[AB Guardian] 告警: {eid} | {alert_type} | {reason}")

        # 自动回滚：任何严重告警都触发回滚
        ok = guardian.rollback(eid, reason=f"{alert_type}: {reason}")
        if ok:
            rolled_back.append(eid)
            _notify_admin(bot, config, eid, alert_type, reason, bad_variant)

    if not alerts:
        logger.debug("[AB Guardian] 巡检完成，无异常")

    return rolled_back


def _notify_admin(bot, config: dict, experiment_id: str, alert_type: str, reason: str, bad_variant: str):
    """向管理员发送回滚通知"""
    admin_id = config.get("ADMIN_ID", 0)
    if not admin_id or not bot:
        return
    try:
        msg = (
            f"🚨 <b>A/B 测试自动回滚通知</b>\n"
            f"实验ID: <code>{experiment_id}</code>\n"
            f"告警类型: {alert_type}\n"
            f"原因: {reason}\n"
            f"问题版本: {bad_variant}\n"
            f"动作: 已自动回滚至对照组(A组)，新用户将不再进入问题版本。"
        )
        bot.send_message(admin_id, msg, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"守护告警通知管理员失败: {e}")
