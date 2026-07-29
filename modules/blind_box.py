"""
盲盒/扭蛋系统 - 消耗积分抽取随机奖品

功能：
  1. 用户消耗积分开启盲盒，随机获得奖品
  2. 基于概率权重的随机抽奖
  3. 管理员可自定义奖品池（增删改查+重置）

命令：
  盲盒 / 扭蛋 → handle_blind_box
  盲盒设置 列表 → 查看奖品池
  盲盒设置 添加 奖品名 概率 奖励积分 → 添加奖品
  盲盒设置 删除 奖品名 → 删除奖品
  盲盒设置 重置 → 重置为默认奖品

数据表：blind_box_prizes（id, name, probability, prize_type, value, enabled, ts）
"""
import time
import random

from core.database import _db_lock
from core.logging_util import get_logger
from core.admin_utils import is_admin_user

logger = get_logger("blind_box")

# 默认盲盒消耗积分
DEFAULT_BLIND_BOX_COST = 30

# 默认奖品池：名称 → (概率权重, 奖励积分)
_DEFAULT_PRIZES = [
    ("谢谢参与", 50, 0),
    ("小奖", 25, 10),
    ("中奖", 15, 30),
    ("大奖", 8, 80),
    ("超级大奖", 2, 200),
]


def _init_default_prizes(db):
    """初始化默认奖品池（当blind_box_prizes表为空时调用）"""
    now_ts = int(time.time())
    with _db_lock:
        for name, prob, value in _DEFAULT_PRIZES:
            db.conn.execute(
                "INSERT INTO blind_box_prizes (name, probability, prize_type, value, enabled, ts) VALUES (?,?,?,?,?,?)",
                (name, prob, "points", value, 1, now_ts)
            )
        db.conn.commit()
    logger.info("盲盒默认奖品池已初始化")


def _select_prize(db):
    """基于概率权重随机选择奖品

    Returns:
        (name, value) 奖品名称和奖励积分
    """
    rows = db.conn.execute(
        "SELECT name, probability, value FROM blind_box_prizes WHERE enabled=1"
    ).fetchall()

    # 奖品池为空时初始化默认奖品
    if not rows:
        _init_default_prizes(db)
        rows = db.conn.execute(
            "SELECT name, probability, value FROM blind_box_prizes WHERE enabled=1"
        ).fetchall()

    # 加权随机选择
    names = [r[0] for r in rows]
    weights = [r[1] for r in rows]
    values = [r[2] for r in rows]

    chosen = random.choices(range(len(rows)), weights=weights, k=1)[0]
    return names[chosen], values[chosen]


def handle_blind_box(bot, m, config, db):
    """处理盲盒/扭蛋命令"""
    uid = m.from_user.id
    cost = config.get("BLIND_BOX_COST", DEFAULT_BLIND_BOX_COST)

    # 等级折扣
    from modules.points_enhanced import _get_applicable_privilege
    discount = _get_applicable_privilege(db, uid, "blindbox_discount", config)
    original_cost = cost
    if discount is not None and discount < 1.0:
        cost = max(1, int(cost * discount))

    try:
        # [TRAE SOLO CN] 原子扣款：UPDATE ... WHERE uid=? AND points>=?，避免 TOCTOU 竞态
        with _db_lock:
            cur = db.conn.execute(
                "UPDATE user_levels SET points = points - ? WHERE uid = ? AND points >= ?",
                (cost, uid, cost)
            )
            if cur.rowcount == 0:
                db.conn.rollback()
                current_points = db.get_user_points(uid) or 0
                deficit = cost - current_points
                bot.reply_to(
                    m,
                    f"❌ 积分不足！\n"
                    f"💎 当前积分：{current_points}\n"
                    f"🎫 需要积分：{cost}\n"
                    f"📉 还差：{deficit}积分"
                )
                return
            # 记录积分日志
            try:
                db.conn.execute(
                    "INSERT INTO points_log (uid, change_amount, balance_after, source, ts) VALUES (?,?,?,?,?)",
                    (uid, -cost, db.get_user_points(uid), "blindbox", int(time.time()))
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            db.conn.commit()

        # 抽取奖品
        prize_name, prize_value = _select_prize(db)

        # 获取概率信息
        prob_info = ""
        try:
            prob_row = db.conn.execute(
                "SELECT probability FROM blind_box_prizes WHERE name=? AND enabled=1",
                (prize_name,)
            ).fetchone()
            if prob_row:
                prob_info = f"\n📊 概率：{prob_row[0]}%"
        except Exception as e:
            logger.warning(f"盲盒概率查询失败: {e}")
        # 发放奖品积分
        if prize_value > 0:
            _lv_result = db.add_points(uid, prize_value, source="blindbox")
            # 检查升级通知
            from modules.points_enhanced import check_level_up
            check_level_up(bot, m.chat.id, uid, m.from_user.first_name or str(uid), _lv_result, config)

        # 获取最新积分
        current_points = db.get_user_points(uid)
        if current_points is None:
            current_points = 0

        # 构建回复
        discount_info = ""
        if discount is not None and discount < 1.0:
            discount_info = f"\n🏷 等级折扣：{original_cost}→{cost}（{int(discount*100)}%）"
        if prize_name == "谢谢参与":
            reply = (
                "🎁 盲盒开奖！\n"
                "🎲 你抽到了：谢谢参与\n"
                "😅 下次好运！"
                f"{prob_info}"
                f"{discount_info}"
            )
        else:
            reply = (
                f"🎁 盲盒开奖！\n"
                f"🎲 你抽到了：{prize_name}\n"
                f"💰 获得积分：{prize_value}\n"
                f"💎 当前积分：{current_points}"
                f"{prob_info}"
                f"{discount_info}"
            )

        bot.reply_to(m, reply)
        logger.info(f"盲盒: uid={uid} prize={prize_name} value={prize_value} cost={cost}")

    except Exception as e:
        logger.error(f"盲盒异常: {e}")
        bot.reply_to(m, "❌ 盲盒开奖失败，请稍后再试")


def handle_blind_box_admin(bot, m, config, db, args):
    """管理员盲盒设置命令"""
    uid = m.from_user.id

    # 【P2-3 安全加固】统一使用 is_admin_user，同时支持 ADMIN_ID 和 ADMIN_IDS
    if not is_admin_user(config, uid):
        bot.reply_to(m, "❌ 仅管理员可设置盲盒")
        return

    if not args:
        bot.reply_to(m, "格式：盲盒设置 列表|添加|删除|重置")
        return

    action = args[0]

    try:
        if action == "列表":
            _admin_list_prizes(bot, m, db)

        elif action == "添加":
            if len(args) < 4:
                bot.reply_to(m, "格式：盲盒设置 添加 奖品名 概率 奖励积分")
                return
            _admin_add_prize(bot, m, db, args[1], args[2], args[3])

        elif action == "删除":
            if len(args) < 2:
                bot.reply_to(m, "格式：盲盒设置 删除 奖品名")
                return
            _admin_delete_prize(bot, m, db, args[1])

        elif action == "重置":
            _admin_reset_prizes(bot, m, db)

        else:
            bot.reply_to(m, "未知操作，支持：列表|添加|删除|重置")

    except ValueError:
        bot.reply_to(m, "❌ 概率和积分必须是数字")
    except Exception as e:
        logger.error(f"盲盒设置异常: {e}")
        bot.reply_to(m, "❌ 操作失败")


def _admin_list_prizes(bot, m, db):
    """列出当前奖品池"""
    rows = db.conn.execute(
        "SELECT name, probability, value, enabled FROM blind_box_prizes ORDER BY probability DESC"
    ).fetchall()

    if not rows:
        bot.reply_to(m, "📋 奖品池为空，发送「盲盒设置 重置」可恢复默认")
        return

    text = "📋 盲盒奖品池\n━━━━━━━━━━━━━\n"
    total_prob = 0
    for name, prob, value, enabled in rows:
        status = "✅" if enabled else "❌"
        text += f"{status} {name} — 概率:{prob}% 积分:{value}\n"
        if enabled:
            total_prob += prob
    text += f"━━━━━━━━━━━━━\n总概率：{total_prob}%"

    bot.reply_to(m, text)


def _admin_add_prize(bot, m, db, name, prob_str, value_str):
    """添加奖品"""
    prob = float(prob_str)
    value = int(value_str)
    now_ts = int(time.time())

    with _db_lock:
        db.conn.execute(
            "INSERT INTO blind_box_prizes (name, probability, prize_type, value, enabled, ts) VALUES (?,?,?,?,?,?)",
            (name, prob, "points", value, 1, now_ts)
        )
        db.conn.commit()

    bot.reply_to(m, f"✅ 已添加奖品：{name}（概率:{prob}% 积分:{value}）")
    logger.info(f"盲盒添加奖品: name={name} prob={prob} value={value}")


def _admin_delete_prize(bot, m, db, name):
    """删除奖品"""
    with _db_lock:
        cur = db.conn.execute(
            "DELETE FROM blind_box_prizes WHERE name=?", (name,)
        )
        db.conn.commit()
        deleted = cur.rowcount > 0

    if deleted:
        bot.reply_to(m, f"✅ 已删除奖品：{name}")
        logger.info(f"盲盒删除奖品: name={name}")
    else:
        bot.reply_to(m, f"❌ 未找到奖品：{name}")


def _admin_reset_prizes(bot, m, db):
    """重置为默认奖品池"""
    with _db_lock:
        db.conn.execute("DELETE FROM blind_box_prizes")
        db.conn.commit()

    _init_default_prizes(db)
    bot.reply_to(m, "✅ 奖品池已重置为默认")
    logger.info("盲盒奖品池已重置")
