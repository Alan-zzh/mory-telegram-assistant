"""
商城系统 - 积分兑换商品 + 商品管理 + 兑换记录

功能：
  1. 展示商城商品列表（积分价格、库存、描述）
  2. 用户积分兑换商品（扣积分 + 扣库存 + 记录兑换）
  3. 管理员商品管理（上架/下架/查看订单）

命令：
  商城 → handle_shop_list
  兑换 商品名 → handle_exchange
  上架 商品名 积分 [库存] [描述] → handle_shop_admin(action="add")
  下架 商品名 → handle_shop_admin(action="remove")
  订单 → handle_shop_admin(action="orders")

数据表：
  shop_items（id, name, points_cost, stock, description, category, enabled, ts）
  exchange_records（id, uid, item_id, item_name, points_cost, ts, status）
"""
import time
from datetime import datetime, timezone, timedelta

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("shop")

# 北京时间
_CST = timezone(timedelta(hours=8))


def handle_shop_list(bot, m, config, db):
    """展示商城商品列表"""
    try:
        rows = db.conn.execute(
            "SELECT id, name, points_cost, stock, description FROM shop_items WHERE enabled=1 ORDER BY points_cost"
        ).fetchall()

        if not rows:
            bot.reply_to(m, "🏪 商城暂无商品")
            return

        text = "🏪 积分商城\n━━━━━━━━━━━━━\n"
        for item_id, name, cost, stock, desc in rows:
            stock_text = "∞" if stock == -1 else str(stock)
            text += f"📦 {name}\n   💰 {cost}积分 | 库存：{stock_text}\n"
            if desc:
                text += f"   📝 {desc}\n"
            text += "\n"
        text += "💡 发送「兑换 商品名」即可兑换"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"商城列表异常: {e}")


def handle_exchange(bot, m, config, db, item_name):
    """兑换商品"""
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    try:
        # 查找商品
        item = db.conn.execute(
            "SELECT id, name, points_cost, stock FROM shop_items WHERE name=? AND enabled=1",
            (item_name,)
        ).fetchone()

        if not item:
            bot.reply_to(m, f"❌ 未找到商品「{item_name}」")
            return

        item_id, name, cost, stock = item

        # 等级折扣
        from modules.points_enhanced import _get_applicable_privilege
        discount = _get_applicable_privilege(db, uid, "shop_discount", config)
        original_cost = cost
        if discount is not None and discount < 1.0:
            cost = max(1, int(cost * discount))

        # 检查库存
        if stock == 0:
            bot.reply_to(m, f"❌ 「{name}」已售罄")
            return

        # 检查积分
        user_points = db.get_user_points(uid)
        if user_points is None or user_points < cost:
            current = user_points if user_points is not None else 0
            bot.reply_to(
                m,
                f"❌ 积分不足！\n💰 当前积分：{current}\n💰 所需积分：{cost}\n差额：{cost - current}"
            )
            return

        # 先扣积分，再扣库存 + 记录兑换（原子操作）
        now_ts = int(time.time())
        with _db_lock:
            # 再次检查库存（防止并发超卖）
            current_stock = db.conn.execute(
                "SELECT stock FROM shop_items WHERE id=?", (item_id,)
            ).fetchone()
            if current_stock and current_stock[0] == 0:
                bot.reply_to(m, f"❌ 「{name}」已售罄")
                return

            # 扣积分（原子操作：WHERE points >= ? 防止并发下积分变负数）
            # 注意：redpacket/blind_box/tip 用 db.lock 原子扣分，与 shop._db_lock 不同锁
            # 必须用原子 SQL 防止"锁外检查通过→他线程扣分→锁内扣分变负数"
            cur = db.conn.execute(
                "UPDATE user_levels SET points=points-? WHERE uid=? AND points >= ?",
                (cost, uid, cost)
            )
            if cur.rowcount == 0:
                # 并发下积分已被其他线程扣光（如红包/盲盒/打赏原子扣减）
                db.conn.rollback()
                bot.reply_to(m, f"❌ 积分不足！兑换失败（并发竞争，请重试）")
                return

            # 扣库存
            if current_stock and current_stock[0] > 0:
                db.conn.execute("UPDATE shop_items SET stock=stock-1 WHERE id=?", (item_id,))

            # 记录兑换
            db.conn.execute(
                "INSERT INTO exchange_records (uid, item_id, item_name, points_cost, ts, status) VALUES (?,?,?,?,?,?)",
                (uid, item_id, name, cost, now_ts, "pending")
            )

            # 记录积分日志（points_log schema: id, uid, change_amount, balance_after, source, ts）
            balance_after = db.get_user_points(uid) or 0
            db.conn.execute(
                "INSERT INTO points_log (uid, change_amount, balance_after, source, ts) VALUES (?,?,?,?,?)",
                (uid, -cost, balance_after, f"兑换:{name}", now_ts)
            )
            db.conn.commit()

        remaining_points = db.get_user_points(uid)
        discount_info = ""
        if discount is not None and discount < 1.0:
            discount_info = f"🏷 等级折扣：{original_cost}→{cost}（{int(discount*100)}%）\n"
        bot.reply_to(
            m,
            f"✅ 兑换成功！\n📦 商品：{name}\n💰 消耗积分：{cost}\n"
            f"{discount_info}"
            f"💎 剩余积分：{remaining_points if remaining_points is not None else 0}\n\n"
            f"⏳ 管理员将尽快处理发货"
        )

        # 通知管理员
        admin_id = config.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(
                    admin_id,
                    f"📦 新的兑换订单\n👤 用户：{uname}(id={uid})\n📦 商品：{name}\n💰 积分：{cost}"
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        logger.info(f"兑换: uid={uid} item={name} cost={cost}")

    except Exception as e:
        logger.error(f"兑换异常: {e}")
        bot.reply_to(m, "❌ 兑换失败，请稍后再试")


def handle_shop_admin(bot, m, config, db, action, args):
    """管理员商品管理"""
    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可操作")
        return

    try:
        if action == "add":
            # 上架 商品名 积分 [库存] [描述]
            if len(args) < 2:
                bot.reply_to(m, "格式：上架 商品名 积分 [库存] [描述]")
                return
            name = args[0]
            try:
                cost = int(args[1])
            except ValueError:
                bot.reply_to(m, "❌ 积分必须是数字")
                return
            stock = -1
            if len(args) > 2:
                try:
                    stock = int(args[2])
                except ValueError:
                    stock = -1
            desc = " ".join(args[3:]) if len(args) > 3 else ""
            now_ts = int(time.time())
            with _db_lock:
                db.conn.execute(
                    "INSERT INTO shop_items (name, points_cost, stock, description, enabled, ts) VALUES (?,?,?,?,1,?)",
                    (name, cost, stock, desc, now_ts)
                )
                db.conn.commit()
            stock_text = "无限" if stock == -1 else str(stock)
            bot.reply_to(m, f"✅ 商品「{name}」已上架（{cost}积分，库存{stock_text}）")

        elif action == "remove":
            if not args:
                bot.reply_to(m, "格式：下架 商品名")
                return
            with _db_lock:
                db.conn.execute("UPDATE shop_items SET enabled=0 WHERE name=?", (args[0],))
                db.conn.commit()
            bot.reply_to(m, f"✅ 商品「{args[0]}」已下架")

        elif action == "orders":
            rows = db.conn.execute(
                "SELECT uid, item_name, points_cost, ts, status FROM exchange_records ORDER BY ts DESC LIMIT 10"
            ).fetchall()
            if not rows:
                bot.reply_to(m, "📋 暂无兑换记录")
                return
            text = "📋 最近兑换记录\n━━━━━━━━━━━━━\n"
            for r_uid, r_name, r_cost, r_ts, r_status in rows:
                t = datetime.fromtimestamp(r_ts, _CST).strftime("%m-%d %H:%M")
                text += f"👤 {r_uid} | 📦 {r_name} | 💰 {r_cost} | {r_status} | {t}\n"
            bot.reply_to(m, text)

        else:
            bot.reply_to(m, f"❌ 未知操作：{action}")

    except Exception as e:
        logger.error(f"商城管理异常: {e}")
        bot.reply_to(m, "❌ 操作失败")


def handle_ship_order(bot, m, config, db, order_id):
    """管理员发货（pending→shipped）"""
    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可操作")
        return

    try:
        order_id = int(order_id)
    except (ValueError, TypeError):
        bot.reply_to(m, "❌ 订单号必须是数字")
        return

    try:
        order = db.conn.execute(
            "SELECT id, uid, item_name, status FROM exchange_records WHERE id=?",
            (order_id,)
        ).fetchone()

        if not order:
            bot.reply_to(m, f"❌ 订单#{order_id}不存在")
            return

        if order[3] != "pending":
            bot.reply_to(m, f"❌ 订单#{order_id}当前状态为「{order[3]}」，无法发货（仅待发货状态可发货）")
            return

        with _db_lock:
            db.conn.execute("UPDATE exchange_records SET status='shipped' WHERE id=?", (order_id,))
            db.conn.commit()

        bot.reply_to(m, f"✅ 订单#{order_id}已发货\n📦 商品：{order[2]}")

        # 通知用户
        try:
            bot.send_message(order[1], f"📦 您的订单已发货！\n📦 商品：{order[2]}")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        logger.info(f"发货: order_id={order_id} item={order[2]}")

    except Exception as e:
        logger.error(f"发货异常: {e}")
        bot.reply_to(m, "❌ 发货操作失败")


def handle_complete_order(bot, m, config, db, order_id):
    """管理员完成订单（shipped→completed）"""
    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可操作")
        return

    try:
        order_id = int(order_id)
    except (ValueError, TypeError):
        bot.reply_to(m, "❌ 订单号必须是数字")
        return

    try:
        order = db.conn.execute(
            "SELECT id, uid, item_name, status FROM exchange_records WHERE id=?",
            (order_id,)
        ).fetchone()

        if not order:
            bot.reply_to(m, f"❌ 订单#{order_id}不存在")
            return

        if order[3] != "shipped":
            bot.reply_to(m, f"❌ 订单#{order_id}当前状态为「{order[3]}」，无法完成（仅已发货状态可完成）")
            return

        with _db_lock:
            db.conn.execute("UPDATE exchange_records SET status='completed' WHERE id=?", (order_id,))
            db.conn.commit()

        bot.reply_to(m, f"✅ 订单#{order_id}已完成\n📦 商品：{order[2]}")

        # 通知用户
        try:
            bot.send_message(order[1], f"📦 您的订单已完成！\n📦 商品：{order[2]}")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        logger.info(f"完成订单: order_id={order_id} item={order[2]}")

    except Exception as e:
        logger.error(f"完成订单异常: {e}")
        bot.reply_to(m, "❌ 完成订单操作失败")


def handle_refund_order(bot, m, config, db, order_id):
    """管理员退款订单（任意状态→refunded + 退回积分）"""
    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可操作")
        return

    try:
        order_id = int(order_id)
    except (ValueError, TypeError):
        bot.reply_to(m, "❌ 订单号必须是数字")
        return

    try:
        order = db.conn.execute(
            "SELECT id, uid, item_name, points_cost, status FROM exchange_records WHERE id=?",
            (order_id,)
        ).fetchone()

        if not order:
            bot.reply_to(m, f"❌ 订单#{order_id}不存在")
            return

        if order[4] == "refunded":
            bot.reply_to(m, f"❌ 订单#{order_id}已退款，请勿重复操作")
            return

        # 退回积分
        db.add_points(order[1], order[3], source="shop_refund")

        with _db_lock:
            db.conn.execute("UPDATE exchange_records SET status='refunded' WHERE id=?", (order_id,))
            db.conn.commit()

        bot.reply_to(m, f"✅ 订单#{order_id}已退款\n📦 商品：{order[2]}\n💰 退回积分：{order[3]}")

        # 通知用户
        try:
            bot.send_message(order[1], f"📦 您的订单已退款\n📦 商品：{order[2]}\n💰 退回积分：{order[3]}")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        logger.info(f"退款: order_id={order_id} uid={order[1]} 退回={order[3]}积分")

    except Exception as e:
        logger.error(f"退款异常: {e}")
        bot.reply_to(m, "❌ 退款操作失败")


def handle_my_orders(bot, m, config, db):
    """用户查看自己的兑换记录"""
    uid = m.from_user.id

    try:
        rows = db.conn.execute(
            "SELECT id, item_name, points_cost, ts, status FROM exchange_records WHERE uid=? ORDER BY ts DESC LIMIT 10",
            (uid,)
        ).fetchall()

        if not rows:
            bot.reply_to(m, "📋 您暂无兑换记录")
            return

        status_map = {
            "pending": "⏳ 待发货",
            "shipped": "🚚 已发货",
            "completed": "✅ 已完成",
            "refunded": "💰 已退款"
        }

        text = "📋 我的兑换记录\n━━━━━━━━━━━━━\n"
        for order_id, item_name, cost, ts, status in rows:
            t = datetime.fromtimestamp(ts, _CST).strftime("%m-%d %H:%M")
            status_text = status_map.get(status, status)
            text += f"#{order_id} {item_name} | 💰{cost} | {status_text} | {t}\n"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"查询兑换记录异常: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")
