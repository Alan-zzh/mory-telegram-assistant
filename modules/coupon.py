"""
modules/coupon.py · 优惠券系统

功能：
  handle_generate_coupon(bot, m, config, db, args) - 管理员生成优惠券
  handle_claim_coupon(bot, m, config, db, code) - 用户领取优惠券
  handle_redeem_coupon(bot, m, config, db, code) - 管理员核销优惠券

优惠券码格式：8位随机字母数字（如 AB3K9M2X）
coupon_claims 表字段：code, type, value, expires_at, claimed_by, used_at
"""

import random
import string
import time
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("coupon")

_CST = timezone(timedelta(hours=8))


def _generate_code(length: int = 8) -> str:
    """生成随机优惠券码（大写字母+数字）"""
    chars = string.ascii_uppercase + string.digits
    # 排除容易混淆的字符 O/0, I/1, L
    chars = chars.replace("O", "").replace("0", "").replace("I", "").replace("1", "").replace("L", "")
    return "".join(random.choices(chars, k=length))


def _ensure_coupon_table(db):
    """确保 coupon_claims 表存在（兼容旧数据库）"""
    try:
        c = db.conn.cursor()
        c.execute("SELECT 1 FROM coupon_claims LIMIT 0")
    except Exception:
        c = db.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS coupon_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'points',
            value INTEGER NOT NULL DEFAULT 0,
            days INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER NOT NULL DEFAULT 0,
            claimed_by INTEGER DEFAULT 0,
            claimed_at INTEGER DEFAULT 0,
            used_at INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            UNIQUE(code)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_code ON coupon_claims(code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_coupon_claimed_by ON coupon_claims(claimed_by)")
        db.conn.commit()
        logger.info("coupon_claims 表已自动创建")


def handle_generate_coupon(bot, m, config: dict, db, args: str):
    """
    管理员生成优惠券。

    用法：生成优惠券 类型 数量 面额 天数
    示例：生成优惠券 points 10 50 30
      - 类型：points（积分）
      - 数量：10张
      - 面额：50积分
      - 天数：30天有效期

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        args: 指令参数（类型 数量 面额 天数）
    """
    chat_id = m.chat.id
    admin_uid = m.from_user.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)

    if admin_uid not in admin_ids:
        bot.send_message(chat_id, "⛔ 只有管理员才能生成优惠券")
        return

    _ensure_coupon_table(db)

    # 解析参数
    parts = args.strip().split()
    if len(parts) < 4:
        bot.send_message(
            chat_id,
            "❌ 格式：生成优惠券 类型 数量 面额 天数\n"
            "示例：生成优惠券 points 10 50 30\n"
            "  类型：points（积分）\n"
            "  数量：10张\n"
            "  面额：50积分\n"
            "  天数：30天有效期",
        )
        return

    coupon_type = parts[0].lower()
    try:
        count = int(parts[1])
        value = int(parts[2])
        days = int(parts[3])
    except ValueError:
        bot.send_message(chat_id, "❌ 数量、面额、天数必须是整数")
        return

    if count <= 0 or count > 100:
        bot.send_message(chat_id, "❌ 数量范围：1-100")
        return

    if value <= 0:
        bot.send_message(chat_id, "❌ 面额必须大于0")
        return

    if days <= 0:
        bot.send_message(chat_id, "❌ 有效天数必须大于0")
        return

    # 支持的优惠券类型
    valid_types = {"points", "vip", "discount"}
    if coupon_type not in valid_types:
        bot.send_message(chat_id, f"❌ 不支持的类型：{coupon_type}\n可选类型：{', '.join(valid_types)}")
        return

    now = int(time.time())
    expires_at = now + days * 86400

    # 生成优惠券码
    codes = []
    try:
        c = db.conn.cursor()
        for _ in range(count):
            # 确保码不重复
            code = _generate_code()
            attempts = 0
            while attempts < 10:
                c.execute("SELECT 1 FROM coupon_claims WHERE code=?", (code,))
                if not c.fetchone():
                    break
                code = _generate_code()
                attempts += 1

            c.execute(
                "INSERT INTO coupon_claims (code, type, value, days, expires_at, created_at) VALUES (?,?,?,?,?,?)",
                (code, coupon_type, value, days, expires_at, now),
            )
            codes.append(code)

        db.conn.commit()

        # 构建结果消息
        type_labels = {"points": "积分", "vip": "VIP", "discount": "折扣"}
        type_label = type_labels.get(coupon_type, coupon_type)
        expires_str = datetime.now(_CST).strftime("%Y-%m-%d %H:%M")

        lines = [
            f"✅ 已生成 {count} 张优惠券",
            f"📦 类型：{type_label}  面额：{value}  有效期：{days}天",
            f"⏰ 过期时间：{expires_str}",
            "",
            "🎫 优惠券码：",
        ]
        for i, code in enumerate(codes, 1):
            lines.append(f"  {i}. {code}")

        bot.send_message(chat_id, "\n".join(lines))
        logger.info(f"生成优惠券: type={coupon_type} count={count} value={value} days={days} by admin={admin_uid}")
    except Exception as e:
        logger.error(f"生成优惠券失败: {e}")
        bot.send_message(chat_id, "❌ 生成优惠券失败，请稍后再试")


def handle_claim_coupon(bot, m, config: dict, db, code: str):
    """
    用户领取优惠券。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        code: 优惠券码
    """
    chat_id = m.chat.id
    uid = m.from_user.id

    _ensure_coupon_table(db)

    code = code.strip().upper()
    if not code:
        bot.send_message(chat_id, "❌ 请输入优惠券码\n用法：领取优惠券 AB3K9M2X")
        return

    try:
        c = db.conn.cursor()
        c.execute(
            "SELECT id, code, type, value, expires_at, claimed_by FROM coupon_claims WHERE code=?",
            (code,),
        )
        row = c.fetchone()

        if not row:
            bot.send_message(chat_id, "❌ 优惠券码不存在")
            return

        coupon_id, coupon_code, coupon_type, coupon_value, expires_at, claimed_by = row

        # 检查是否已被领取
        if claimed_by:
            if claimed_by == uid:
                bot.send_message(chat_id, "⚠️ 你已经领取过这张优惠券了")
            else:
                bot.send_message(chat_id, "❌ 该优惠券已被他人领取")
            return

        # 检查是否过期
        now = int(time.time())
        if expires_at > 0 and now > expires_at:
            bot.send_message(chat_id, "❌ 该优惠券已过期")
            return

        # 领取优惠券
        c.execute(
            "UPDATE coupon_claims SET claimed_by=?, claimed_at=? WHERE code=?",
            (uid, now, code),
        )

        # 如果是积分类型，直接加积分
        if coupon_type == "points":
            c.execute("INSERT OR IGNORE INTO user_levels VALUES (?,1,0,?,?)", (uid, now, now))
            c.execute("UPDATE user_levels SET points=points+?, last_active=? WHERE uid=?", (coupon_value, now, uid))
            c.execute("SELECT points FROM user_levels WHERE uid=?", (uid,))
            total_row = c.fetchone()
            total_points = total_row[0] if total_row else 0

            # 更新等级
            level = 1
            if total_points >= 500:
                level = 4
            elif total_points >= 100:
                level = 3
            elif total_points >= 20:
                level = 2
            c.execute("UPDATE user_levels SET level=? WHERE uid=?", (level, uid))

        db.conn.commit()

        # 获取用户名
        c.execute("SELECT name FROM users WHERE uid=?", (uid,))
        user_row = c.fetchone()
        name = user_row[0] if user_row else f"用户{uid}"

        type_labels = {"points": "积分", "vip": "VIP", "discount": "折扣"}
        type_label = type_labels.get(coupon_type, coupon_type)

        if coupon_type == "points":
            bot.send_message(
                chat_id,
                f"✅ {name} 领取优惠券成功！\n"
                f"🎫 码：{code}\n"
                f"📦 类型：{type_label}  面额：{coupon_value}\n"
                f"💰 积分已到账，当前积分：{total_points}",
            )
        else:
            bot.send_message(
                chat_id,
                f"✅ {name} 领取优惠券成功！\n"
                f"🎫 码：{code}\n"
                f"📦 类型：{type_label}  面额：{coupon_value}\n"
                f"📝 请联系管理员使用",
            )

        logger.info(f"领取优惠券: code={code} uid={uid} type={coupon_type} value={coupon_value}")
    except Exception as e:
        logger.error(f"领取优惠券失败: {e}")
        bot.send_message(chat_id, "❌ 领取优惠券失败，请稍后再试")


def handle_redeem_coupon(bot, m, config: dict, db, code: str):
    """
    管理员核销优惠券。

    Args:
        bot: TeleBot实例
        m: 消息对象
        config: 配置字典
        db: DB类实例
        code: 优惠券码
    """
    chat_id = m.chat.id
    admin_uid = m.from_user.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if isinstance(admin_ids, int):
        admin_ids = [admin_ids]
    if not isinstance(admin_ids, list):
        admin_ids = []
    if admin_id and admin_id not in admin_ids:
        admin_ids.append(admin_id)

    if admin_uid not in admin_ids:
        bot.send_message(chat_id, "⛔ 只有管理员才能核销优惠券")
        return

    _ensure_coupon_table(db)

    code = code.strip().upper()
    if not code:
        bot.send_message(chat_id, "❌ 请输入优惠券码\n用法：核销优惠券 AB3K9M2X")
        return

    try:
        c = db.conn.cursor()
        c.execute(
            "SELECT id, code, type, value, expires_at, claimed_by, used_at FROM coupon_claims WHERE code=?",
            (code,),
        )
        row = c.fetchone()

        if not row:
            bot.send_message(chat_id, "❌ 优惠券码不存在")
            return

        coupon_id, coupon_code, coupon_type, coupon_value, expires_at, claimed_by, used_at = row

        # 检查是否已被核销
        if used_at:
            bot.send_message(chat_id, "⚠️ 该优惠券已被核销")
            return

        # 检查是否已被领取
        if not claimed_by:
            bot.send_message(chat_id, "⚠️ 该优惠券尚未被领取，无法核销")
            return

        # 核销
        now = int(time.time())
        c.execute("UPDATE coupon_claims SET used_at=? WHERE code=?", (now, code))
        db.conn.commit()

        # 获取领取人信息
        c.execute("SELECT name FROM users WHERE uid=?", (claimed_by,))
        user_row = c.fetchone()
        claimer_name = user_row[0] if user_row else f"用户{claimed_by}"

        type_labels = {"points": "积分", "vip": "VIP", "discount": "折扣"}
        type_label = type_labels.get(coupon_type, coupon_type)

        bot.send_message(
            chat_id,
            f"✅ 优惠券已核销\n"
            f"🎫 码：{code}\n"
            f"📦 类型：{type_label}  面额：{coupon_value}\n"
            f"👤 领取人：{claimer_name}（UID: {claimed_by}）",
        )
        logger.info(f"核销优惠券: code={code} claimed_by={claimed_by} by admin={admin_uid}")
    except Exception as e:
        logger.error(f"核销优惠券失败: {e}")
        bot.send_message(chat_id, "❌ 核销优惠券失败，请稍后再试")
