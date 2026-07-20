# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/managed_groups.py  ·  托管管理（多群代运营）                  ║
║                                                                        ║
║  功能：统一管理多个托管群组，支持不同客户的群组独立配置               ║
║                                                                        ║
║  托管群组管理：                                                         ║
║    - 添加/删除托管群组                                                 ║
║    - 客户信息绑定（客户ID/联系人/到期时间）                            ║
║    - 套餐等级（基础版/标准版/专业版/定制版）                           ║
║                                                                        ║
║  功能开关矩阵：                                                         ║
║    - 每个托管群可独立配置功能开关                                       ║
║    - 广告检测/欢迎语/积分/抽奖/主动消息等分别开关                     ║
║    - 按套餐等级限制可用功能数量                                        ║
║                                                                        ║
║  数据隔离：                                                             ║
║    - 各托管群数据独立统计                                               ║
║    - 客户维度的报表汇总                                                ║
║    - 到期提醒                                                          ║
║                                                                        ║
║  默认关闭：MANAGED_GROUPS_CONFIG.enabled = false                      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from datetime import datetime, timezone, timedelta

from core.logging_util import get_logger

logger = get_logger("managed_groups")

_CST = timezone(timedelta(hours=8))

DEFAULT_CONFIG = {
    "enabled": False,
    "notify_expire_days": [30, 7, 1],   # 到期前多少天提醒
    "trial_days": 7,                    # 试用天数
}

# 套餐定义：可用功能列表
PLAN_FEATURES = {
    "basic": ["welcome", "antiflood", "banned_words", "auto_reply"],
    "standard": ["welcome", "antiflood", "banned_words", "auto_reply",
                 "verification", "lottery", "points", "ad_detect_basic"],
    "pro": ["welcome", "antiflood", "banned_words", "auto_reply",
            "verification", "lottery", "points", "ad_detect_full",
            "proactive_engage", "ai_chat", "custom_commands", "nsfw_detect"],
    "enterprise": ["all"],  # 全部功能
}

PLAN_NAMES = {
    "basic": "基础版",
    "standard": "标准版",
    "pro": "专业版",
    "enterprise": "定制版",
}


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("MANAGED_GROUPS_CONFIG", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 托管群 CRUD ─────────────────────
def add_managed_group(db, chat_id: int, group_name: str, customer_id: str,
                      plan: str = "basic", expire_at: int = 0,
                      contact: str = "", note: str = "") -> int:
    """添加托管群组"""
    now = int(time.time())
    if expire_at == 0:
        # 默认试用
        expire_at = now + _get_config({}).get("trial_days", 7) * 86400
    with db.lock:
        cur = db.conn.execute(
            """INSERT INTO managed_groups (chat_id, group_name, customer_id, plan, status, expire_at, contact, note, created_at, updated_at)
               VALUES (?,?,?,?, 'active',?,?,?,?,?)""",
            (chat_id, group_name, customer_id, plan, expire_at, contact, note, now, now)
        )
        db.conn.commit()
        return cur.lastrowid


def update_managed_group(db, mg_id: int, **kwargs) -> bool:
    """更新托管群信息"""
    if not kwargs:
        return False
    kwargs["updated_at"] = int(time.time())
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [mg_id]
    with db.lock:
        db.conn.execute(f"UPDATE managed_groups SET {sets} WHERE id=?", vals)
        db.conn.commit()
        return True


def list_managed_groups(db, status: str = None, customer_id: str = None) -> list:
    """列出托管群组"""
    q = "SELECT id, chat_id, group_name, customer_id, plan, status, expire_at, contact, created_at FROM managed_groups WHERE 1=1"
    params = []
    if status:
        q += " AND status=?"
        params.append(status)
    if customer_id:
        q += " AND customer_id=?"
        params.append(customer_id)
    q += " ORDER BY id DESC"
    with db.lock:
        return db.conn.execute(q, params).fetchall()


def get_managed_group(db, chat_id: int) -> dict:
    """获取单个托管群信息"""
    with db.lock:
        row = db.conn.execute(
            "SELECT id, chat_id, group_name, customer_id, plan, status, expire_at, contact, note FROM managed_groups WHERE chat_id=?",
            (chat_id,)
        ).fetchone()
        if not row:
            return {}
        return {
            "id": row[0], "chat_id": row[1], "group_name": row[2],
            "customer_id": row[3], "plan": row[4], "status": row[5],
            "expire_at": row[6], "contact": row[7], "note": row[8]
        }


def is_feature_enabled(db, chat_id: int, feature: str) -> bool:
    """检查某托管群的某功能是否可用"""
    mg = get_managed_group(db, chat_id)
    if not mg or mg.get("status") != "active":
        return False
    plan = mg.get("plan", "basic")
    features = PLAN_FEATURES.get(plan, [])
    if "all" in features:
        return True
    # 检查功能开关（如果有单独配置）
    try:
        row = db.conn.execute(
            "SELECT enabled FROM managed_group_features WHERE mg_id=? AND feature=?",
            (mg["id"], feature)
        ).fetchone()
        if row:
            return bool(row[0])
    except Exception:
        pass
    return feature in features


def set_feature_enabled(db, mg_id: int, feature: str, enabled: bool) -> bool:
    """设置托管群功能开关"""
    now = int(time.time())
    with db.lock:
        db.conn.execute(
            """INSERT INTO managed_group_features (mg_id, feature, enabled, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(mg_id, feature) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at""",
            (mg_id, feature, 1 if enabled else 0, now)
        )
        db.conn.commit()
        return True


# ───────────────────── 到期检查与提醒 ─────────────────────
def check_expiring_groups(db) -> list:
    """检查即将到期的托管群"""
    now = int(time.time())
    cfg = _get_config({})
    notify_days = cfg.get("notify_expire_days", [7])
    results = []
    for days in notify_days:
        cutoff = now + days * 86400
        try:
            with db.lock:
                rows = db.conn.execute(
                    """SELECT id, chat_id, group_name, customer_id, plan, expire_at
                       FROM managed_groups WHERE status='active' AND expire_at<=? AND expire_at>?""",
                    (cutoff, now)
                ).fetchall()
                for r in rows:
                    results.append({
                        "id": r[0], "chat_id": r[1], "group_name": r[2],
                        "customer_id": r[3], "plan": r[4], "expire_at": r[5],
                        "days_left": days
                    })
        except Exception as e:
            logger.warning(f"检查到期群组失败: {e}")
    return results


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_cmd(bot, m, config: dict, db, args: list) -> bool:
    """管理员托管管理命令"""
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
            groups = list_managed_groups(db)
            if not groups:
                bot.reply_to(m, "暂无托管群组")
                return True
            lines = ["📋 托管群组列表："]
            for g in groups:
                plan_name = PLAN_NAMES.get(g[4], g[4])
                expire = datetime.fromtimestamp(g[6], _CST).strftime("%Y-%m-%d") if g[6] else "永久"
                lines.append(f"  #{g[0]} [{g[5]}] {g[2]} ({plan_name}) 到期:{expire}")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "添加" and len(args) >= 4:
            # 托管 添加 <chat_id> <群名> <客户ID> [套餐] [天数]
            chat_id = int(args[1])
            group_name = args[2]
            customer_id = args[3]
            plan = args[4] if len(args) > 4 else "basic"
            days = int(args[5]) if len(args) > 5 else 7
            expire_at = int(time.time()) + days * 86400
            mg_id = add_managed_group(db, chat_id, group_name, customer_id, plan, expire_at)
            bot.reply_to(m, f"✅ 已添加托管群 #{mg_id}: {group_name}")

        elif cmd == "删除" and len(args) >= 2:
            mg_id = int(args[1])
            update_managed_group(db, mg_id, status="cancelled")
            bot.reply_to(m, f"✅ 已取消托管 #{mg_id}")

        elif cmd == "续费" and len(args) >= 3:
            mg_id = int(args[1])
            days = int(args[2])
            row = db.conn.execute("SELECT expire_at FROM managed_groups WHERE id=?", (mg_id,)).fetchone()
            if row:
                new_expire = max(row[0], int(time.time())) + days * 86400
                update_managed_group(db, mg_id, expire_at=new_expire)
                date = datetime.fromtimestamp(new_expire, _CST).strftime("%Y-%m-%d")
                bot.reply_to(m, f"✅ 续费成功，新到期日：{date}")

        elif cmd == "套餐" and len(args) >= 3:
            mg_id = int(args[1])
            plan = args[2]
            update_managed_group(db, mg_id, plan=plan)
            bot.reply_to(m, f"✅ 套餐已更改为：{PLAN_NAMES.get(plan, plan)}")

        elif cmd == "功能" and len(args) >= 4:
            # 托管 功能 <mg_id> <feature> on/off
            mg_id = int(args[1])
            feature = args[2]
            enabled = args[3] in ("on", "1", "true", "开启")
            set_feature_enabled(db, mg_id, feature, enabled)
            bot.reply_to(m, f"✅ 功能 {feature} 已{'开启' if enabled else '关闭'}")

        elif cmd == "到期":
            expiring = check_expiring_groups(db)
            if not expiring:
                bot.reply_to(m, "✅ 近期没有到期的托管群")
                return True
            lines = ["⏰ 即将到期："]
            for e in expiring:
                plan_name = PLAN_NAMES.get(e["plan"], e["plan"])
                lines.append(f"  {e['group_name']} ({plan_name}) 还剩{e['days_left']}天")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "📋 托管管理命令：\n"
                "  托管 列表\n"
                "  托管 添加 <chat_id> <群名> <客户ID> [套餐] [天数]\n"
                "  托管 删除 <id>\n"
                "  托管 续费 <id> <天数>\n"
                "  托管 套餐 <id> <plan>\n"
                "  托管 功能 <id> <feature> on/off\n"
                "  托管 到期\n\n"
                "套餐：basic/standard/pro/enterprise"
            )
        return True
    except Exception as e:
        logger.warning(f"managed_groups admin cmd 异常: {e}")
        bot.reply_to(m, f"❌ 操作失败: {str(e)[:50]}")
        return True
