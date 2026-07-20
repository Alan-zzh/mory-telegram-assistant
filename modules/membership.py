# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/membership.py  ·  网编会员（付费订阅管理）                    ║
║                                                                      ║
║  功能：会员等级订阅管理系统                                           ║
║                                                                      ║
║  会员等级：                                                           ║
║    - 免费用户（free）                                                 ║
║    - 基础会员（basic）- 月付                                          ║
║    - 高级会员（premium）- 季付                                        ║
║    - 至尊会员（vip）- 年付                                            ║
║                                                                      ║
║  会员权益：                                                           ║
║    - 专属身份标识/徽章                                               ║
║    - 每日积分奖励                                                     ║
║    - 专属内容访问权限                                                 ║
║    - 优先回复/专属客服                                                ║
║    - 抽奖加权                                                         ║
║    - 免广告                                                           ║
║                                                                      ║
║  订阅管理：                                                           ║
║    - 订阅/续费/升级/降级                                             ║
║    - 到期提醒                                                         ║
║    - 订阅历史记录                                                     ║
║                                                                      ║
║  默认关闭：MEMBERSHIP_CONFIG.enabled = false                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("membership")

_CST = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "enabled": False,
    "notify_expire_days": [7, 3, 1],
    "auto_extend": False,
    "daily_bonus_points": {
        "basic": 10,
        "premium": 30,
        "vip": 100,
    },
    "lottery_weight": {
        "free": 1,
        "basic": 2,
        "premium": 5,
        "vip": 10,
    },
}

# 会员等级定义
TIER_CONFIG = {
    "free": {
        "name": "免费用户",
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_yearly": 0,
        "badges": [],
        "features": ["基础聊天", "每日签到"],
    },
    "basic": {
        "name": "基础会员",
        "price_monthly": 29,
        "price_quarterly": 79,
        "price_yearly": 299,
        "badges": ["⭐"],
        "features": ["每日积分奖励", "专属徽章", "优先回复"],
    },
    "premium": {
        "name": "高级会员",
        "price_monthly": 59,
        "price_quarterly": 159,
        "price_yearly": 599,
        "badges": ["⭐⭐"],
        "features": ["基础会员全部", "专属内容访问", "抽奖加权5倍", "免广告"],
    },
    "vip": {
        "name": "至尊会员",
        "price_monthly": 0,
        "price_quarterly": 0,
        "price_yearly": 999,
        "badges": ["👑"],
        "features": ["高级会员全部", "专属一对一客服", "定制内容权限", "所有活动优先"],
    },
}


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("MEMBERSHIP_CONFIG", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 会员查询 ─────────────────────
def get_member_info(db, uid: int) -> dict:
    """获取用户会员信息"""
    try:
        with db.lock:
            row = db.conn.execute(
                """SELECT uid, tier, expire_at, sub_type, auto_renew, total_spent, joined_at
                   FROM user_membership WHERE uid=?""",
                (uid,)
            ).fetchone()
            if not row:
                return {"uid": uid, "tier": "free", "expire_at": 0, "sub_type": "",
                        "auto_renew": 0, "total_spent": 0, "is_active": False}
            tier = row[1]
            expire_at = row[2] or 0
            is_active = tier != "free" and (expire_at == 0 or expire_at > int(time.time()))
            return {
                "uid": row[0],
                "tier": tier,
                "expire_at": expire_at,
                "sub_type": row[3] or "",
                "auto_renew": row[4] or 0,
                "total_spent": row[5] or 0,
                "joined_at": row[6] or 0,
                "is_active": is_active,
                "tier_name": TIER_CONFIG.get(tier, {}).get("name", tier),
                "badges": TIER_CONFIG.get(tier, {}).get("badges", []),
            }
    except Exception as e:
        logger.debug(f"获取会员信息失败: {e}")
        return {"uid": uid, "tier": "free", "expire_at": 0, "is_active": False}


def is_member_active(db, uid: int, min_tier: str = "basic") -> bool:
    """检查用户是否是有效会员（等级 >= min_tier）"""
    info = get_member_info(db, uid)
    if not info.get("is_active"):
        return False
    tier_order = ["free", "basic", "premium", "vip"]
    user_level = tier_order.index(info["tier"]) if info["tier"] in tier_order else 0
    min_level = tier_order.index(min_tier) if min_tier in tier_order else 1
    return user_level >= min_level


# ───────────────────── 订阅管理 ─────────────────────
def set_membership(db, uid: int, tier: str, duration_days: int, amount: float = 0) -> dict:
    """设置/续费会员"""
    now = int(time.time())
    try:
        with db.lock:
            # 查现有记录
            row = db.conn.execute(
                "SELECT expire_at, total_spent FROM user_membership WHERE uid=?",
                (uid,)
            ).fetchone()

            if row and row[0] and row[0] > now:
                # 续期
                new_expire = row[0] + duration_days * 86400
                new_total = (row[1] or 0) + amount
            else:
                # 新订
                new_expire = now + duration_days * 86400
                new_total = amount

            db.conn.execute(
                """INSERT INTO user_membership (uid, tier, expire_at, sub_type, total_spent, joined_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(uid) DO UPDATE SET
                   tier=excluded.tier,
                   expire_at=excluded.expire_at,
                   total_spent=excluded.total_spent,
                   updated_at=excluded.updated_at""",
                (uid, tier, new_expire, "manual", new_total, now if not row else row[0], now)
            )

            # 记录订阅历史
            db.conn.execute(
                """INSERT INTO membership_subscriptions (uid, tier, duration_days, amount, sub_type, status, created_at)
                   VALUES (?,?,?,?,?, 'active', ?)""",
                (uid, tier, duration_days, amount, "manual", now)
            )
            db.conn.commit()

            return {
                "uid": uid,
                "tier": tier,
                "tier_name": TIER_CONFIG.get(tier, {}).get("name", tier),
                "expire_at": new_expire,
                "total_spent": new_total,
            }
    except Exception as e:
        logger.warning(f"设置会员失败: {e}")
        return {}


def cancel_membership(db, uid: int) -> bool:
    """取消会员（设为免费）"""
    try:
        with db.lock:
            db.conn.execute(
                "UPDATE user_membership SET tier='free', expire_at=0, updated_at=? WHERE uid=?",
                (int(time.time()), uid)
            )
            db.conn.commit()
            return True
    except Exception as e:
        logger.warning(f"取消会员失败: {e}")
        return False


# ───────────────────── 到期检查 ─────────────────────
def get_expiring_members(db, days: int = 7) -> list:
    """获取即将到期的会员"""
    now = int(time.time())
    cutoff = now + days * 86400
    try:
        with db.lock:
            rows = db.conn.execute(
                """SELECT uid, tier, expire_at FROM user_membership
                   WHERE tier!='free' AND expire_at>? AND expire_at<=?
                   ORDER BY expire_at ASC""",
                (now, cutoff)
            ).fetchall()
            return [{"uid": r[0], "tier": r[1], "expire_at": r[2],
                     "days_left": (r[2] - now) // 86400} for r in rows]
    except Exception as e:
        logger.warning(f"查询到期会员失败: {e}")
        return []


# ───────────────────── 会员列表 ─────────────────────
def list_members(db, tier: str = None, limit: int = 50) -> list:
    """列出会员"""
    q = "SELECT uid, tier, expire_at, total_spent FROM user_membership WHERE 1=1"
    params = []
    if tier:
        q += " AND tier=?"
        params.append(tier)
    q += " ORDER BY expire_at DESC LIMIT ?"
    params.append(limit)
    try:
        with db.lock:
            return db.conn.execute(q, params).fetchall()
    except Exception as e:
        logger.warning(f"列出会员失败: {e}")
        return []


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_cmd(bot, m, config: dict, db, args: list) -> bool:
    """管理员会员管理命令"""
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

    try:
        if cmd == "列表":
            tier = args[1] if len(args) > 1 else None
            members = list_members(db, tier)
            if not members:
                bot.reply_to(m, "暂无会员")
                return True
            lines = ["👑 会员列表："]
            for m_row in members:
                tier_name = TIER_CONFIG.get(m_row[1], {}).get("name", m_row[1])
                expire = datetime.fromtimestamp(m_row[2], _CST).strftime("%Y-%m-%d") if m_row[2] else "永久"
                lines.append(f"  {m_row[0]} - {tier_name} - 到期:{expire} - 累计¥{m_row[3]}")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "添加" and len(args) >= 4:
            # 会员 添加 <uid> <tier> <天数> [金额]
            target_uid = int(args[1])
            tier = args[2]
            days = int(args[3])
            amount = float(args[4]) if len(args) > 4 else 0
            result = set_membership(db, target_uid, tier, days, amount)
            if result:
                expire = datetime.fromtimestamp(result["expire_at"], _CST).strftime("%Y-%m-%d")
                bot.reply_to(m, f"✅ 已为 {target_uid} 添加 {result['tier_name']}\n到期：{expire}")
            else:
                bot.reply_to(m, "❌ 添加失败")

        elif cmd == "取消" and len(args) >= 2:
            target_uid = int(args[1])
            if cancel_membership(db, target_uid):
                bot.reply_to(m, f"✅ 已取消 {target_uid} 的会员")
            else:
                bot.reply_to(m, "❌ 取消失败")

        elif cmd == "查询" and len(args) >= 2:
            target_uid = int(args[1])
            info = get_member_info(db, target_uid)
            if info.get("tier") == "free":
                bot.reply_to(m, f"用户 {target_uid} 不是会员")
            else:
                expire = datetime.fromtimestamp(info["expire_at"], _CST).strftime("%Y-%m-%d") if info["expire_at"] else "永久"
                bot.reply_to(m,
                    f"👑 用户 {target_uid}\n"
                    f"  等级：{info.get('tier_name', info['tier'])}\n"
                    f"  到期：{expire}\n"
                    f"  累计消费：¥{info.get('total_spent', 0)}"
                )

        elif cmd == "到期":
            days = int(args[1]) if len(args) > 1 else 7
            expiring = get_expiring_members(db, days)
            if not expiring:
                bot.reply_to(m, f"✅ {days}天内无即将到期会员")
                return True
            lines = [f"⏰ {days}天内到期会员："]
            for e in expiring:
                tier_name = TIER_CONFIG.get(e["tier"], {}).get("name", e["tier"])
                lines.append(f"  {e['uid']} - {tier_name} - 还剩{e['days_left']}天")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "👑 会员管理命令：\n"
                "  会员 列表 [等级]\n"
                "  会员 添加 <uid> <tier> <天数> [金额]\n"
                "  会员 取消 <uid>\n"
                "  会员 查询 <uid>\n"
                "  会员 到期 [天数]\n\n"
                "等级：basic/premium/vip"
            )
        return True
    except Exception as e:
        logger.warning(f"membership admin cmd 异常: {e}")
        bot.reply_to(m, f"❌ 操作失败: {str(e)[:50]}")
        return True


def handle_user_query(mory_bot, m, config: dict, db) -> bool:
    """用户查询自己的会员状态"""
    if not _is_enabled(config):
        return False

    msg = (m.text or "").strip()
    if "我的会员" not in msg and "会员状态" not in msg:
        return False

    uid = m.from_user.id
    info = get_member_info(db, uid)

    if info.get("tier") == "free":
        mory_bot.reply_and_track(m,
            "你还不是会员哦～\n"
            "会员有专属徽章、每日积分、优先回复好多福利呢。"
        )
    else:
        expire = datetime.fromtimestamp(info["expire_at"], _CST).strftime("%Y-%m-%d") if info.get("expire_at") else "永久"
        badges = " ".join(info.get("badges", []))
        mory_bot.reply_and_track(m,
            f"{badges} {info.get('tier_name', info['tier'])}\n"
            f"到期时间：{expire}\n"
            f"累计消费：¥{info.get('total_spent', 0)}\n\n"
            f"谢谢支持呀～"
        )
    return True
