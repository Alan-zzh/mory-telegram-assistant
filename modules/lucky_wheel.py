import time
import random
from datetime import datetime, timedelta, timezone
from core.database import _db_lock
from core.logging_util import get_logger

_CST = timezone(timedelta(hours=8))
logger = get_logger("lucky_wheel")


def _weighted_reward():
    """按权重分布随机生成积分奖励。

    经济平衡：期望 ≈ 0.4×2 + 0.3×7 + 0.2×15.5 + 0.1×30.5 ≈ 9 分，
    必须低于默认付费成本（LUCKY_WHEEL_COST=10），否则付费档成为
    无限印钞机掏穿积分体系；调整奖励区间时必须重算期望。
    """
    roll = random.random()
    if roll < 0.40:
        return random.randint(1, 3)
    elif roll < 0.70:
        return random.randint(4, 10)
    elif roll < 0.90:
        return random.randint(11, 20)
    else:
        return random.randint(21, 40)


def _today_str():
    """返回今天的日期字符串（CST）"""
    return datetime.now(_CST).strftime("%Y-%m-%d")


def handle_lucky_wheel(bot, m, config, db, args=""):
    """处理幸运转盘命令"""
    uid = m.from_user.id
    text = (m.text or "").strip()
    cost_per_spin = config.get("LUCKY_WHEEL_COST", 10)
    wheel_cfg = config.get("LUCKY_WHEEL_CONFIG", {}) or {}
    paid_daily_limit = int(wheel_cfg.get("paid_daily_limit", 20) or 0)
    today = _today_str()

    # 等级免费转盘次数
    from modules.points_enhanced import _get_applicable_privilege
    level_free_spins = _get_applicable_privilege(db, uid, "wheel_free_spins", config) or 0

    # 解析转盘次数
    parts = text.split()
    count = 1
    if len(parts) >= 2:
        try:
            count = int(parts[1])
        except ValueError:
            bot.reply_to(m, "❌ 转盘次数请输入数字，如「转盘 3」")
            return

    if count < 1:
        bot.reply_to(m, "❌ 转盘次数至少为1")
        return

    if count > 10:
        bot.reply_to(m, "❌ 单次最多转10次")
        return

    reply_text = None
    _levelup_result = None
    with _db_lock:
        # 查询今日转盘记录
        row = db.conn.execute(
            "SELECT id, reward, spin_count FROM lucky_wheel_results WHERE uid=? AND date=?",
            (uid, today),
        ).fetchone()

        # 今日总免费次数 = 基础1次 + 等级额外次数
        total_free = 1 + level_free_spins
        used_spins = row[2] if row else 0
        remaining_free = max(0, total_free - used_spins)

        if count == 1:
            # 单次转盘
            if remaining_free > 0:
                # 使用免费次数
                reward = _weighted_reward()
                if row is None:
                    db.conn.execute(
                        "INSERT INTO lucky_wheel_results (uid, date, reward, spin_count, ts) VALUES (?, ?, ?, 1, ?)",
                        (uid, today, reward, int(time.time())),
                    )
                else:
                    db.conn.execute(
                        "UPDATE lucky_wheel_results SET reward=reward+?, spin_count=spin_count+1, ts=? WHERE uid=? AND date=?",
                        (reward, int(time.time()), uid, today),
                    )
                db.conn.commit()
                _levelup_result = db.add_points(uid, reward, source="wheel")
                current = db.get_user_points(uid) or 0
                free_info = f"（免费 {used_spins + 1}/{total_free}）" if total_free > 1 else ""
                reply_text = (
                    f"🎡 幸运转盘！{free_info}\n🎲 获得积分：{reward}\n💎 当前积分：{current}"
                )
                logger.info(f"用户{uid}免费转盘获得{reward}积分")
            else:
                # 免费次数已用完，付费
                if paid_daily_limit > 0 and used_spins >= total_free + paid_daily_limit:
                    reply_text = (
                        f"🎡 今日转盘次数已用完（免费{total_free}次+付费{paid_daily_limit}次），明天再来吧～"
                    )
                else:
                    current_points = db.get_user_points(uid) or 0
                    if current_points < cost_per_spin:
                        reply_text = (
                            f"🎡 今日免费转盘已用完（共{total_free}次）\n❌ 积分不足！付费转盘需要{cost_per_spin}积分，当前仅有{current_points}积分"
                        )
                    else:
                        # 扣费与开奖在同一锁内完成；开奖/记账任一步失败自动退回扣费，杜绝"扣了钱没结果"
                        db.add_points(uid, -cost_per_spin, source="wheel_cost")
                        try:
                            reward = _weighted_reward()
                            db.conn.execute(
                                "UPDATE lucky_wheel_results SET reward=reward+?, spin_count=spin_count+1, ts=? WHERE uid=? AND date=?",
                                (reward, int(time.time()), uid, today),
                            )
                            db.conn.commit()
                            _levelup_result = db.add_points(uid, reward, source="wheel")
                        except Exception as e:
                            try:
                                db.add_points(uid, cost_per_spin, source="wheel_refund")
                                logger.error(f"付费转盘开奖失败已自动退费（非致命）：uid={uid} cost={cost_per_spin} err={e}")
                            except Exception as refund_err:
                                logger.error(f"付费转盘开奖失败且退费失败，需人工补积分：uid={uid} cost={cost_per_spin} err={e} refund_err={refund_err}")
                            raise
                        current = db.get_user_points(uid) or 0
                        reply_text = (
                            f"🎡 幸运转盘（付费）\n💰 消耗积分：{cost_per_spin}\n🎲 获得积分：{reward}\n💎 当前积分：{current}"
                        )
                        logger.info(f"用户{uid}付费转盘获得{reward}积分")
        else:
            # 多次转盘：计算免费次数和付费次数
            free_spins = min(remaining_free, count)
            paid_spins = count - free_spins
            total_cost = paid_spins * cost_per_spin

            # 付费日上限对多次转同样生效（旧版只拦单次，循环“转盘 10”即可绕过）
            if paid_daily_limit > 0 and used_spins + count > total_free + paid_daily_limit:
                allowed_paid = max(0, total_free + paid_daily_limit - used_spins)
                reply_text = (
                    f"🎡 超出今日转盘上限（免费{total_free}+付费{paid_daily_limit}），"
                    f"本次最多还能转 {allowed_paid} 次"
                )
            elif total_cost > 0:
                current_points = db.get_user_points(uid) or 0
                if current_points < total_cost:
                    reply_text = (
                        f"❌ 积分不足！转盘{count}次（免费{free_spins}次+付费{paid_spins}次）需要{total_cost}积分，当前仅有{current_points}积分"
                    )
                else:
                    # 与单次付费同理：失败自动退回全部扣费
                    db.add_points(uid, -total_cost, source="wheel_cost")
                    try:
                        # 计算总奖励
                        total_reward = sum(_weighted_reward() for _ in range(count))
                        # 更新记录
                        if row is None:
                            db.conn.execute(
                                "INSERT INTO lucky_wheel_results (uid, date, reward, spin_count, ts) VALUES (?, ?, ?, ?, ?)",
                                (uid, today, total_reward, count, int(time.time())),
                            )
                        else:
                            db.conn.execute(
                                "UPDATE lucky_wheel_results SET reward=reward+?, spin_count=spin_count+?, ts=? WHERE uid=? AND date=?",
                                (total_reward, count, int(time.time()), uid, today),
                            )
                        db.conn.commit()
                        # 发放奖励
                        _levelup_result = db.add_points(uid, total_reward, source="wheel")
                    except Exception as e:
                        try:
                            db.add_points(uid, total_cost, source="wheel_refund")
                            logger.error(f"多次转盘发放失败已自动退费（非致命）：uid={uid} cost={total_cost} err={e}")
                        except Exception as refund_err:
                            logger.error(f"多次转盘发放失败且退费失败，需人工补积分：uid={uid} cost={total_cost} err={e} refund_err={refund_err}")
                        raise

                    current = db.get_user_points(uid) or 0
                    cost_info = f"\n💰 消耗积分：{total_cost}" if total_cost > 0 else ""
                    free_info = f"\n🎁 免费次数：{free_spins}/{total_free}" if free_spins > 0 else ""
                    reply_text = (
                        f"🎡 幸运转盘 x{count}！{free_info}{cost_info}\n🎲 总获得：{total_reward}\n💎 当前积分：{current}"
                    )
                    logger.info(f"用户{uid}转盘{count}次（免费{free_spins}付费{paid_spins}），消耗{total_cost}，获得{total_reward}积分")

            else:
                # 纯免费多次转（旧版此路径静默无任何回复）
                total_reward = sum(_weighted_reward() for _ in range(count))
                if row is None:
                    db.conn.execute(
                        "INSERT INTO lucky_wheel_results (uid, date, reward, spin_count, ts) VALUES (?, ?, ?, ?, ?)",
                        (uid, today, total_reward, count, int(time.time())),
                    )
                else:
                    db.conn.execute(
                        "UPDATE lucky_wheel_results SET reward=reward+?, spin_count=spin_count+?, ts=? WHERE uid=? AND date=?",
                        (total_reward, count, int(time.time()), uid, today),
                    )
                db.conn.commit()
                _levelup_result = db.add_points(uid, total_reward, source="wheel")
                current = db.get_user_points(uid) or 0
                reply_text = (
                    f"🎡 幸运转盘 x{count}！\n🎁 免费次数：{free_spins}/{total_free}\n🎲 总获得：{total_reward}\n💎 当前积分：{current}"
                )
                logger.info(f"用户{uid}免费转盘x{count}，获得{total_reward}积分")

    # 锁外发送：Telegram 网络 IO 不占用全局数据库锁
    if reply_text:
        bot.reply_to(m, reply_text)
        if _levelup_result is not None:
            # 检查升级通知
            from modules.points_enhanced import check_level_up
            check_level_up(bot, m.chat.id, uid, m.from_user.first_name or str(uid), _levelup_result, config)


def handle_wheel_history(bot, m, config, db):
    """查看转盘历史记录（最近7天）"""
    uid = m.from_user.id
    today = datetime.now(_CST).date()

    with _db_lock:
        rows = db.conn.execute(
            "SELECT date, reward FROM lucky_wheel_results WHERE uid=? AND date>=? ORDER BY date DESC",
            (uid, (today - timedelta(days=6)).strftime("%Y-%m-%d")),
        ).fetchall()

    if not rows:
        bot.reply_to(m, "📋 近7天暂无转盘记录")
        return

    lines = ["🎡 近7天转盘记录："]
    for date_str, reward in rows:
        lines.append(f"{date_str}：{reward}积分")

    bot.reply_to(m, "\n".join(lines))
