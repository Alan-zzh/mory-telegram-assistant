"""
增强积分系统 - 转账、积分记录、每日限额、等级查询

功能：
  1. 积分转账（转账 @用户 金额 / 回复+转账 金额）
  2. 积分记录查询（积分记录）
  3. 每日发言积分限额检查
  4. 等级信息查询（等级）

命令：
  转账 → handle_transfer
  积分记录 → handle_points_log
  等级 → handle_level_info
"""
import time
import threading
from datetime import datetime, timedelta, timezone

from core.database import _db_lock
from core.helpers import can_delete_message, get_broadcast_auto_delete_config
from core.logging_util import get_logger

logger = get_logger("points_enhanced")

# 北京时间
_CST = timezone(timedelta(hours=8))

# 积分来源中文映射（缺项会在积分记录里直出英文 key）
SOURCE_MAP = {
    "speech": "发言",
    "checkin": "签到",
    "invite": "邀请",
    "tip": "打赏",
    "exchange": "兑换",
    "blindbox": "盲盒中奖",
    "blindbox_cost": "盲盒",
    "wheel": "转盘中奖",
    "wheel_cost": "转盘",
    "wheel_refund": "转盘退费",
    "transfer": "转账",
    "transfer_refund": "转账退回",
    "quest": "任务",
    "quest_bonus": "全勤任务奖励",
    "achievement": "成就",
    "checkin_makeup": "补签",
    "checkin_makeup_bonus": "补签补发奖励",
    "coupon": "优惠券",
    "redpacket": "红包",
    "system": "系统",
}

# 等级阈值：等级 → 所需积分（10级体系）
LEVEL_THRESHOLDS = {1: 0, 2: 20, 3: 50, 4: 100, 5: 200, 6: 500, 7: 1000, 8: 2000, 9: 5000, 10: 10000}


def _schedule_orphan_delete(bot, chat_id, msg_id, delay_seconds, label="level_up"):
    """[Trae CN] 调度一条孤儿播报的延迟删除（使用后台线程，0=不删）

    不依赖 APScheduler，跨模块零侵入。
    """
    if delay_seconds <= 0:
        return

    def _del():
        try:
            if can_delete_message(_config_ref[0] or {}):
                bot.delete_message(chat_id, msg_id)
                logger.info(f"🗑️ 孤儿播报已自动删除[{label}]: chat={chat_id} msg={msg_id} 延迟={delay_seconds}s")
        except Exception as e:
            logger.debug(f"⏭️ 孤儿播报删除失败[{label}]: chat={chat_id} msg={msg_id} err={e}")

    t = threading.Timer(delay_seconds, _del)
    t.daemon = True
    t.start()


# 引用闭包占位（实际由 _set_config_ref 注入）
_config_ref = [None]


def _set_config_ref(config):
    """[Trae CN] 由 call_site 注入最新 config 引用，保证删除时拿到最新开关"""
    _config_ref[0] = config


def check_level_up(bot, chat_id, uid, uname, level_result, config, db=None):
    """检查升级并发送通知

    [Trae CN v5.12.0] 孤儿播报30S自动删除
    - 默认 BROADCAST_AUTO_DELETE.orphan_seconds=30
    - 0=不删；>0=N秒后自动删除（可配置）
    - 依赖全局 ENABLE_MESSAGE_DELETION 开关
    - 发送后立即入库 broadcast_tracking（category=level_up）便于查询/调试

    Args:
        bot: Telebot实例
        chat_id: 发送通知的聊天ID
        uid: 用户ID
        uname: 用户名
        level_result: add_points/upsert_user_with_points 返回的 (new_level, old_level)
        config: 配置字典
        db: DB实例（可选，用于入库 broadcast_tracking）
    """
    if not level_result or len(level_result) < 2:
        return
    new_lv, old_lv = level_result[0], level_result[1]
    if new_lv > old_lv:
        lv_titles = config.get("LEVEL_TITLES", {})
        new_title = lv_titles.get(str(new_lv), f"Lv{new_lv}")
        try:
            sent = bot.send_message(
                chat_id,
                f"🎉 恭喜 {uname} 升级到 Lv{new_lv} {new_title}！"
            )
            # [Trae CN] 升级播报=孤儿消息，按配置 N 秒后自动删除
            if sent and hasattr(sent, "message_id"):
                _set_config_ref(config)
                if db is not None and hasattr(db, "track_broadcast"):
                    try:
                        db.track_broadcast(chat_id, "level_up", sent.message_id)
                    except Exception as track_err:
                        logger.debug(f"升级播报入库失败（不影响删除）: {track_err}")

                auto_cfg = get_broadcast_auto_delete_config(config)
                if auto_cfg["orphan_seconds"] > 0:
                    _schedule_orphan_delete(bot, chat_id, sent.message_id, auto_cfg["orphan_seconds"], "level_up")
        except Exception as e:
            logger.warning(f"升级播报发送失败: {e}")


def handle_transfer(bot, m, config, db, args=None):
    """处理积分转账命令"""
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    # 解析目标用户和金额
    target_uid = None
    target_name = "用户"
    amount = None

    # 方式1：回复某人的消息 + "转账 金额"
    if m.reply_to_message and m.reply_to_message.from_user:
        parts = m.text.strip().split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
            except ValueError:
                bot.reply_to(m, "❌ 金额必须是整数")
                return
        else:
            bot.reply_to(m, "❌ 用法：回复对方消息 + 转账 金额")
            return
        target_uid = m.reply_to_message.from_user.id
        target_name = m.reply_to_message.from_user.first_name or "用户"

    # 方式2："转账 @用户 金额"
    else:
        parts = m.text.strip().split()
        if len(parts) < 3:
            bot.reply_to(m, "❌ 用法：转账 @用户 金额\n或回复对方消息 + 转账 金额")
            return
        # 提取目标用户
        entities = m.entities or []
        mention_found = False
        for ent in entities:
            if ent.type == "text_mention":
                mention_found = True
                target_uid = ent.user.id
                target_name = ent.user.first_name or "用户"
                break
            if ent.type == "mention":
                # 纯 @用户名 无法本地解析出 uid：旧代码走到这里必然 NameError，改为明确提示
                bot.reply_to(m, "❌ 暂不支持 @用户名 转账，请回复对方消息后发送「转账 金额」")
                return
        if not mention_found:
            bot.reply_to(m, "❌ 请用 @用户 指定转账对象")
            return
        # 提取金额（最后一个数字参数）
        try:
            amount = int(parts[-1])
        except ValueError:
            bot.reply_to(m, "❌ 金额必须是整数")
            return

    # 校验：不能转给自己
    if target_uid == uid:
        bot.reply_to(m, "❌ 不能给自己转账哦")
        return

    # 校验：最低转账金额
    if amount < 1:
        bot.reply_to(m, "❌ 最低转账金额为1积分")
        return

    # [TRAE SOLO CN] 原子扣款：UPDATE ... SET points = points - ? WHERE uid = ? AND points >= ?
    # 避免"先查余额再扣款"两步操作之间的竞态条件
    insufficient_reply = None
    try:
        with _db_lock:
            cur = db.conn.cursor()
            cur.execute("UPDATE user_levels SET points = points - ? WHERE uid = ? AND points >= ?",
                        (amount, uid, amount))
            if cur.rowcount == 0:
                # 余额不足或用户不存在
                db.conn.rollback()
                sender_points = db.get_user_points(uid) or 0
                # 锁外回复：Telegram 网络 IO 不占用全局数据库锁
                insufficient_reply = f"❌ 积分不足，当前余额：{sender_points}"
            else:
                # 记录发送方积分日志
                ts = int(time.time())
                try:
                    cur.execute(
                        "INSERT INTO points_log (uid, change_amount, balance_after, source, ts) VALUES (?,?,?,?,?)",
                        (uid, -amount, db.get_user_points(uid), "transfer", ts)
                    )
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
                db.conn.commit()
    except Exception as e:
        logger.error(f"转账扣款异常: {e}")
        bot.reply_to(m, "❌ 转账失败，请稍后再试")
        return
    if insufficient_reply:
        bot.reply_to(m, insufficient_reply)
        return

    # 执行接收方入账（事务保护：如果接收方入账失败，退还发送方）
    try:
        _lv_result = db.add_points(target_uid, amount, source="transfer")
    except Exception as e:
        logger.error(f"转账接收方入账失败，退还发送方: {e}")
        db.add_points(uid, amount, source="transfer_refund")
        bot.reply_to(m, "❌ 转账失败，积分已退还")
        return
    logger.info(f"转账: {uid}→{target_uid} 金额={amount}")
    bot.reply_to(
        m,
        f"✅ 转账成功！\n"
        f"💸 {uname} → {target_name}\n"
        f"💰 金额：{amount}积分\n"
        f"💎 余额：{db.get_user_points(uid)}积分"
    )

    # 私聊通知收款方（与 tip 行为一致；失败静默）
    try:
        bot.send_message(
            target_uid,
            f"💰 收到来自 {uname} 的转账 {amount} 积分，已到账～",
        )
    except Exception as e:
        logger.debug(f"转账收款方通知失败 uid={target_uid}: {e}")

    # 检查接收方升级通知
    check_level_up(bot, m.chat.id, target_uid, target_name, _lv_result, config)


def handle_points_log(bot, m, config, db):
    """查看积分记录"""
    uid = m.from_user.id

    try:
        rows = db.get_points_log(uid, limit=10)
        if not rows:
            bot.reply_to(m, "📋 暂无积分记录")
            return

        text = "📋 积分记录（最近10条）\n━━━━━━━━━━━━━\n"
        text += "来源 | 金额 | 余额 | 时间\n"
        text += "─────────────────\n"
        for change_amount, balance_after, source, ts in rows:
            source_cn = SOURCE_MAP.get(source, source)
            # 金额带正负号
            amt_str = f"+{change_amount}" if change_amount > 0 else str(change_amount)
            time_str = datetime.fromtimestamp(ts, tz=_CST).strftime("%m-%d %H:%M")
            text += f"{source_cn} | {amt_str} | {balance_after} | {time_str}\n"

        current_points = db.get_user_points(uid)
        if current_points is not None:
            text += f"\n💎 当前积分：{current_points}"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"积分记录查询异常: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")


def check_daily_points_limit(db, uid, config) -> bool:
    """检查用户今日发言积分是否已达上限

    Returns:
        True = 已达上限，False = 未达上限
    """
    points_rules = config.get("POINTS_RULES", {})
    daily_limit = points_rules.get("daily_limit", 50)
    today_speech = db.get_today_speech_points(uid)
    return today_speech >= daily_limit


def handle_level_info(bot, m, config, db):
    """查看当前等级信息（10级体系）"""
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    try:
        points = db.get_user_points(uid)
        if points is None:
            bot.reply_to(m, f"📊 {uname}，你还没有积分记录，快去发言赚积分吧！")
            return

        # 计算当前等级（10级体系）
        _thresholds = config.get("LEVEL_THRESHOLDS", [0, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000])
        level = 1
        for i in range(len(_thresholds) - 1, -1, -1):
            if points >= _thresholds[i]:
                level = i + 1
                break

        # 检查认证状态
        try:
            from modules.certify import is_certified
            certified = is_certified(db, uid)
        except Exception:
            certified = False

        # 获取等级称号
        level_titles = config.get("LEVEL_TITLES", {})
        title = level_titles.get(str(level), "未知")

        # 计算下一等级所需积分（与当前等级同一阈值真相源：配置覆盖版 _thresholds）
        max_level = len(_thresholds)
        if level < max_level:
            next_level = level + 1
            next_threshold = _thresholds[next_level - 1]
            need = next_threshold - points
            next_title = level_titles.get(str(next_level), "未知")
            progress = f"距离下一级（Lv{next_level} {next_title}）还需 {need} 积分"
        else:
            progress = "🎉 已达最高等级！"

        # 获取等级特权信息
        privileges = config.get("LEVEL_PRIVILEGES", {})
        privilege_text = ""
        level_priv = privileges.get(str(level), {})
        if level_priv:
            priv_items = []
            for key, val in level_priv.items():
                priv_items.append(f"{key}: {val}")
            privilege_text = "\n🏅 特权：" + "、".join(priv_items)

        bot.reply_to(
            m,
            f"📊 {uname} 的等级信息\n"
            f"━━━━━━━━━━━━━\n"
            f"🏷 等级：Lv{level} {title}\n"
            f"💎 积分：{points}\n"
            + (f"✅ 已认证\n" if certified else "")
            + f"📈 {progress}\n"
            f"{privilege_text}"
        )

    except Exception as e:
        logger.error(f"等级查询异常: {e}")
        bot.reply_to(m, "❌ 查询失败，请稍后再试")


def _get_user_level(db, uid):
    """获取用户等级（根据积分计算）

    Args:
        db: 数据库实例
        uid: 用户ID

    Returns:
        用户等级（1-10）
    """
    points = db.get_user_points(uid) or 0
    level = 1
    # 按阈值从高到低匹配
    sorted_thresholds = sorted(LEVEL_THRESHOLDS.items(), key=lambda x: x[1])
    for lvl, threshold in reversed(sorted_thresholds):
        if points >= threshold:
            level = lvl
            break
    return level


def _get_applicable_privilege(db, uid, privilege_type, config):
    """获取用户适用的等级特权值（从当前等级向下查找最近的特权定义）

    Args:
        db: 数据库实例
        uid: 用户ID
        privilege_type: 特权类型（如 shop_discount、blindbox_discount、wheel_free_spins）
        config: 配置字典

    Returns:
        特权值，不存在则返回None
    """
    user_level = _get_user_level(db, uid)
    for lvl in range(user_level, 0, -1):
        priv = get_level_privilege(lvl, privilege_type, config)
        if priv is not None:
            return priv
    return None


def get_level_privilege(level, privilege_type, config):
    """获取等级特权值，如折扣、倍率等

    Args:
        level: 用户等级（1-10）
        privilege_type: 特权类型（如 discount、multiplier 等）
        config: 配置字典

    Returns:
        特权值，不存在则返回None
    """
    privileges = config.get("LEVEL_PRIVILEGES", {})
    level_str = str(level)
    if level_str in privileges:
        return privileges[level_str].get(privilege_type)
    return None


def run_points_decay(bot, config, db):
    """执行积分衰减（午夜定时任务调用）

    逻辑：
    1. 检查config中POINTS_DECAY.enabled是否开启
    2. 获取衰减率（默认1%）和最低保留积分（默认10）
    3. 查询所有积分 > 最低值的用户
    4. 对每个用户：衰减量 = max(1, int(积分 * 衰减率))；新积分 = max(最低值, 积分 - 衰减量)
    5. 更新数据库并记录日志
    """
    decay_config = config.get("POINTS_DECAY", {})
    if not decay_config.get("enabled", False):
        logger.debug("积分衰减未启用，跳过")
        return

    rate = decay_config.get("rate", 0.01)  # 默认1%
    minimum = decay_config.get("minimum", 10)  # 默认最低保留10积分

    try:
        # 查询所有积分超过最低值的用户
        with _db_lock:
            c = db.conn.cursor()
            c.execute("SELECT uid, points FROM user_levels WHERE points > ?", (minimum,))
            users = c.fetchall()

        if not users:
            logger.info("📉 积分衰减：无需衰减的用户")
            return

        total_decay = 0
        affected = 0

        for uid, points in users:
            decay_amount = max(1, int(points * rate))
            new_points = max(minimum, points - decay_amount)
            actual_decay = points - new_points

            if actual_decay > 0:
                db.add_points(uid, -actual_decay, source="decay")
                total_decay += actual_decay
                affected += 1

        logger.info(f"📉 积分衰减完成：影响{affected}人，总衰减{total_decay}积分")

    except Exception as e:
        logger.error(f"积分衰减异常: {e}")
