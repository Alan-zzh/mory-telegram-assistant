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


def _safe_commit(db):
    """安全提交：sqlite3 连接在 autocommit 模式下 commit() 会抛
    'cannot commit - no transaction is active'，此处降级为 debug 留痕。"""
    try:
        db.conn.commit()
    except Exception as e:
        logger.debug(f"vote_kick commit跳过（无活动事务，非致命）：{e}")


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
    cursor = db.conn.execute(
        "INSERT INTO vote_kicks (chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts) "
        "VALUES (?, ?, ?, ?, '', '', 'active', 0, ?, ?)",
        (chat_id, target_uid, initiator_id, reason, end_ts, now)
    )
    vote_id = cursor.lastrowid
    _safe_commit(db)

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
        # 更新消息ID
        db.conn.execute("UPDATE vote_kicks SET msg_id=? WHERE id=?", (sent.message_id, vote_id))
        _safe_commit(db)
        logger.info(f"⚖️ 投票踢人已发起: vote_id={vote_id} target={target_uid} chat={chat_id}")
    except Exception as e:
        logger.error(f"❌ 发送投票消息失败: {e}")
        # 清理已插入的记录
        db.conn.execute("DELETE FROM vote_kicks WHERE id=?", (vote_id,))
        _safe_commit(db)


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

    # 计票临界区：读-改-写全程持全局数据库锁，防止并发按钮点击互相覆盖丢票
    notice = None
    vid = chat_id = target_uid = initiator_id = None
    reason = ""
    yes_count = no_count = 0
    status = msg_id = end_ts = ts = 0
    with _db_lock:
        row = db.conn.execute(
            "SELECT id, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts "
            "FROM vote_kicks WHERE id=?", (vote_id,)
        ).fetchone()

        if not row:
            notice = "⚠️ 投票记录不存在"
        else:
            vid, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, status, msg_id, end_ts, ts = row

            if status != "active":
                notice = "投票已结束"
            else:
                # 解析已有投票
                yes_list = [x for x in yes_votes.split(",") if x] if yes_votes else []
                no_list = [x for x in no_votes.split(",") if x] if no_votes else []

                # 检查是否已投票（切换投票需先移除旧票）
                if voter_uid in yes_list and vote_type == "yes":
                    notice = "你已经投了赞成票"
                elif voter_uid in no_list and vote_type == "no":
                    notice = "你已经投了反对票"
                else:
                    # 移除旧票（允许改投）
                    if voter_uid in yes_list:
                        yes_list.remove(voter_uid)
                    if voter_uid in no_list:
                        no_list.remove(voter_uid)

                    # 添加新票
                    if vote_type == "yes":
                        yes_list.append(voter_uid)
                    else:
                        no_list.append(voter_uid)

                    yes_count = len(yes_list)
                    no_count = len(no_list)

                    # 更新数据库
                    new_yes = ",".join(yes_list)
                    new_no = ",".join(no_list)
                    db.conn.execute(
                        "UPDATE vote_kicks SET yes_votes=?, no_votes=? WHERE id=?",
                        (new_yes, new_no, vote_id)
                    )
                    _safe_commit(db)

    if notice:
        bot.answer_callback_query(call.id, notice)
        return

    # 检查是否通过（锁外执行，踢人为网络操作不占数据库锁）
    now = int(time.time())
    elapsed = now - ts
    total_count = yes_count + no_count
    rate = yes_count / total_count if total_count > 0 else 0

    if yes_count >= PASS_MIN_YES and rate > PASS_RATE and elapsed >= MIN_ELAPSED_SEC:
        # 投票通过，执行踢人
        try:
            bot.kick_chat_member(chat_id, target_uid)
            result_text = "✅ 投票通过，已踢出"
            logger.info(f"⚖️ 投票踢人通过: vote_id={vote_id} target={target_uid} yes={yes_count} no={no_count}")
        except Exception as e:
            result_text = f"⚠️ 投票通过但踢人失败：{e}"
            logger.error(f"❌ 踢人执行失败: vote_id={vote_id} target={target_uid} error={e}")

        # 关闭投票
        db.conn.execute("UPDATE vote_kicks SET status='closed' WHERE id=?", (vote_id,))
        _safe_commit(db)

        # 更新消息
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
    else:
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
    """检查并关闭过期投票（由auto_tasks定期调用）

    Args:
        bot: TeleBot实例
        config: 配置字典
        db: 数据库实例
    """
    now = int(time.time())

    # 查找所有已过期的活跃投票
    rows = db.conn.execute(
        "SELECT id, chat_id, target_uid, initiator_id, reason, yes_votes, no_votes, msg_id, end_ts, ts "
        "FROM vote_kicks WHERE status='active' AND end_ts<?",
        (now,)
    ).fetchall()

    if not rows:
        return

    for row in rows:
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
            # 投票通过，执行踢人
            try:
                bot.kick_chat_member(chat_id, target_uid)
                result_text = "✅ 投票通过，已踢出"
                logger.info(f"⚖️ 过期投票自动通过: vote_id={vid} target={target_uid}")
            except Exception as e:
                result_text = f"⚠️ 投票通过但踢人失败：{e}"
                logger.error(f"❌ 过期投票踢人失败: vote_id={vid} error={e}")
        else:
            result_text = "❌ 投票未通过（赞成票不足或赞成率不够）"
            logger.info(f"⚖️ 过期投票未通过: vote_id={vid} yes={yes_count} no={no_count}")

        # 关闭投票
        db.conn.execute("UPDATE vote_kicks SET status='closed' WHERE id=?", (vid,))
        _safe_commit(db)

        # 更新消息
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
