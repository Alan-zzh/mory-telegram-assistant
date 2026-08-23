# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/sales_center.py  ·  群销售中心（管理员商品管理）              ║
║                                                                        ║
║  职责边界（v5.39.0 治理后）：                                           ║
║    - 仅保留管理员商品管理命令（/sales 商品 列表|添加|上架|下架|删除…）  ║
║    - 不在 Bot 内收款、不创建订单、不做线下收款回执                      ║
║      （与 core/handlers/business_handlers.py 的“仅观测”定位一致）       ║
║    - 面向用户的咨询承接统一走 P7.5 搭讪 / P10 AI 主链的单目标漏斗，      ║
║      本模块不再有独立的用户侧触发词和固定回复                           ║
║                                                                        ║
║  历史：旧版 handle_price_request / handle_my_orders / handle_callback   ║
║  / build_product_keyboard 为无调用方的死代码，且含“付款后告诉我订单号”  ║
║  这类与项目事实矛盾的线下收款流程，已整体移除。                         ║
║                                                                        ║
║  默认关闭：SALES_CENTER_CONFIG.enabled = false                          ║
║  被调用：core/handlers/command_handlers.py → /sales                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.logging_util import get_logger

logger = get_logger("sales_center")

DEFAULT_CONFIG = {
    "enabled": False,
    "commission_rate": 0.1,
    "auto_track_events": True,
    "show_price_in_group": False,
    "notify_admin_on_order": True,
    "daily_sales_report": False,
    "cart_expire_hours": 24,
}


def _get_config(config: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    user_cfg = config.get("SALES_CENTER_CONFIG", {})
    merged.update(user_cfg)
    return merged


def _is_enabled(config: dict) -> bool:
    return _get_config(config).get("enabled", False)


# ───────────────────── 销售事件追踪 ─────────────────────
def track_event(db, uid: int, event: str, chat_id: int = 0,
                product_id: int = 0, value: float = 0, note: str = ""):
    """记录销售漏斗事件（带容错，静默失败）"""
    try:
        if hasattr(db, 'sales'):
            db.sales.track_sales_event(uid, event, chat_id, product_id, value, note)
    except Exception as e:
        logger.debug(f"track_sales_event 失败: {e}")


# ───────────────────── 管理员命令 ─────────────────────
def handle_admin_product_cmd(bot, m, config: dict, db, args: list) -> bool:
    """
    管理员商品管理命令
    格式：商品 上架|下架|列表|添加|删除 ...
    """
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
            products = db.sales.list_products(active_only=False) if hasattr(db, 'sales') else []
            if not products:
                bot.reply_to(m, "暂无商品")
                return True
            lines = ["📦 商品列表："]
            for p in products:
                status = "✅" if p[7] else "❌"
                lines.append(f"  #{p[0]} {status} {p[1]} ¥{p[4]} (库存:{p[6]})")
            bot.reply_to(m, "\n".join(lines))

        elif cmd == "上架" and len(args) >= 2:
            pid = int(args[1])
            db.sales.update_product(pid, is_active=1)
            bot.reply_to(m, f"✅ 商品 #{pid} 已上架")

        elif cmd == "下架" and len(args) >= 2:
            pid = int(args[1])
            db.sales.update_product(pid, is_active=0)
            bot.reply_to(m, f"✅ 商品 #{pid} 已下架")

        elif cmd == "删除" and len(args) >= 2:
            pid = int(args[1])
            db.sales.update_product(pid, is_active=0)
            bot.reply_to(m, f"✅ 商品 #{pid} 已删除（标记下架）")

        elif cmd == "添加" and len(args) >= 4:
            # 商品 添加 名称 价格 分类
            name = args[1]
            price = float(args[2])
            category = args[3] if len(args) > 3 else "default"
            desc = " ".join(args[4:]) if len(args) > 4 else ""
            pid = db.sales.add_product(name, price, category, desc)
            bot.reply_to(m, f"✅ 已添加商品 #{pid}: {name} ¥{price}")

        elif cmd == "统计":
            stats = db.sales.get_order_stats(30) if hasattr(db, 'sales') else {}
            bot.reply_to(m,
                f"📊 近{stats.get('days',30)}天销售统计：\n"
                f"  订单数：{stats.get('total_orders',0)}\n"
                f"  GMV：¥{stats.get('total_gmv',0)}\n"
                f"  付款订单：{stats.get('paid_orders',0)}\n"
                f"  付款金额：¥{stats.get('paid_amount',0)}\n"
                f"  转化率：{stats.get('conversion_rate',0)}%"
            )

        elif cmd == "漏斗":
            funnel = db.sales.get_funnel_stats(7) if hasattr(db, 'sales') else {}
            lines = ["📈 7日销售漏斗："]
            stage_names = {"view": "浏览", "click": "点击", "consult": "咨询", "cart": "加购", "pay": "付款"}
            for k, v in stage_names.items():
                lines.append(f"  {v}：{funnel.get(k, 0)} 人")
            rates = funnel.get("stage_rates", {})
            if rates:
                lines.append("")
                lines.append("阶段转化率：")
                for k, v in rates.items():
                    lines.append(f"  {k}: {v}%")
            bot.reply_to(m, "\n".join(lines))

        else:
            bot.reply_to(m,
                "📦 商品管理命令：\n"
                "  商品 列表\n"
                "  商品 添加 名称 价格 分类 [描述]\n"
                "  商品 上架 <id>\n"
                "  商品 下架 <id>\n"
                "  商品 删除 <id>\n"
                "  商品 统计\n"
                "  商品 漏斗"
            )
        return True
    except Exception as e:
        logger.warning(f"handle_admin_product_cmd 异常: {e}")
        bot.reply_to(m, f"❌ 操作失败: {str(e)[:50]}")
        return True


# command_handlers.py 的 /sales 统一入口按 handle_admin_cmd 命名导入；
# 此别名保证 /sales 不再因 ImportError 静默失败。
handle_admin_cmd = handle_admin_product_cmd
