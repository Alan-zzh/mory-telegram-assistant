# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/sales_center.py  ·  群销售中心                               ║
║                                                                        ║
║  功能：完整的群内销售转化管理系统                                     ║
║                                                                        ║
║  商品管理：                                                             ║
║    - 商品上架/下架/编辑                                                ║
║    - 分类管理                                                          ║
║    - 库存管理                                                          ║
║                                                                        ║
║  订单管理：                                                             ║
║    - 创建/查询订单                                                     ║
║    - 订单状态流转（pending→paid→shipped→completed）                   ║
║    - 退款/取消                                                         ║
║                                                                        ║
║  销售漏斗：                                                             ║
║    - 浏览→点击→咨询→加购→付款 5阶段追踪                               ║
║    - 阶段转化率计算                                                    ║
║    - 流失点分析                                                        ║
║                                                                        ║
║  分销佣金：                                                             ║
║    - 推荐人绑定                                                        ║
║    - 佣金自动计算                                                      ║
║    - 佣金结算                                                          ║
║                                                                        ║
║  群内触发：                                                             ║
║    - 价格/内容咨询 → 预览；明确购买/下单 → 自助订阅                    ║
║    - 管理员发"上架"/"下架" → 商品管理                                 ║
║    - "我的订单" → 个人订单查询                                         ║
║                                                                        ║
║  默认关闭：SALES_CENTER_CONFIG.enabled = false                        ║
║  被调用：main.py → 商业意图检测模块                                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import re
from datetime import datetime, timezone, timedelta

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.logging_util import get_logger

logger = get_logger("sales_center")

_CST = timezone(timedelta(hours=8))

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


# ───────────────────── 商品展示 ─────────────────────
def build_product_keyboard(products: list, page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    """构建商品列表内联键盘"""
    kb = InlineKeyboardMarkup()
    start = page * page_size
    end = start + page_size
    for p in products[start:end]:
        pid = p[0]
        name = p[1]
        price = p[4]
        kb.add(InlineKeyboardButton(f"🛍 {name} - ¥{price}", callback_data=f"prod_view_{pid}"))
    # 翻页
    total = len(products)
    total_pages = (total + page_size - 1) // page_size
    if total_pages > 1:
        row = []
        if page > 0:
            row.append(InlineKeyboardButton("⬅ 上一页", callback_data=f"prod_page_{page-1}"))
        row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="prod_nop"))
        if page < total_pages - 1:
            row.append(InlineKeyboardButton("下一页 ➡", callback_data=f"prod_page_{page+1}"))
        kb.add(*row)
    return kb


def format_product_detail(product: dict) -> str:
    """格式化商品详情"""
    stock_text = "现货充足" if product.get("stock", -1) == -1 else f"仅剩 {product['stock']} 件"
    return (
        f"🛍 <b>{product['name']}</b>\n"
        f"💰 价格：¥{product['price']}\n"
        f"📦 库存：{stock_text}\n"
        f"📝 {product.get('description', '暂无描述')}\n"
    )


# ───────────────────── 销售事件追踪 ─────────────────────
def track_event(db, uid: int, event: str, chat_id: int = 0,
                product_id: int = 0, value: float = 0, note: str = ""):
    """记录销售漏斗事件（带容错，静默失败）"""
    try:
        if hasattr(db, 'sales'):
            db.sales.track_sales_event(uid, event, chat_id, product_id, value, note)
    except Exception as e:
        logger.debug(f"track_sales_event 失败: {e}")


# ───────────────────── 群内触发处理 ─────────────────────
def handle_price_request(mory_bot, m, config: dict, db) -> bool:
    """
    处理"价格表"/"买"/"多少钱"等购买意图。

    ReplyContract v1：了解阶段只给预览，明确购买才给自助订阅；
    不在群里展示价格/商品承诺，也不主动引导私聊。
    返回 True 表示已消费消息
    """
    if not _is_enabled(config):
        return False

    msg = (m.text or "").strip()
    uid = m.from_user.id
    chat_id = m.chat.id

    # 触发关键词
    trigger_words = ["价格表", "价目表", "多少钱", "怎么买", "购买", "下单", "商品"]
    if not any(w in msg for w in trigger_words):
        return False

    try:
        # 记录浏览事件
        track_event(db, uid, "view", chat_id, note=msg)

        from core.growth_optimizer import resolve_conversion_target

        target, _ = resolve_conversion_target(msg, mode="convert")
        if target == "none" and msg in {"购买", "下单"}:
            target = "subscribe"
        if target == "subscribe":
            reply = (
                "想继续的话去 @MorychannelBot 看当前可选内容和档位，"
                "按提示自助完成。"
            )
        else:
            reply = "想先了解的话去 @moryselect 看预览，合不合适你自己判断。"
        mory_bot.reply_and_track(m, reply)
        return True
    except Exception as e:
        logger.warning(f"handle_price_request 异常: {e}")
        return False


def handle_my_orders(mory_bot, m, config: dict, db) -> bool:
    """处理'我的订单'查询"""
    if not _is_enabled(config):
        return False

    msg = (m.text or "").strip()
    if "我的订单" not in msg and "订单查询" not in msg:
        return False

    uid = m.from_user.id
    try:
        orders = db.sales.get_user_orders(uid) if hasattr(db, 'sales') else []
        if not orders:
            mory_bot.reply_and_track(m, "你还没有订单哦～")
            return True
        lines = ["📋 你的订单："]
        for o in orders[:10]:
            status_map = {
                "pending": "⏳ 待付款", "paid": "✅ 已付款",
                "shipped": "📦 已发货", "completed": "🎉 已完成",
                "refunded": "↩️ 已退款", "cancelled": "❌ 已取消"
            }
            status = status_map.get(o[5], o[5])
            date = datetime.fromtimestamp(o[7], _CST).strftime("%m-%d %H:%M") if o[7] else ""
            lines.append(f"  • {o[3]} ¥{o[4]} {status} {date}")
        mory_bot.reply_and_track(m, "\n".join(lines))
        return True
    except Exception as e:
        logger.warning(f"handle_my_orders 异常: {e}")
        return False


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
    chat_id = m.chat.id

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


# ───────────────────── 回调处理 ─────────────────────
def handle_callback(bot, call, config: dict, db) -> bool:
    """处理内联键盘回调"""
    if not _is_enabled(config):
        return False

    data = call.data or ""
    uid = call.from_user.id
    chat_id = call.message.chat.id if call.message else 0

    try:
        if data.startswith("prod_view_"):
            pid = int(data.replace("prod_view_", ""))
            product = db.sales.get_product(pid) if hasattr(db, 'sales') else {}
            if not product:
                bot.answer_callback_query(call.id, "商品不存在")
                return True
            track_event(db, uid, "click", chat_id, product_id=pid)
            text = format_product_detail(product)
            kb = InlineKeyboardMarkup()
            kb.add(
                InlineKeyboardButton("🛒 下单", callback_data=f"prod_buy_{pid}"),
                InlineKeyboardButton("💬 咨询", callback_data=f"prod_ask_{pid}"),
            )
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=kb, parse_mode="HTML")
            return True

        elif data.startswith("prod_buy_"):
            pid = int(data.replace("prod_buy_", ""))
            product = db.sales.get_product(pid) if hasattr(db, 'sales') else {}
            if not product:
                bot.answer_callback_query(call.id, "商品不存在")
                return True
            track_event(db, uid, "cart", chat_id, product_id=pid, value=product.get("price", 0))
            order_id = db.sales.create_order(uid, pid, product["price"], chat_id, source="inline")
            bot.answer_callback_query(call.id, "已为你创建订单，请私聊完成付款")
            bot.send_message(uid,
                f"🛒 已为你创建订单 #{order_id}\n"
                f"商品：{product['name']}\n"
                f"金额：¥{product['price']}\n\n"
                f"付款后告诉我订单号就好啦～"
            )
            return True

        elif data.startswith("prod_page_"):
            page = int(data.replace("prod_page_", ""))
            products = db.sales.list_products(active_only=True) if hasattr(db, 'sales') else []
            kb = build_product_keyboard(products, page)
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=kb)
            return True

    except Exception as e:
        logger.warning(f"sales_center callback 异常: {e}")

    return False
