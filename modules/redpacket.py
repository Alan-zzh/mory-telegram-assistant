"""
红包系统 - 发红包/抢红包 + 随机/均分模式 + 过期退回

功能：
  1. 管理员发红包（随机/均分两种模式）
  2. 用户点击按钮抢红包
  3. 随机模式：金额随机分配，保证每人至少1积分
  4. 均分模式：每人等额
  5. 抢完后自动公布明细

命令：
  红包 金额 数量 [均] → handle_send_redpacket
  回调 rp_{id} → handle_claim_redpacket

数据表：
  redpackets（id, sender_id, chat_id, total_points, count, remaining, mode, msg_id, expired, ts）
  redpacket_claims（id, redpacket_id, uid, amount, ts）
"""
import time
import random

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("redpacket")


def handle_send_redpacket(bot, m, config, db, args):
    """发红包：红包 金额 数量 [均]"""
    uid = m.from_user.id
    chat_id = m.chat.id

    # 权限检查
    admin_id = config.get("ADMIN_ID", 0)
    admin_ids = config.get("ADMIN_IDS", [])
    if uid != admin_id and uid not in admin_ids:
        bot.reply_to(m, "❌ 仅管理员可发红包")
        return

    try:
        if len(args) < 2:
            bot.reply_to(m, "格式：红包 金额 数量 [均]")
            return

        total = int(args[0])
        count = int(args[1])
        mode = "average" if len(args) > 2 and args[2] in ("均", "均分", "avg") else "random"

        if total <= 0 or count <= 0 or count > 100:
            bot.reply_to(m, "❌ 参数无效（金额>0，数量1-100）")
            return

        # 检查管理员积分
        admin_points = db.get_user_points(uid)
        if admin_points is None or admin_points < total:
            current = admin_points if admin_points is not None else 0
            bot.reply_to(m, f"❌ 积分不足！当前：{current}，需要：{total}")
            return

        now_ts = int(time.time())
        with _db_lock:
            # 在事务内扣积分和创建红包记录，保证原子性
            db.add_points(uid, -total)
            cursor = db.conn.execute(
                "INSERT INTO redpackets (sender_id, chat_id, total_points, count, remaining, mode, expired, ts) VALUES (?,?,?,?,?,?,?,?)",
                (uid, chat_id, total, count, count, mode, 0, now_ts)
            )
            rp_id = cursor.lastrowid
            db.conn.commit()

        # 发送红包消息
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🧧 抢红包", callback_data=f"rp_{rp_id}"))

        mode_text = "均分" if mode == "average" else "随机"
        text = (
            f"🧧 红包来了！\n"
            f"💰 总额：{total}积分 | {count}份\n"
            f"🎲 模式：{mode_text}\n\n"
            f"👇 点击抢红包！"
        )
        msg = bot.send_message(chat_id, text, reply_markup=keyboard)

        # 更新msg_id
        with _db_lock:
            db.conn.execute("UPDATE redpackets SET msg_id=? WHERE id=?", (msg.message_id, rp_id))
            db.conn.commit()

        logger.info(f"红包: id={rp_id} total={total} count={count} mode={mode}")

    except ValueError:
        bot.reply_to(m, "❌ 金额和数量必须是数字")
    except Exception as e:
        logger.error(f"发红包异常: {e}")
        bot.reply_to(m, "❌ 发红包失败")


def handle_claim_redpacket(bot, call, config, db):
    """抢红包回调"""
    data = call.data
    if not data.startswith("rp_"):
        return False

    rp_id = int(data[3:])
    uid = call.from_user.id
    chat_id = call.message.chat.id

    try:
        # 检查红包状态
        rp = db.conn.execute(
            "SELECT sender_id, total_points, count, remaining, mode, expired FROM redpackets WHERE id=?",
            (rp_id,)
        ).fetchone()
        if not rp:
            bot.answer_callback_query(call.id, text="红包不存在", show_alert=True)
            return True

        sender_id, total, count, remaining, mode, expired = rp

        # 不能抢自己的红包
        if uid == sender_id:
            bot.answer_callback_query(call.id, text="不能抢自己的红包哦", show_alert=True)
            return True

        # 检查是否已抢
        claimed = db.conn.execute(
            "SELECT id FROM redpacket_claims WHERE redpacket_id=? AND uid=?",
            (rp_id, uid)
        ).fetchone()
        if claimed:
            bot.answer_callback_query(call.id, text="你已经抢过了！", show_alert=True)
            return True

        # 检查是否已抢完或过期
        if expired or remaining <= 0:
            bot.answer_callback_query(call.id, text="红包已抢完", show_alert=True)
            return True

        # 计算金额
        if mode == "average":
            amount = total // count
        else:
            # 随机模式：保证每人至少1积分
            claimed_total = db.conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM redpacket_claims WHERE redpacket_id=?",
                (rp_id,)
            ).fetchone()[0]
            remaining_total = total - claimed_total
            if remaining == 1:
                # 最后一份：剩余全部
                amount = max(1, remaining_total)
            else:
                # 随机分配，留够剩余每人至少1积分
                max_per_person = round((remaining_total - (remaining - 1)) * 100) / 100  # 留足后面每人1分后的最大可用额
                max_per_person = int(max_per_person)
                avg_remaining = max(1, max_per_person // remaining * 2)
                amount = random.randint(1, max(1, avg_remaining))
                # 确保后面的人至少1分
                amount = min(amount, remaining_total - (remaining - 1))

        amount = max(1, amount)

        # 写入领取记录 + 更新剩余（原子操作）
        now_ts = int(time.time())
        with _db_lock:
            # 再次检查剩余（防止并发超抢）
            current_remaining = db.conn.execute(
                "SELECT remaining FROM redpackets WHERE id=?", (rp_id,)
            ).fetchone()
            if not current_remaining or current_remaining[0] <= 0:
                bot.answer_callback_query(call.id, text="红包已抢完", show_alert=True)
                return True

            # 再次检查是否已抢（防止并发重复抢）
            already = db.conn.execute(
                "SELECT id FROM redpacket_claims WHERE redpacket_id=? AND uid=?",
                (rp_id, uid)
            ).fetchone()
            if already:
                bot.answer_callback_query(call.id, text="你已经抢过了！", show_alert=True)
                return True

            db.conn.execute(
                "INSERT INTO redpacket_claims (redpacket_id, uid, amount, ts) VALUES (?,?,?,?)",
                (rp_id, uid, amount, now_ts)
            )
            db.conn.execute(
                "UPDATE redpackets SET remaining=remaining-1 WHERE id=?",
                (rp_id,)
            )
            db.conn.commit()

        # 积分入账（add_points内部有锁）
        _lv_result = db.add_points(uid, amount)

        bot.answer_callback_query(call.id, text=f"🧧 抢到 {amount} 积分！")

        # 检查升级通知
        if amount > 0:
            from modules.points_enhanced import check_level_up
            _rp_uname = call.from_user.first_name or "用户"
            check_level_up(bot, chat_id, uid, _rp_uname, _lv_result, config)

        # 检查是否抢完
        new_remaining = remaining - 1
        if new_remaining <= 0:
            # 更新消息，公布明细
            claims = db.conn.execute(
                "SELECT uid, amount FROM redpacket_claims WHERE redpacket_id=? ORDER BY ts",
                (rp_id,)
            ).fetchall()
            detail = "\n".join([f"👤 uid={c_uid} → {c_amt}积分" for c_uid, c_amt in claims])
            try:
                bot.edit_message_text(
                    f"🧧 红包已抢完！\n💰 总额：{total}积分 | {count}份\n\n{detail}",
                    chat_id, call.message.message_id
                )
            except Exception:
                pass

        logger.info(f"抢红包: uid={uid} rp_id={rp_id} amount={amount}")

    except Exception as e:
        logger.error(f"抢红包异常: {e}")
        try:
            bot.answer_callback_query(call.id, text="❌ 抢红包失败")
        except Exception:
            pass

    return True


def check_expired_redpackets(bot, config, db):
    """检查过期红包，退回未领取积分（由auto_tasks定期调用）

    Args:
        bot: TeleBot实例
        config: 配置字典
        db: 数据库实例
    """
    expire_hours = config.get("REDPACKET_EXPIRE_HOURS", 24)
    cutoff = int(time.time()) - expire_hours * 3600

    try:
        # 查找所有未过期且已超时的红包
        rows = db.conn.execute(
            "SELECT id, sender_id, chat_id, total_points, msg_id FROM redpackets WHERE expired=0 AND ts<?",
            (cutoff,)
        ).fetchall()

        if not rows:
            return

        for rp_id, sender_id, chat_id, total_points, msg_id in rows:
            # 计算已领取总额
            claimed_total = db.conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM redpacket_claims WHERE redpacket_id=?",
                (rp_id,)
            ).fetchone()[0]

            remaining = total_points - claimed_total

            # 原子操作：标记过期 + 退回剩余积分（同一事务）
            with _db_lock:
                db.conn.execute("UPDATE redpackets SET expired=1 WHERE id=?", (rp_id,))
                if remaining > 0:
                    db.conn.execute(
                        "UPDATE user_levels SET points=points+? WHERE uid=?", (remaining, sender_id)
                    )
                    db.conn.execute(
                        "INSERT INTO points_log (uid, delta, reason, ts) VALUES (?,?,?,?)",
                        (sender_id, remaining, f"红包过期退回:rp={rp_id}", int(time.time()))
                    )
                db.conn.commit()

            # 尝试编辑红包消息
            if msg_id:
                try:
                    bot.edit_message_text(
                        f"🧧 红包已过期\n💰 总额：{total_points}积分\n⏰ 未抢完的{remaining}积分已退回",
                        chat_id, msg_id
                    )
                except Exception:
                    pass

            logger.info(f"红包过期退回: rp_id={rp_id} sender={sender_id} 退回={remaining}积分")

    except Exception as e:
        logger.error(f"红包过期检查异常: {e}")
