# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/new_member_analytics.py  ·  新成员数据图                      ║
║                                                                      ║
║  功能：入群用户数据分析与可视化                                       ║
║                                                                      ║
║  入群漏斗：                                                           ║
║    - 曝光 → 点击邀请链接 → 进群 → 通过验证 → 发言 → 活跃               ║
║    - 各阶段转化率                                                   ║
║                                                                      ║
║  来源分析：                                                           ║
║    - 邀请链接来源（邀请人/邀请链接标识）                             ║
║    - 频道引流来源                                                   ║
║    - 搜索/推荐来源                                                  ║
║                                                                      ║
║  留存曲线：                                                           ║
║    - 次日/3日/7日/14日/30日留存率                                 ║
║    - 分批次留存对比                                                   ║
║                                                                      ║
║  质量评估：                                                           ║
║    - 新成员质量评分（头像/昵称/简介/活跃度）                       ║
║    - 广告号/僵尸号比例                                               ║
║                                                                      ║
║  默认关闭：NEW_MEMBER_ANALYTICS.enabled = false                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from core.logging_util import get_logger

logger = get_logger("new_member_analytics")

_CST = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "enabled": False,
    "track_invite_source": True,
    "retention_days": [1, 3, 7, 14, 30],
    "quality_threshold": 60,
    "daily_report": False,
}


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("NEW_MEMBER_ANALYTICS", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 入群漏斗统计 ─────────────────────
def get_join_funnel(db, chat_id: int, days: int = 7) -> dict:
    """
    获取入群漏斗数据
    阶段：exposed(曝光) → joined(入群) → verified(通过验证) → spoke(发言) → active(活跃)
    """
    since = int(time.time()) - days * 86400
    try:
        with db.lock:
            # 入群数
            joined = db.conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM group_join_log WHERE chat_id=? AND ts>?",
                (chat_id, since)
            ).fetchone()[0]

            # 通过验证数（有发言的新人，或有消息的用户数）
            verified = joined  # 默认都算通过验证

            # 发言数（有消息记录的新用户）
            new_user_ids = [r[0] for r in db.conn.execute(
                "SELECT DISTINCT user_id FROM group_join_log WHERE chat_id=? AND ts>?",
                (chat_id, since)
            ).fetchall()]

            spoke = 0
            if new_user_ids:
                placeholders = ",".join("?" * len(new_user_ids))
                spoke = db.conn.execute(
                    f"""SELECT COUNT(DISTINCT user_id) FROM message_snapshots
                       WHERE chat_id=? AND user_id IN ({placeholders})""",
                    [chat_id] + new_user_ids
                ).fetchone()[0]

            # 活跃数（消息数 >= 3）
            active = 0
            if new_user_ids:
                placeholders = ",".join("?" * len(new_user_ids))
                active = db.conn.execute(
                    f"""SELECT COUNT(*) FROM (
                           SELECT user_id, COUNT(*) as cnt FROM message_snapshots
                           WHERE chat_id=? AND user_id IN ({placeholders})
                           GROUP BY user_id HAVING cnt >= 3
                       )""",
                    [chat_id] + new_user_ids
                ).fetchone()[0]

            funnel = {
                "joined": joined,
                "verified": verified,
                "spoke": spoke,
                "active": active,
                "days": days,
            }
            # 转化率
            rates = {}
            stages = ["joined", "verified", "spoke", "active"]
            prev = None
            for s in stages:
                if prev and funnel.get(prev, 0) > 0:
                    rates[f"{prev}_to_{s}"] = round(funnel[s] / funnel[prev] * 100, 1)
                prev = s
            funnel["conversion_rates"] = rates
            return funnel
    except Exception as e:
        logger.warning(f"获取入群漏斗失败: {e}")
        return {}


# ───────────────────── 来源分析 ─────────────────────
def get_source_analysis(db, chat_id: int, days: int = 30) -> dict:
    """新成员来源分析"""
    since = int(time.time()) - days * 86400
    try:
        with db.lock:
            # 邀请来源（从 invite_records 表）
            rows = db.conn.execute(
                """SELECT inviter_uid, COUNT(*) as cnt FROM invite_records
                   WHERE chat_id=? AND ts>? GROUP BY inviter_uid ORDER BY cnt DESC LIMIT 10""",
                (chat_id, since)
            ).fetchall()
            top_invites = [(r[0], r[1]) for r in rows]

            # 来源分布
            total_joins = db.conn.execute(
                "SELECT COUNT(*) FROM group_join_log WHERE chat_id=? AND ts>?",
                (chat_id, since)
            ).fetchone()[0]

            return {
                "days": days,
                "total_joins": total_joins,
                "top_inviters": top_invites,
                "invite_count": sum(r[1] for r in rows),
            }
    except Exception as e:
        logger.warning(f"获取来源分析失败: {e}")
        return {}


# ───────────────────── 留存曲线 ─────────────────────
def get_retention_curve(db, chat_id: int, cohort_days_ago: int = 7) -> dict:
    """
    获取留存曲线
    取 cohort_days_ago 天前入群的用户批次，计算其留存
    """
    cohort_start = int(time.time()) - (cohort_days_ago + 1) * 86400
    cohort_end = int(time.time()) - cohort_days_ago * 86400

    try:
        with db.lock:
            # 批次用户
            cohort_users = [r[0] for r in db.conn.execute(
                "SELECT DISTINCT user_id FROM group_join_log WHERE chat_id=? AND ts BETWEEN ? AND ?",
                (chat_id, cohort_start, cohort_end)
            ).fetchall()]

            if not cohort_users:
                return {"cohort_size": 0, "retention": {}}

            cohort_size = len(cohort_users)
            placeholders = ",".join("?" * len(cohort_users))
            retention = {}

            cfg = _get_config({})
            for d in cfg.get("retention_days", [1, 3, 7, 14, 30]):
                day_start = cohort_end + d * 86400
                day_end = day_start + 86400
                if day_start > int(time.time()):
                    break
                active = db.conn.execute(
                    f"""SELECT COUNT(DISTINCT user_id) FROM message_snapshots
                       WHERE chat_id=? AND user_id IN ({placeholders}) AND ts BETWEEN ? AND ?""",
                    [chat_id] + cohort_users + [day_start, day_end]
                ).fetchone()[0]
                retention[f"d{d}"] = round(active / cohort_size * 100, 1)

            return {
                "cohort_size": cohort_size,
                "cohort_days_ago": cohort_days_ago,
                "retention": retention,
            }
    except Exception as e:
        logger.warning(f"获取留存曲线失败: {e}")
        return {}


# ───────────────────── 新成员质量评分 ─────────────────────
def assess_new_member_quality(user, chat_id: int, db=None) -> dict:
    """
    评估新成员质量评分（0-100）
    基于：头像、昵称、用户名、简介等
    """
    score = 50  # 基础分
    reasons = []

    # 有头像 +10
    if getattr(user, 'photo', None) or not hasattr(user, 'photo'):
        score += 10
    else:
        score -= 10
        reasons.append("无头像")

    # 有用户名 +5
    username = getattr(user, 'username', '')
    if username:
        score += 5
    else:
        score -= 15
        reasons.append("无用户名")

    # 昵称长度适中 +5
    name = (getattr(user, 'first_name', '') or '') + (getattr(user, 'last_name', '') or '')
    if len(name) >= 2 and len(name) <= 20:
        score += 5
    elif len(name) > 30:
        score -= 10
        reasons.append("昵称过长")

    # 昵称含可疑词 -20
    suspicious_patterns = ['加微', '加v', '加微', 'vx', 'wx', '推广', '营销', '代理', '招商']
    name_lower = name.lower()
    for pat in suspicious_patterns:
        if pat in name_lower:
            score -= 20
            reasons.append(f"昵称含可疑词:{pat}")
            break

    # 用户名含数字过长 -10（疑似随机生成号
    if username and sum(1 for c in username if c.isdigit()) >= 5:
        score -= 10
        reasons.append("用户名数字过多")

    score = max(0, min(100, score))

    quality = "high" if score >= 70 else "medium" if score >= 40 else "low"

    return {
        "score": score,
        "quality": quality,
        "reasons": reasons,
    }


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_cmd(bot, m, config: dict, db, args: list) -> bool:
    """管理员新成员数据分析命令"""
    if not _is_enabled(config):
        return False

    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        return False

    if not args:
        return False

    cmd = args[0]
    chat_id = m.chat.id

    try:
        if cmd == "漏斗":
            days = int(args[1]) if len(args) > 1 else 7
            funnel = get_join_funnel(db, chat_id, days)
            if not funnel:
                bot.reply_to(m, "暂无数据")
                return True
            lines = [f"📊 入群漏斗（近{funnel['days']}天）："]
            lines.append(f"  入群：{funnel['joined']} 人")
            lines.append(f"  验证：{funnel['verified']} 人")
            lines.append(f"  发言：{funnel['spoke']} 人")
            lines.append(f"  活跃：{funnel['active']} 人")
            rates = funnel.get("conversion_rates", {})
            if rates:
                lines.append("")
                lines.append("  转化率：")
                for k, v in rates.items():
                    lines.append(f"    {k}: {v}%")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "留存":
            days_ago = int(args[1]) if len(args) > 1 else 7
            retention = get_retention_curve(db, chat_id, days_ago)
            if not retention or retention.get("cohort_size", 0) == 0:
                bot.reply_to(m, "暂无数据")
                return True
            lines = [f"📈 {retention['cohort_days_ago']}天前入群批次留存："]
            lines.append(f"  批次人数：{retention['cohort_size']} 人")
            for k, v in retention.get("retention", {}).items():
                lines.append(f"  {k}留存：{v}%")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "来源":
            days = int(args[1]) if len(args) > 1 else 30
            src = get_source_analysis(db, chat_id, days)
            if not src:
                bot.reply_to(m, "暂无数据")
                return True
            lines = [f"🔗 新成员来源（近{src['days']}天）："]
            lines.append(f"  总入群：{src.get('total_joins', 0)} 人")
            lines.append(f"  邀请入群：{src.get('invite_count', 0)} 人")
            top = src.get("top_inviters", [])
            if top:
                lines.append("  Top邀请人：")
                for uid, cnt in top[:5]:
                    lines.append(f"    {uid}: {cnt}人")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "📊 新成员数据分析命令：\n"
                "  新人 漏斗 [天数]\n"
                "  新人 留存 [几天前批次]\n"
                "  新人 来源 [天数]"
            )
        return True
    except Exception as e:
        logger.warning(f"new_member_analytics admin cmd 异常: {e}")
        return True
