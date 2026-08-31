"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/vote_kick.py  ·  投票踢人模块                                 ║
║                                                                        ║
║  功能：群成员投票踢人机制                                               ║
║                                                                        ║
║  handle_vote_kick()       -> 发起投票踢人                               ║
║  handle_vote_kick_callback() -> 处理投票按钮回调                        ║
║  check_expired_votes()    -> 检查并关闭过期投票                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import time
from contextlib import contextmanager
from threading import RLock

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("vote_kick")

# 投票通过条件
PASS_MIN_YES = 5          # 最低赞成票数
PASS_RATE = 0.6           # 赞成率阈值
MIN_ELAPSED_SEC = 300     # 最短投票时长（5分钟）
# 投票配置
VOTE_DURATION_SEC = 600   # 投票总时长（10分钟）

# 只串行化本模块的“数据库认领 -> Telegram 动作 -> 最终落库”流程。
# 不能在网络调用期间持有全局数据库锁，否则会拖慢其他机器人功能。
_vote_flow_lock = RLock()


@contextmanager
def _transaction(db):
    """投票写事务：执行或提交任一步失败都完整回滚并上抛。"""
    with _db_lock:
        try:
            yield db.conn
            db.conn.commit()
        except Exception:
            try:
                db.conn.rollback()
            except Exception as rollback_error:
                logger.error(f"vote_kick 回滚失败: {rollback_error}")
            raise


def _kick_or_confirm_removed(bot, chat_id, target_uid):
    """执行移除；结果不明时用群成员状态收敛为幂等结果。"""
    try:
        bot.kick_chat_member(chat_id, target_uid)
        return
    except Exception as kick_error:
        try:
            member = bot.get_chat_member(chat_id, target_uid)
            member_status = getattr(member, "status", "")
        except Exception:
            raise kick_error
        if member_status == "kicked":
            logger.warning(
                "投票移除请求返回异常，但目标已不在群内: chat=%s target=%s status=%s",
                chat_id,
                target_uid,
                member_status,
            )
            return
        raise kick_error


def handle_vote_kick(bot, m, config, db, target_uid, reason=""):
    """发起投票踢人

    Args:
        bot: TeleBot实例
        m: 触发消息
        config: 配置字典
        db: 数据库实例
        target_uid: 被踢目标UID
        reason: 踢人理由
    """
    chat_id = m.chat.id
    initiator_id = m.from_user.id
    now = int(time.time())
    end_ts = now + VOTE_DURATION_SEC

    # 插入投票记录
    with _transaction(db) as conn:
        cursor = conn.execute(
            "INSERT INTO vote_kicks (chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts) "
            "VALUES (?, ?, ?, ?, '', '', 'active', 0, ?, ?)",
            (chat_id, target_uid, initiator_id, reason, end_ts, now)
        )
        vote_id = cursor.lastrowid

    # 构建投票按钮
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ 赞成踢出", callback_data=f"vk_yes_{vote_id}"),
        InlineKeyboardButton("❌ 反对", callback_data=f"vk_no_{vote_id}")
    )

    # 发送投票消息
    target_mention = f"<a href='tg://user?id={target_uid}'>{target_uid}</a>"
    initiator_mention = f"<a href='tg://user?id={initiator_id}'>{initiator_id}</a>"
    reason_text = f"\n📝 理由：{reason}" if reason else ""
    text = (
        f"⚖️ <b>投票踢人</b>\n"
        f"👤 被踢人：{target_mention}\n"
        f"🎯 发起人：{initiator_mention}"
        f"{reason_text}\n"
        f"━━━━━━━━━━━━━━\n"
        f"✅ 赞成：0  |  ❌ 反对：0\n"
        f"⏱ 投票截止：10分钟后\n"
        f"📋 通过条件：赞成≥{PASS_MIN_YES}票 且 赞成率>{int(PASS_RATE*100)}% 且 投票≥5分钟"
    )

    try:
        sent = bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        # 网络异常可能发生在 Telegram 已接收消息之后；保留 active 记录，
        # 让真实存在的按钮仍可工作，过期任务最终会自动收口。
        logger.error(f"❌ 投票消息发送结果未知，记录已保留: vote_id={vote_id} error={e}")
        raise

    # 消息已经真实发出后，持久化失败不能再冒充“发送失败”并删除记录。
    with _transaction(db) as conn:
        conn.execute("UPDATE vote_kicks SET msg_id=? WHERE id=?", (sent.message_id, vote_id))
    logger.info(f"⚖️ 投票踢人已发起: vote_id={vote_id} target={target_uid} chat={chat_id}")


def handle_vote_kick_callback(bot, call, config, db):
    """处理投票踢人按钮回调

    Args:
        bot: TeleBot实例
        call: CallbackQuery
        config: 配置字典
        db: 数据库实例
    """
    data = call.data
    voter_uid = str(call.from_user.id)

    # 解析回调数据
    try:
        if data.startswith("vk_yes_"):
            vote_id = int(data[7:])
            vote_type = "yes"
        elif data.startswith("vk_no_"):
            vote_id = int(data[6:])
            vote_type = "no"
        else:
            return
    except (ValueError, IndexError):
        return

    # 模块流程锁覆盖“认领 + Telegram 动作 + 完成”，避免回调与定时任务重复踢人。
    notice = None
    vid = chat_id = target_uid = initiator_id = None
    reason = ""
    yes_count = no_count = 0
    status = msg_id = end_ts = ts = 0
    passed = False
    with _vote_flow_lock:
        # 必须在取得流程锁后取时间；等待其他 Telegram 动作期间可能已经跨过截止点。
        now = int(time.time())
        with _transaction(db) as conn:
            row = conn.execute(
                "SELECT id, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts "
                "FROM vote_kicks WHERE id=?", (vote_id,)
            ).fetchone()

            if not row:
                notice = "⚠️ 投票记录不存在"
            else:
                vid, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts = row

                if status == "processing":
                    notice = "投票正在结算，请稍候"
                elif status != "active":
                    notice = "投票已结束"
                elif now >= end_ts:
                    notice = "投票已截止，等待系统结算"
                else:
                    yes_list = [x for x in yes_votes.split(",") if x] if yes_votes else []
                    no_list = [x for x in no_votes.split(",") if x] if no_votes else []

                    if voter_uid in yes_list and vote_type == "yes":
                        notice = "你已经投了赞成票"
                    elif voter_uid in no_list and vote_type == "no":
                        notice = "你已经投了反对票"
                    else:
                        if voter_uid in yes_list:
                            yes_list.remove(voter_uid)
                        if voter_uid in no_list:
                            no_list.remove(voter_uid)

                        if vote_type == "yes":
                            yes_list.append(voter_uid)
                        else:
                            no_list.append(voter_uid)

                        yes_count = len(yes_list)
                        no_count = len(no_list)
                        total_count = yes_count + no_count
                        rate = yes_count / total_count if total_count > 0 else 0
                        passed = (
                            yes_count >= PASS_MIN_YES
                            and rate > PASS_RATE
                            and (now - ts) >= MIN_ELAPSED_SEC
                        )
                        next_status = "processing" if passed else "active"
                        conn.execute(
                            "UPDATE vote_kicks SET yes_votes=?, no_votes=?, status=? WHERE id=?",
                            (",".join(yes_list), ",".join(no_list), next_status, vote_id),
                        )

        if notice:
            bot.answer_callback_query(call.id, notice)
            return

        if passed:
            try:
                # 此时只持模块流程锁，不持全局数据库锁。
                _kick_or_confirm_removed(bot, chat_id, target_uid)
            except Exception as e:
                with _transaction(db) as conn:
                    conn.execute(
                        "UPDATE vote_kicks SET status='active' WHERE id=? AND status='processing'",
                        (vote_id,),
                    )
                logger.error(f"❌ 踢人执行失败，已恢复为可重试: vote_id={vote_id} target={target_uid} error={e}")
                try:
                    bot.answer_callback_query(call.id, "踢人失败，系统稍后会重试")
                except Exception:
                    pass
                raise

            # 踢人成功后才关闭；若提交失败，processing 会被定时任务恢复处理。
            with _transaction(db) as conn:
                conn.execute(
                    "UPDATE vote_kicks SET status='closed_removed' WHERE id=? AND status='processing'",
                    (vote_id,),
                )
            result_text = "✅ 投票通过，已踢出"
            logger.info(f"⚖️ 投票踢人通过: vote_id={vote_id} target={target_uid} yes={yes_count} no={no_count}")

            target_mention = f"<a href='tg://user?id={target_uid}'>{target_uid}</a>"
            reason_text = f"\n📝 理由：{reason}" if reason else ""
            final_text = (
                f"⚖️ <b>投票踢人 - 已结束</b>\n"
                f"👤 被踢人：{target_mention}\n"
                f"━━━━━━━━━━━━━━\n"
                f"✅ 赞成：{yes_count}  |  ❌ 反对：{no_count}\n"
                f"{result_text}"
                f"{reason_text}"
            )
            try:
                bot.edit_message_text(final_text, chat_id, msg_id, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            bot.answer_callback_query(call.id, f"投票通过！赞成{yes_count}票，反对{no_count}票")
            return

        # 投票未通过，更新消息中的票数
        remaining = max(0, end_ts - now)
        remaining_min = remaining // 60
        remaining_sec = remaining % 60
        time_str = f"{remaining_min}分{remaining_sec}秒" if remaining > 0 else "已截止"

        target_mention = f"<a href='tg://user?id={target_uid}'>{target_uid}</a>"
        initiator_mention = f"<a href='tg://user?id={initiator_id}'>{initiator_id}</a>"
        reason_text = f"\n📝 理由：{reason}" if reason else ""
        updated_text = (
            f"⚖️ <b>投票踢人</b>\n"
            f"👤 被踢人：{target_mention}\n"
            f"🎯 发起人：{initiator_mention}"
            f"{reason_text}\n"
            f"━━━━━━━━━━━━━━\n"
            f"✅ 赞成：{yes_count}  |  ❌ 反对：{no_count}\n"
            f"⏱ 剩余时间：{time_str}\n"
            f"📋 通过条件：赞成≥{PASS_MIN_YES}票 且 赞成率>{int(PASS_RATE*100)}% 且 投票≥5分钟"
        )

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ 赞成踢出", callback_data=f"vk_yes_{vote_id}"),
            InlineKeyboardButton("❌ 反对", callback_data=f"vk_no_{vote_id}")
        )

        try:
            bot.edit_message_text(updated_text, chat_id, msg_id, parse_mode="HTML", reply_markup=markup)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        vote_label = "赞成" if vote_type == "yes" else "反对"
        bot.answer_callback_query(call.id, f"已投{vote_label}票（赞成{yes_count}/反对{no_count}）")


def check_expired_votes(bot, config, db):
    """检查并关闭过期投票（由统一调度器定期调用）

    Args:
        bot: TeleBot实例
        config: 配置字典
        db: 数据库实例
    """
    # 一次只认领一条；失败时保留其余记录，下一轮继续，且本次任务明确报错。
    with _vote_flow_lock:
        now = int(time.time())
        while True:
            with _transaction(db) as conn:
                row = conn.execute(
                    "SELECT id, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, msg_id, end_ts, ts "
                    "FROM vote_kicks "
                    "WHERE status='processing' OR (status='active' AND end_ts<?) "
                    "ORDER BY CASE WHEN status='processing' THEN 0 ELSE 1 END, end_ts, id LIMIT 1",
                    (now,),
                ).fetchone()
                if not row:
                    return
                vid = row[0]
                conn.execute(
                    "UPDATE vote_kicks SET status='processing' "
                    "WHERE id=? AND status IN ('active','processing')",
                    (vid,),
                )

            vid, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, msg_id, end_ts, ts = row

            yes_list = [x for x in yes_votes.split(",") if x] if yes_votes else []
            no_list = [x for x in no_votes.split(",") if x] if no_votes else []
            yes_count = len(yes_list)
            no_count = len(no_list)
            total_count = yes_count + no_count
            rate = yes_count / total_count if total_count > 0 else 0

            target_mention = f"<a href='tg://user?id={target_uid}'>{target_uid}</a>"
            reason_text = f"\n📝 理由：{reason}" if reason else ""

            if yes_count >= PASS_MIN_YES and rate > PASS_RATE:
                try:
                    _kick_or_confirm_removed(bot, chat_id, target_uid)
                except Exception as e:
                    with _transaction(db) as conn:
                        conn.execute(
                            "UPDATE vote_kicks SET status='active' WHERE id=? AND status='processing'",
                            (vid,),
                        )
                    logger.error(f"❌ 过期投票踢人失败，已恢复为可重试: vote_id={vid} error={e}")
                    raise
                result_text = "✅ 投票通过，已踢出"
                logger.info(f"⚖️ 过期投票自动通过: vote_id={vid} target={target_uid}")
            else:
                result_text = "❌ 投票未通过（赞成票不足或赞成率不够）"
                logger.info(f"⚖️ 过期投票未通过: vote_id={vid} yes={yes_count} no={no_count}")

            final_status = "closed_removed" if yes_count >= PASS_MIN_YES and rate > PASS_RATE else "closed_rejected"
            with _transaction(db) as conn:
                conn.execute(
                    "UPDATE vote_kicks SET status=? WHERE id=? AND status='processing'",
                    (final_status, vid),
                )

            final_text = (
                f"⚖️ <b>投票踢人 - 已结束</b>\n"
                f"👤 被踢人：{target_mention}\n"
                f"━━━━━━━━━━━━━━\n"
                f"✅ 赞成：{yes_count}  |  ❌ 反对：{no_count}\n"
                f"{result_text}"
                f"{reason_text}"
            )
            try:
                bot.edit_message_text(final_text, chat_id, msg_id, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
