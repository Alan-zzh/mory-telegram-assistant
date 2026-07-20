# -*- coding: utf-8 -*-
"""销售中心数据操作 — 商品、订单、销售事件、佣金"""
import time
import uuid
from datetime import datetime, timedelta, timezone

from core.logging_util import get_logger
from core.db_repos._constants import _CST

logger = get_logger("db.sales")


class SalesRepo:
    """销售中心数据层"""

    def __init__(self, db):
        self._db = db

    @property
    def conn(self):
        return self._db.conn

    @property
    def lock(self):
        return self._db.lock

    # ──────────────────── 商品管理 ────────────────────
    def add_product(self, name: str, price: float, category: str = "default",
                    description: str = "", stock: int = -1, sku: str = "") -> int:
        """新增商品，返回 product_id"""
        now = int(time.time())
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO sales_products (name, sku, category, price, description, stock, is_active, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,1,?,?)""",
                (name, sku, category, price, description, stock, now, now)
            )
            self.conn.commit()
            return cur.lastrowid

    def update_product(self, product_id: int, **kwargs) -> bool:
        """更新商品字段

        v5.35.1 修复 P2 bug：检查 rowcount，不存在的 ID 返回 False。
        """
        if not kwargs:
            return False
        kwargs["updated_at"] = int(time.time())
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [product_id]
        with self.lock:
            cur = self.conn.execute(f"UPDATE sales_products SET {sets} WHERE id=?", vals)
            self.conn.commit()
            return cur.rowcount > 0

    def list_products(self, category: str = None, active_only: bool = True) -> list:
        """列出商品"""
        q = "SELECT id, name, sku, category, price, description, stock, is_active, created_at FROM sales_products WHERE 1=1"
        params = []
        if active_only:
            q += " AND is_active=1"
        if category:
            q += " AND category=?"
            params.append(category)
        q += " ORDER BY sort_order ASC, id ASC"
        with self.lock:
            return self.conn.execute(q, params).fetchall()

    def get_product(self, product_id: int) -> dict:
        """获取单个商品"""
        with self.lock:
            row = self.conn.execute(
                "SELECT id, name, sku, category, price, description, stock, is_active FROM sales_products WHERE id=?",
                (product_id,)
            ).fetchone()
            if not row:
                return {}
            return {
                "id": row[0], "name": row[1], "sku": row[2], "category": row[3],
                "price": row[4], "description": row[5], "stock": row[6], "is_active": row[7]
            }

    # ──────────────────── 订单管理 ────────────────────
    def create_order(self, uid: int, product_id: int, amount: float,
                     chat_id: int = 0, source: str = "group",
                     referrer_uid: int = 0, note: str = "") -> int:
        """创建订单，返回 order_id。状态默认 pending

        v5.35.1 修复 P0 bug：order_no 加 8 位 uuid 后缀避免同秒同 uid 同 product_id 重复下单 UNIQUE 冲突。
        """
        now = int(time.time())
        order_no = f"ORD{now}{uid}{product_id}{uuid.uuid4().hex[:8]}"
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO sales_orders (order_no, uid, product_id, amount, status, chat_id, source, referrer_uid, note, created_at, updated_at)
                   VALUES (?,?,?,?, 'pending',?,?,?,?,?,?)""",
                (order_no, uid, product_id, amount, chat_id, source, referrer_uid, note, now, now)
            )
            self.conn.commit()
            return cur.lastrowid

    def update_order_status(self, order_id: int, status: str, note: str = "") -> bool:
        """更新订单状态（pending/paid/shipped/completed/refunded/cancelled）

        v5.35.1 修复 P2 bug：检查 rowcount，不存在的 ID 返回 False。
        """
        now = int(time.time())
        with self.lock:
            cur = self.conn.execute(
                "UPDATE sales_orders SET status=?, updated_at=?, note=COALESCE(?, note) WHERE id=?",
                (status, now, note, order_id)
            )
            self.conn.commit()
            return cur.rowcount > 0

    def get_user_orders(self, uid: int, limit: int = 20, chat_id: int = 0) -> list:
        """获取用户订单列表

        v5.35.1 修复 P3 bug：增加 chat_id 可选过滤参数，避免同一用户跨群订单互相可见。
        chat_id=0（默认）时不过滤，保持向后兼容。
        """
        with self.lock:
            if chat_id:
                return self.conn.execute(
                    """SELECT o.id, o.order_no, o.uid, p.name as product_name, o.amount, o.status, o.source, o.created_at
                       FROM sales_orders o LEFT JOIN sales_products p ON o.product_id=p.id
                       WHERE o.uid=? AND o.chat_id=? ORDER BY o.id DESC LIMIT ?""",
                    (uid, chat_id, limit)
                ).fetchall()
            return self.conn.execute(
                """SELECT o.id, o.order_no, o.uid, p.name as product_name, o.amount, o.status, o.source, o.created_at
                   FROM sales_orders o LEFT JOIN sales_products p ON o.product_id=p.id
                   WHERE o.uid=? ORDER BY o.id DESC LIMIT ?""",
                (uid, limit)
            ).fetchall()

    def get_order_stats(self, days: int = 30) -> dict:
        """订单统计（GMV、订单数、付款数、转化率）"""
        since = int(time.time()) - days * 86400
        with self.lock:
            total = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_orders WHERE created_at>?",
                (since,)
            ).fetchone()
            paid = self.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM sales_orders WHERE created_at>? AND status IN ('paid','shipped','completed')",
                (since,)
            ).fetchone()
            return {
                "days": days,
                "total_orders": total[0],
                "total_gmv": total[1],
                "paid_orders": paid[0],
                "paid_amount": paid[1],
                "conversion_rate": round(paid[0] / total[0] * 100, 1) if total[0] > 0 else 0
            }

    # ──────────────────── 销售事件追踪 ────────────────────
    def track_sales_event(self, uid: int, event: str, chat_id: int = 0,
                          product_id: int = 0, value: float = 0, note: str = ""):
        """记录销售漏斗事件（view/click/consult/cart/pay/refund）"""
        now = int(time.time())
        with self.lock:
            self.conn.execute(
                """INSERT INTO sales_events (uid, event, chat_id, product_id, value, note, ts)
                   VALUES (?,?,?,?,?,?,?)""",
                (uid, event, chat_id, product_id, value, note, now)
            )
            self.conn.commit()

    def get_funnel_stats(self, days: int = 7) -> dict:
        """销售漏斗统计：各阶段人数与转化率"""
        since = int(time.time()) - days * 86400
        stages = ["view", "click", "consult", "cart", "pay"]
        result = {}
        with self.lock:
            for stage in stages:
                cnt = self.conn.execute(
                    "SELECT COUNT(DISTINCT uid) FROM sales_events WHERE event=? AND ts>?",
                    (stage, since)
                ).fetchone()[0]
                result[stage] = cnt
        # 计算阶段转化率
        rates = {}
        prev = None
        for stage in stages:
            if prev and result.get(prev, 0) > 0:
                rates[f"{prev}_to_{stage}"] = round(result[stage] / result[prev] * 100, 1)
            prev = stage
        result["stage_rates"] = rates
        result["days"] = days
        return result

    # ──────────────────── 佣金/分销 ────────────────────
    def add_commission(self, referrer_uid: int, order_id: int, amount: float, rate: float = 0.1) -> int:
        """新增佣金记录"""
        now = int(time.time())
        with self.lock:
            cur = self.conn.execute(
                """INSERT INTO sales_commissions (referrer_uid, order_id, amount, rate, status, created_at)
                   VALUES (?,?,?,?, 'pending', ?)""",
                (referrer_uid, order_id, amount, rate, now)
            )
            self.conn.commit()
            return cur.lastrowid

    def get_commission_stats(self, uid: int) -> dict:
        """获取用户佣金统计"""
        with self.lock:
            total = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM sales_commissions WHERE referrer_uid=?",
                (uid,)
            ).fetchone()
            paid = self.conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM sales_commissions WHERE referrer_uid=? AND status='paid'",
                (uid,)
            ).fetchone()
            return {
                "total_commission": total[0],
                "total_orders": total[1],
                "paid_commission": paid[0],
                "pending_commission": total[0] - paid[0]
            }
