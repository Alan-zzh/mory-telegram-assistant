"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/verification.py  ·  入群验证码模块                           ║
║                                                                        ║
║  功能：新人入群时发送验证码，防止机器人/广告号进群。                     ║
║
║  验证模式：                                                            ║
║    - button: 按钮验证（点击指定按钮通过）                                ║
║    - math: 数学题验证（回答简单算术题）                                  ║
║    - text: 文字验证（输入指定文字）                                    ║
║
║  流程：                                                                ║
║    1. 新人入群 → 自动禁言                                              ║
║    2. 发送验证码消息 + 键盘（60秒超时）                                  ║
║    3. 用户作答 → 验证通过则解禁，失败扣次数                              ║
║    4. 60秒超时或错误3次 → 踢出群组                                     ║
║
║  被调用：main.py P0 消息分发入口                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import random
import time
import threading
from core.logging_util import get_logger

logger = get_logger("verification")


# 验证码会话存储（内存级，进程内有效，双写 SQLite 用于重启恢复）
# { (chat_id, user_id): { "answer": str, "attempts": int, "timeout_ts": float, "msg_id": int, "mode": str, "started_ts": int } }
_verification_sessions = {}
_verification_lock = threading.Lock()
_VERIFICATION_SESSIONS_MAX = 1000  # 容量上限，防止内存泄漏

# 模块级 DB 引用，由 restore_sessions_on_startup 在启动时注入
# 双写策略：内存优先读（性能），SQLite 用于重启恢复（持久化）
_db = None
# 降级告警标志：db 为 None 时只告警一次，避免日志噪音
_db_none_warned = False


def _warn_db_none_once():
    """db 为 None 时输出一次 warning，便于运维感知降级状态"""
    global _db_none_warned
    if not _db_none_warned:
        _db_none_warned = True
        logger.warning(
            "⚠️ verification._db 为 None（restore_sessions_on_startup 未被调用或失败），"
            "验证码会话 SQLite 双写已降级为静默跳过。重启后无法恢复未完成验证的会话，"
            "可能导致部分新成员永久禁言。请检查 main.py 启动流程是否调用了 restore_sessions_on_startup。"
        )


def _save_session_to_db(db, chat_id, user_id, session_data):
    """将验证会话写入 SQLite（双写策略：内存优先读，SQLite 用于重启恢复）"""
    if db is None:
        _warn_db_none_once()
        return
    try:
        with db.lock:
            with db.conn:
                db.conn.execute("""
                    INSERT OR REPLACE INTO verification_sessions
                    (chat_id, user_id, answer, attempts, max_attempts, timeout_ts,
                     msg_id, mode, user_name, started_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chat_id, user_id, session_data.get("answer", ""),
                    session_data.get("attempts", 0), session_data.get("max_attempts", 3),
                    session_data.get("timeout_ts", 0.0), session_data.get("msg_id"),
                    session_data.get("mode", "button"), session_data.get("user_name", ""),
                    int(session_data.get("started_ts", time.time())),
                ))
    except Exception as e:
        logger.error(f"保存验证会话到 SQLite 失败 chat={chat_id} uid={user_id}: {e}")


def _load_session_from_db(db, chat_id, user_id):
    """从 SQLite 加载单个验证会话，返回 dict 或 None"""
    if db is None:
        return None
    try:
        c = db.conn.cursor()
        c.execute("""
            SELECT answer, attempts, max_attempts, timeout_ts, msg_id, mode,
                   user_name, started_ts
            FROM verification_sessions WHERE chat_id=? AND user_id=?
        """, (chat_id, user_id))
        row = c.fetchone()
        if not row:
            return None
        return {
            "answer": row[0],
            "attempts": row[1],
            "max_attempts": row[2],
            "timeout_ts": row[3],
            "msg_id": row[4],
            "mode": row[5],
            "user_name": row[6],
            "started_ts": row[7],
        }
    except Exception as e:
        logger.error(f"从 SQLite 加载验证会话失败 chat={chat_id} uid={user_id}: {e}")
        return None


def _delete_session_from_db(db, chat_id, user_id):
    """从 SQLite 删除验证会话"""
    if db is None:
        return
    try:
        with db.lock:
            with db.conn:
                db.conn.execute(
                    "DELETE FROM verification_sessions WHERE chat_id=? AND user_id=?",
                    (chat_id, user_id),
                )
    except Exception as e:
        logger.error(f"从 SQLite 删除验证会话失败 chat={chat_id} uid={user_id}: {e}")


def generate_math_question():
    """生成数学题，返回 (question, answer)。
    难度适中，目标正常人 30 秒内可解。
    答案范围：加法 2-100、减法 0-49、乘法 4-225、混合运算 4-100。
    """
    ops = [
        (lambda: (random.randint(1, 50), random.randint(1, 50)), lambda a, b: a + b, "+"),
        (lambda: (random.randint(10, 50), random.randint(1, 20)), lambda a, b: a - b, "-"),
        (lambda: (random.randint(2, 15), random.randint(2, 15)), lambda a, b: a * b, "×"),
    ]
    # 15% 概率出混合运算 (a + b) × c，降低难度保持在 30 秒可解范围
    if random.random() < 0.15:
        a = random.randint(1, 10)
        b = random.randint(1, 10)
        c = random.randint(2, 3)
        answer = (a + b) * c
        return f"({a} + {b}) × {c} = ?", str(answer)
    gen, calc, op = random.choice(ops)
    a, b = gen()
    # 确保减法不为负
    if op == "-" and a < b:
        a, b = b, a
    return f"{a} {op} {b} = ?", str(calc(a, b))


def generate_text_challenge():
    """生成文字验证码，返回 (question, answer)"""
    texts = ["你好", "通过", "进群", "验证", "确认"]
    answer = random.choice(texts)
    return f"请在群里发送文字：「{answer}」", answer


def start_verification(bot, chat_id, user_id, user_name, config: dict):
    """
    启动验证码流程
    返回 (captcha_text, answer, inline_keyboard, mode)
    """
    mode = config.get("VERIFICATION_CONFIG", {}).get("mode", "button")
    timeout = config.get("VERIFICATION_CONFIG", {}).get("timeout", 60)
    max_attempts = config.get("VERIFICATION_CONFIG", {}).get("max_attempts", 3)

    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    if mode == "button":
        btn_text = "✅ 点我验证"
        answer = "button_click"
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text=btn_text, callback_data="verify_pass"))
        question = f" {user_name}，请点击下方按钮完成验证！"

    elif mode == "math":
        question, answer = generate_math_question()
        question = f"👋 {user_name}，{question}（请在群里回复答案，60秒内完成）"
        keyboard = None

    elif mode == "text":
        question, answer = generate_text_challenge()
        question = f" {user_name}，{question}"
        keyboard = None

    else:
        # 默认button模式
        btn_text = "✅ 点我验证"
        answer = "button_click"
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text=btn_text, callback_data="verify_pass"))
        question = f" {user_name}，请点击下方按钮完成验证！"

    # 保存会话（线程安全 + 容量上限防护）
    now = time.time()
    session_data = {
        "answer": answer,
        "attempts": 0,
        "max_attempts": max_attempts,
        "timeout_ts": now + timeout,
        "msg_id": None,
        "mode": mode,
        "user_name": user_name,
        "started_ts": int(now),
    }
    with _verification_lock:
        if len(_verification_sessions) > _VERIFICATION_SESSIONS_MAX:
            # 优先清理已超时的会话，避免误删活跃会话
            now_ts = time.time()
            expired_keys = [k for k, v in _verification_sessions.items()
                            if now_ts > v.get("timeout_ts", 0)]
            for k in expired_keys:
                del _verification_sessions[k]
            # 如果清理已超时会话后仍超限，才按 timeout_ts 删最早（并记录 warning）
            if len(_verification_sessions) > _VERIFICATION_SESSIONS_MAX:
                sorted_keys = sorted(
                    _verification_sessions.keys(),
                    key=lambda k: _verification_sessions[k].get("timeout_ts", 0)
                )
                remove_count = len(_verification_sessions) - _VERIFICATION_SESSIONS_MAX + 1
                for k in sorted_keys[:remove_count]:
                    del _verification_sessions[k]
                logger.warning(f"⚠️ 验证会话容量超限且无已超时会话，强制清理 {remove_count} 个最早活跃会话（可能误删）")
            elif expired_keys:
                logger.info(f"🧹 验证会话容量超限，清理 {len(expired_keys)} 个已超时会话")
        _verification_sessions[(chat_id, user_id)] = session_data

    # 双写：同步到 SQLite（用于重启恢复）
    _save_session_to_db(_db, chat_id, user_id, session_data)

    # 启动超时定时器
    timer = threading.Timer(timeout, _verification_timeout, args=(bot, chat_id, user_id))
    timer.daemon = True
    timer.start()

    return question, keyboard


def _verification_timeout(bot, chat_id, user_id):
    """验证码超时处理"""
    key = (chat_id, user_id)
    with _verification_lock:
        session = _verification_sessions.pop(key, None)
    if session:
        # 同步删除 SQLite 记录，避免重启后残留
        _delete_session_from_db(_db, chat_id, user_id)
        logger.warning(f"⏰ 验证码超时: uid={user_id} chat_id={chat_id}")
        try:
            bot.send_message(chat_id, f"⏰ {session['user_name']} 验证超时，已移出群组")
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        try:
            bot.send_message(user_id,
                f"⏰ 你在群组中验证超时，已被移出。\n"
                f"如需重新加入，请通过群链接重新申请，入群后请及时完成验证。"
            )
        except Exception as e:
            logger.debug(f"私聊超时用户失败 uid={user_id}: {e}")
        try:
            bot.kick_chat_member(chat_id, user_id)
            bot.unban_chat_member(chat_id, user_id)  # 允许重新被邀请
        except Exception as e:
            logger.error(f"踢出超时用户失败 uid={user_id}: {e}")


def check_callback_query(bot, callback_query, config: dict):
    """
    处理验证码按钮点击
    返回 True 表示已处理（验证通过/失败）
    """
    if callback_query.data != "verify_pass":
        return False

    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    key = (chat_id, user_id)

    # 【P1-NEW-01】超时自检：Timer 是 daemon 线程，Bot 异常退出时可能未触发，
    # 此处兜底检测超时会话并手动清理，避免用户被永久禁言
    with _verification_lock:
        session = _verification_sessions.get(key)
    if session and time.time() > session.get("timeout_ts", 0):
        logger.warning(f"检测到超时未处理的验证会话 uid={user_id}, 手动清理")
        _verification_timeout(bot, chat_id, user_id)
        return True

    cb_notice = None
    session = None
    with _verification_lock:
        if key not in _verification_sessions:
            cb_notice = "验证已过期"
        else:
            s = _verification_sessions[key]
            if s["mode"] != "button":
                cb_notice = "此验证不需要点击按钮"
            else:
                # 验证通过：持锁摘除会话，防止并发双消费
                del _verification_sessions[key]
                session = s

    if cb_notice:
        bot.answer_callback_query(callback_query.id, text=cb_notice)
        return False
    if session is None:
        return False

    # 同步删除 SQLite 记录
    _delete_session_from_db(_db, chat_id, user_id)
    bot.answer_callback_query(callback_query.id, text="✅ 验证通过！")

    # 编辑原消息
    try:
        bot.edit_message_text(
            f"✅ {session['user_name']} 验证通过！",
            chat_id=chat_id,
            message_id=callback_query.message.message_id,
        )
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # 解禁用户
    try:
        from telebot.types import ChatPermissions
        bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
    except Exception as e:
        logger.error(f"解禁验证通过用户失败 uid={user_id}: {e}")

    logger.info(f"✅ 验证通过: uid={user_id} chat_id={chat_id}")
    return True


def check_verification_answer(bot, m, config: dict) -> bool:
    """
    检查用户的验证码回答
    返回 True 表示是验证消息（已处理），False 表示不是验证消息
    """
    chat_id = m.chat.id
    user_id = m.from_user.id
    key = (chat_id, user_id)

    with _verification_lock:
        if key not in _verification_sessions:
            return False

        session = _verification_sessions[key]

        # 检查是否超时
        if time.time() > session["timeout_ts"]:
            del _verification_sessions[key]
            _delete_session_from_db(_db, chat_id, user_id)
            return False

        # 检查答案
        user_answer = (m.text or "").strip()
        if session["mode"] == "math":
            if user_answer == session["answer"]:
                # 验证通过
                del _verification_sessions[key]
                _delete_session_from_db(_db, chat_id, user_id)
                _do_verify_pass(bot, chat_id, user_id, session)
                return True
            else:
                # 验证失败
                session["attempts"] += 1
                if session["attempts"] >= session["max_attempts"]:
                    del _verification_sessions[key]
                    _delete_session_from_db(_db, chat_id, user_id)
                    _do_verify_fail(bot, chat_id, user_id, session)
                else:
                    remaining = session["max_attempts"] - session["attempts"]
                    bot.send_message(chat_id, f"❌ 答案错误！还有 {remaining} 次机会")
                    logger.warning(f"❌ 验证错误 {session['attempts']}/{session['max_attempts']}: uid={user_id}")
                return True

        elif session["mode"] == "text":
            if user_answer.lower() == session["answer"].lower():
                del _verification_sessions[key]
                _delete_session_from_db(_db, chat_id, user_id)
                _do_verify_pass(bot, chat_id, user_id, session)
                return True
            else:
                session["attempts"] += 1
                if session["attempts"] >= session["max_attempts"]:
                    del _verification_sessions[key]
                    _delete_session_from_db(_db, chat_id, user_id)
                    _do_verify_fail(bot, chat_id, user_id, session)
                else:
                    remaining = session["max_attempts"] - session["attempts"]
                    bot.send_message(chat_id, f"❌ 答案错误！还有 {remaining} 次机会，请在群里发送「{session['answer']}」")
                    logger.warning(f"❌ 验证错误 {session['attempts']}/{session['max_attempts']}: uid={user_id}")
                return True

    return False


def _do_verify_pass(bot, chat_id, user_id, session: dict):
    """验证通过后的解禁操作（从锁内调用，字典操作已在调用方完成）"""
    try:
        from telebot.types import ChatPermissions
        bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        bot.send_message(chat_id, f"✅ {session['user_name']} 验证通过！")
        logger.info(f"✅ 验证通过: uid={user_id}")
    except Exception as e:
        logger.error(f"解禁用户失败 uid={user_id}: {e}")


def _do_verify_fail(bot, chat_id, user_id, session: dict):
    """验证失败次数过多，踢出用户（从锁内调用，字典操作已在调用方完成）"""
    try:
        bot.send_message(chat_id, f"❌ {session['user_name']} 验证错误次数过多，已移出群组")
        try:
            bot.send_message(user_id,
                f"⏰ 你在群组中验证超时，已被移出。\n"
                f"如需重新加入，请通过群链接重新申请，入群后请及时完成验证。"
            )
        except Exception as e:
            logger.debug(f"私聊超时用户失败 uid={user_id}: {e}")
        bot.kick_chat_member(chat_id, user_id)
        bot.unban_chat_member(chat_id, user_id)
    except Exception as e:
        logger.error(f"踢出验证失败用户失败 uid={user_id}: {e}")
    logger.warning(f"❌ 验证失败（次数过多）: uid={user_id}")


def cleanup_expired_sessions():
    """清理过期会话（由定时任务调用）"""
    now = time.time()
    with _verification_lock:
        expired = [k for k, v in _verification_sessions.items() if now > v["timeout_ts"]]
        for key in expired:
            del _verification_sessions[key]
    # 同步删除 SQLite 记录
    for key in expired:
        _delete_session_from_db(_db, key[0], key[1])
    if expired:
        logger.info(f"🧹 清理 {len(expired)} 个过期验证会话")


def restore_sessions_on_startup(bot, db, config):
    """启动时从 SQLite 恢复验证会话到内存。

    解决 Bot 重启时内存会话丢失导致永久禁言无人解禁的问题：
    - 注入模块级 _db 引用，供后续双写使用
    - 未超时会话：恢复到内存，重新启动超时定时器
    - 已超时会话：执行踢出逻辑并删除记录
    """
    global _db
    _db = db
    if db is None:
        logger.warning("⚠️ restore_sessions_on_startup: db 为 None，跳过会话恢复")
        return
    try:
        c = db.conn.cursor()
        c.execute("""
            SELECT chat_id, user_id, answer, attempts, max_attempts, timeout_ts,
                   msg_id, mode, user_name, started_ts
            FROM verification_sessions
        """)
        rows = c.fetchall()
    except Exception as e:
        logger.error(f"启动恢复：加载验证会话失败: {e}")
        return
    if not rows:
        logger.info("ℹ️ 启动恢复：无待恢复的验证会话")
        return

    now = time.time()
    restored = 0
    kicked = 0
    for row in rows:
        (chat_id, user_id, answer, attempts, max_attempts, timeout_ts,
         msg_id, mode, user_name, started_ts) = row
        key = (chat_id, user_id)
        if now > timeout_ts:
            # 已超时：执行踢出逻辑并删除记录（避免永久禁言无人解禁）
            logger.warning(f"⏰ 启动恢复：会话已超时 uid={user_id} chat_id={chat_id}，执行踢出")
            try:
                bot.send_message(chat_id, f"⏰ {user_name} 验证超时，已移出群组")
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            try:
                bot.kick_chat_member(chat_id, user_id)
                bot.unban_chat_member(chat_id, user_id)  # 允许重新被邀请
            except Exception as e:
                logger.error(f"踢出超时用户失败 uid={user_id}: {e}")
            _delete_session_from_db(db, chat_id, user_id)
            kicked += 1
        else:
            # 未超时：恢复到内存，重新启动超时定时器
            remaining = max(1, int(timeout_ts - now))
            with _verification_lock:
                _verification_sessions[key] = {
                    "answer": answer,
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                    "timeout_ts": timeout_ts,
                    "msg_id": msg_id,
                    "mode": mode,
                    "user_name": user_name,
                    "started_ts": started_ts,
                }
            timer = threading.Timer(remaining, _verification_timeout, args=(bot, chat_id, user_id))
            timer.daemon = True
            timer.start()
            restored += 1
    logger.info(f"✅ 验证会话恢复完成：{restored} 个恢复，{kicked} 个超时踢出")
