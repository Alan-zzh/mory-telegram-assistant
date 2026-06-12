"""
抽奖系统 - 管理员发起 + 用户参与 + 定时自动开奖
"""
import html
import time
import random
from datetime import datetime, timezone, timedelta

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("lottery")

# 北京时间
_CST = timezone(timedelta(hours=8))


def _get_scheduler():
    """获取APScheduler实例（从auto_tasks模块）"""
    try:
        from modules.auto_tasks import _scheduler_instance
        return _scheduler_instance
    except Exception:
        return None


def handle_create_lottery(bot, m, config, db, args):
    """发起抽奖：抽奖 奖品 数量 时长分钟"""
    uid = m.from_user.id
    chat_id = m.chat.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可发起抽奖")
        return

    try:
        if not args:
            bot.reply_to(m, "格式：抽奖 奖品 数量 时长分钟")
            return

        prize = args[0]
        prize_count = int(args[1]) if len(args) > 1 else 1
        duration = int(args[2]) if len(args) > 2 else 60

        now_ts = int(time.time())
        end_ts = now_ts + duration * 60

        with _db_lock:
            cursor = db.conn.execute(
                "INSERT INTO lotteries (creator_id, chat_id, prize, prize_count, duration_min, end_ts, ts) VALUES (?,?,?,?,?,?,?)",
                (uid, chat_id, prize, prize_count, duration, end_ts, now_ts)
            )
            lottery_id = cursor.lastrowid
            db.conn.commit()

        # 发送抽奖消息
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🎯 参与抽奖", callback_data=f"lot_{lottery_id}"))

        end_time = datetime.fromtimestamp(end_ts, _CST).strftime("%H:%M")
        text = (
            f"🎉 抽奖活动！\n"
            f"🏆 奖品：{prize} x{prize_count}\n"
            f"⏰ 截止时间：{end_time}（{duration}分钟后）\n\n"
            f"👇 点击参与！"
        )
        msg = bot.send_message(chat_id, text, reply_markup=keyboard)

        # 更新msg_id
        with _db_lock:
            db.conn.execute("UPDATE lotteries SET msg_id=? WHERE id=?", (msg.message_id, lottery_id))
            db.conn.commit()

        # 注册定时开奖任务
        scheduler = _get_scheduler()
        if scheduler:
            try:
                scheduler.add_job(
                    _draw_lottery, "date",
                    run_date=datetime.fromtimestamp(end_ts),
                    args=[bot, lottery_id, config, db],
                    id=f"lottery_{lottery_id}",
                    max_instances=1,
                    coalesce=True
                )
                logger.info(f"抽奖定时任务已注册: lottery_{lottery_id}")
            except Exception as sched_err:
                logger.warning(f"定时开奖注册失败（将需手动开奖）: {sched_err}")
        else:
            logger.warning("APScheduler未启动，抽奖将需手动开奖")

        logger.info(f"抽奖: id={lottery_id} prize={prize} duration={duration}min")

    except ValueError:
        bot.reply_to(m, "❌ 数量和时长必须是数字")
    except Exception as e:
        logger.error(f"发起抽奖异常: {e}")
        bot.reply_to(m, "❌ 发起抽奖失败")


def handle_join_lottery(bot, call, config, db):
    """参与抽奖回调"""
    data = call.data
    if not data.startswith("lot_"):
        return False

    lottery_id = int(data[4:])
    uid = call.from_user.id

    try:
        # 检查抽奖状态
        lottery = db.conn.execute(
            "SELECT status, end_ts FROM lotteries WHERE id=?", (lottery_id,)
        ).fetchone()
        if not lottery or lottery[0] != "active":
            bot.answer_callback_query(call.id, text="抽奖已结束", show_alert=True)
            return True

        # 检查是否已参与
        existing = db.conn.execute(
            "SELECT id FROM lottery_participants WHERE lottery_id=? AND uid=?",
            (lottery_id, uid)
        ).fetchone()
        if existing:
            bot.answer_callback_query(call.id, text="已参与抽奖", show_alert=False)
            return True

        # 记录参与
        now_ts = int(time.time())
        with _db_lock:
            # 再次检查状态（防止并发）
            status_row = db.conn.execute(
                "SELECT status FROM lotteries WHERE id=?", (lottery_id,)
            ).fetchone()
            if not status_row or status_row[0] != "active":
                bot.answer_callback_query(call.id, text="抽奖已结束", show_alert=True)
                return True

            db.conn.execute(
                "INSERT INTO lottery_participants (lottery_id, uid, ts) VALUES (?,?,?)",
                (lottery_id, uid, now_ts)
            )
            db.conn.commit()

        # 更新参与人数显示
        count = db.conn.execute(
            "SELECT COUNT(*) FROM lottery_participants WHERE lottery_id=?", (lottery_id,)
        ).fetchone()[0]
        bot.answer_callback_query(call.id, text=f"✅ 已参与！当前{count}人参与")

    except Exception as e:
        logger.error(f"参与抽奖异常: {e}")
        try:
            bot.answer_callback_query(call.id, text="❌ 参与失败")
        except Exception:
            pass

    return True


def _draw_lottery(bot, lottery_id, config, db):
    """开奖（定时任务调用）"""
    try:
        lottery = db.conn.execute(
            "SELECT creator_id, chat_id, prize, prize_count, msg_id FROM lotteries WHERE id=? AND status='active'",
            (lottery_id,)
        ).fetchone()
        if not lottery:
            logger.warning(f"开奖跳过: lottery_id={lottery_id} 状态非active或不存在")
            return

        creator_id, chat_id, prize, prize_count, msg_id = lottery

        # 获取参与者
        participants = db.conn.execute(
            "SELECT uid FROM lottery_participants WHERE lottery_id=?", (lottery_id,)
        ).fetchall()

        if not participants:
            bot.send_message(chat_id, f"🎉 抽奖结束\n🏆 奖品：{prize}\n❌ 无人参与，奖品作废")
            with _db_lock:
                db.conn.execute("UPDATE lotteries SET status='cancelled' WHERE id=?", (lottery_id,))
                db.conn.commit()
            return

        # 随机抽取
        uids = [p[0] for p in participants]
        winners = random.sample(uids, min(prize_count, len(uids)))

        # 公布结果
        winner_mentions = []
        for w_uid in winners:
            user = db.conn.execute("SELECT name FROM users WHERE uid=?", (w_uid,)).fetchone()
            name = user[0] if user else f"uid={w_uid}"
            escaped_name = html.escape(name)
            winner_mentions.append(f"🎉 <a href=\"tg://user?id={w_uid}\">{escaped_name}</a>")

        result_text = (
            f"🎉 抽奖结果揭晓！\n"
            f"🏆 奖品：{prize}\n\n"
            f"中奖者：\n" + "\n".join(winner_mentions) +
            f"\n\n共{len(uids)}人参与"
        )
        bot.send_message(chat_id, result_text, parse_mode="HTML")

        # 更新状态
        with _db_lock:
            db.conn.execute("UPDATE lotteries SET status='drawn' WHERE id=?", (lottery_id,))
            db.conn.commit()

        # 通知管理员
        admin_id = config.get("ADMIN_ID", 0)
        if admin_id:
            try:
                bot.send_message(admin_id, f"🎉 抽奖已开奖\n奖品：{prize}\n中奖者UID：{winners}")
            except Exception:
                pass

        logger.info(f"开奖: id={lottery_id} winners={winners}")

    except Exception as e:
        logger.error(f"开奖异常: {e}")


def handle_manual_draw(bot, m, config, db, lottery_id):
    """手动开奖（当定时任务未触发时的备用方案）"""
    uid = m.from_user.id
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可手动开奖")
        return

    _draw_lottery(bot, lottery_id, config, db)
