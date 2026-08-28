"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/zombie_clean.py  ·  僵尸号清理模块                             ║
║                                                                        ║
║  功能：扫描并清理群内已注销的僵尸账号。                                 ║
║                                                                        ║
║  handle_zombies()         -> 扫描僵尸号，展示结果并等待确认              ║
║  handle_zombies_confirm() -> 确认清理回调，执行踢出                      ║
║                                                                        ║
║  原理：对数据库中记录的群成员逐一调用 bot.kick_chat_member()，          ║
║        已注销账号可被成功踢出，正常账号会报错跳过。                      ║
║        管理员自动跳过。                                                 ║
║                                                                        ║
║  数据表：zombie_scans（扫描记录）+ admin_logs（操作日志）               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from core.database import _db_lock
from core.logging_util import get_logger

logger = get_logger("zombie_clean")

# 每次扫描最大检查用户数（防止API限流）
MAX_SCAN_USERS = 200


def _log_action(db, chat_id: int, operator_uid: int, target_uid: int, action: str, reason: str = ""):
    """记录管理员操作到admin_logs表"""
    now = int(time.time())
    with _db_lock:
        db.conn.execute(
            "INSERT INTO admin_logs (chat_id, operator_uid, target_uid, action, reason, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, operator_uid, target_uid, action, reason, now),
        )
        db.conn.commit()


def handle_zombies(bot, m, config: dict, db):
    """
    扫描群内僵尸账号。
    从数据库users表中获取本群成员，逐一尝试kick来检测已注销账号。
    发现僵尸号后展示数量，管理员点击确认后执行清理。

    Args:
        bot: TeleBot实例
        m: 触发消息
        config: 配置字典
        db: 数据库实例
    """
    chat_id = m.chat.id
    operator_uid = m.from_user.id

    # 获取群管理员列表（跳过管理员不踢）
    try:
        admins = bot.get_chat_administrators(chat_id)
        admin_uids = {a.user.id for a in admins}
    except Exception as e:
        bot.reply_to(m, "⚠️ 获取管理员列表失败，请稍后重试或联系管理员")
        logger.warning("获取管理员列表失败: chat=%s error=%s", chat_id, e)
        return

    # 从数据库获取本群已知用户
    with _db_lock:
        rows = db.conn.execute(
            "SELECT uid FROM users ORDER BY last_active DESC LIMIT ?",
            (MAX_SCAN_USERS,),
        ).fetchall()

    if not rows:
        bot.reply_to(m, "📋 数据库中没有用户记录，无法扫描。")
        return

    # 发送扫描中提示
    scanning_msg = bot.reply_to(m, f"🔍 正在扫描僵尸号，共 {len(rows)} 个用户待检查...")

    zombie_uids = []
    checked = 0

    for (uid,) in rows:
        # 跳过管理员
        if uid in admin_uids:
            continue
        # 跳过机器人自己
        try:
            if uid == bot.get_me().id:
                continue
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        checked += 1
        try:
            # 使用 get_chat_member 安全检测，不会踢出真实用户
            member = bot.get_chat_member(chat_id, uid)
            # status: "left" 或 "kicked" 表示已离开或被踢，属于僵尸号
            if member.status in ("left", "kicked"):
                zombie_uids.append(uid)
                logger.debug("发现僵尸号: uid=%s status=%s", uid, member.status)
            else:
                logger.debug("正常用户: uid=%s status=%s", uid, member.status)
        except Exception as e:
            err_str = str(e).lower()
            # 如果用户不存在或查询失败，可能也是僵尸号
            if "user not found" in err_str or "user is not a member" in err_str:
                zombie_uids.append(uid)
                logger.debug("发现僵尸号(查询不到): uid=%s", uid)
            else:
                logger.debug("检查用户 uid=%s 时异常: %s", uid, e)

        # 避免API限流，每20个用户暂停一下
        if checked % 20 == 0:
            time.sleep(0.5)

    # 删除扫描中提示（受全局开关控制）
    if config.get("ENABLE_MESSAGE_DELETION", False):
        try:
            bot.delete_message(chat_id, scanning_msg.message_id)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    if not zombie_uids:
        bot.reply_to(m, f"✅ 扫描完成！检查了 {checked} 个用户，未发现僵尸号。")
        logger.info("僵尸号扫描无结果: chat=%s checked=%s", chat_id, checked)
        return

    # 记录扫描结果到数据库
    now = int(time.time())
    zombie_str = ",".join(str(u) for u in zombie_uids)
    with _db_lock:
        cursor = db.conn.execute(
            "INSERT INTO zombie_scans (chat_id, operator_uid, zombie_uids, status, ts) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (chat_id, operator_uid, zombie_str, now),
        )
        scan_id = cursor.lastrowid
        db.conn.commit()

    # 展示结果 + 确认按钮
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ 确认清理", callback_data=f"zc_confirm_{scan_id}"),
        InlineKeyboardButton("❌ 取消", callback_data=f"zc_cancel_{scan_id}"),
    )

    text = (
        f"🧟 <b>僵尸号扫描结果</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔍 检查用户数：{checked}\n"
        f"🧟 发现僵尸号：<b>{len(zombie_uids)}</b> 个\n"
        f"━━━━━━━━━━━━━━\n"
        f"点击「确认清理」将踢出这些已注销账号。"
    )

    try:
        sent = bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        # 更新消息ID
        with _db_lock:
            db.conn.execute("UPDATE zombie_scans SET msg_id=? WHERE id=?", (sent.message_id, scan_id))
            db.conn.commit()
    except Exception as e:
        bot.reply_to(m, "⚠️ 发送扫描结果失败，请稍后重试或联系管理员")
        logger.error("发送僵尸号扫描结果失败: %s", e)

    logger.info("僵尸号扫描完成: chat=%s found=%s checked=%s", chat_id, len(zombie_uids), checked)


def handle_zombies_confirm(bot, call, config: dict, db):
    """
    处理僵尸号清理确认/取消回调。

    Args:
        bot: TeleBot实例
        call: CallbackQuery
        config: 配置字典
        db: 数据库实例
    """
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    # 解析回调数据
    try:
        if data.startswith("zc_confirm_"):
            scan_id = int(data[11:])
            action = "confirm"
        elif data.startswith("zc_cancel_"):
            scan_id = int(data[10:])
            action = "cancel"
        else:
            return
    except (ValueError, IndexError):
        return

    # 查询扫描记录
    with _db_lock:
        row = db.conn.execute(
            "SELECT id, chat_id, operator_uid, zombie_uids, status, msg_id, ts "
            "FROM zombie_scans WHERE id=?",
            (scan_id,),
        ).fetchone()

    if not row:
        bot.answer_callback_query(call.id, "⚠️ 扫描记录不存在")
        return

    vid, scan_chat_id, operator_uid, zombie_str, status, scan_msg_id, ts = row

    # 校验群ID
    if scan_chat_id != chat_id:
        bot.answer_callback_query(call.id, "⚠️ 无效操作")
        return

    # 检查是否已处理
    if status != "pending":
        bot.answer_callback_query(call.id, "此扫描已处理")
        return

    if action == "cancel":
        # 取消清理
        with _db_lock:
            db.conn.execute("UPDATE zombie_scans SET status='cancelled' WHERE id=?", (scan_id,))
            db.conn.commit()

        try:
            bot.edit_message_text(
                "🧟 僵尸号清理已取消。",
                chat_id, msg_id,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        bot.answer_callback_query(call.id, "已取消清理")
        logger.info("僵尸号清理取消: scan_id=%s chat=%s", scan_id, chat_id)
        return

    # 确认清理
    zombie_uids = [int(u) for u in zombie_str.split(",") if u]
    kicked = 0
    failed = 0

    for uid in zombie_uids:
        try:
            bot.kick_chat_member(chat_id, uid)
            kicked += 1
            # 记录操作日志
            _log_action(db, chat_id, operator_uid, uid, "zombie_kick", "僵尸号清理")
        except Exception as e:
            failed += 1
            logger.warning("踢出僵尸号失败: uid=%s error=%s", uid, e)

    # 更新扫描状态
    with _db_lock:
        db.conn.execute("UPDATE zombie_scans SET status='done' WHERE id=?", (scan_id,))
        db.conn.commit()

    # 更新消息
    result_text = (
        f"🧟 <b>僵尸号清理完成</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🧟 发现：{len(zombie_uids)} 个\n"
        f"✅ 已踢出：{kicked} 个\n"
        f"{'❌ 失败：' + str(failed) + ' 个' if failed else ''}"
    )

    try:
        bot.edit_message_text(result_text, chat_id, msg_id, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    bot.answer_callback_query(call.id, f"清理完成！踢出{kicked}个僵尸号")
    logger.info("僵尸号清理完成: scan_id=%s kicked=%s failed=%s", scan_id, kicked, failed)
