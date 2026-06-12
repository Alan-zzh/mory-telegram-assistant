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


# 验证码会话存储（内存级，进程内有效）
# { (chat_id, user_id): { "answer": str, "attempts": int, "timeout_ts": float, "msg_id": int, "mode": str } }
_verification_sessions = {}
_verification_lock = threading.Lock()
_VERIFICATION_SESSIONS_MAX = 1000  # 容量上限，防止内存泄漏


def generate_math_question():
    """生成简单数学题，返回 (question, answer)"""
    ops = [
        (lambda: (random.randint(1, 20), random.randint(1, 20)), lambda a, b: a + b, "+"),
        (lambda: (random.randint(5, 20), random.randint(1, 5)), lambda a, b: a - b, "-"),
        (lambda: (random.randint(1, 10), random.randint(1, 10)), lambda a, b: a * b, "×"),
    ]
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
    with _verification_lock:
        if len(_verification_sessions) > _VERIFICATION_SESSIONS_MAX:
            # 清理最旧的条目（按 timeout_ts 排序，删除最早的）
            sorted_keys = sorted(
                _verification_sessions.keys(),
                key=lambda k: _verification_sessions[k].get("timeout_ts", 0)
            )
            remove_count = len(_verification_sessions) - _VERIFICATION_SESSIONS_MAX + 1
            for k in sorted_keys[:remove_count]:
                del _verification_sessions[k]
            logger.info(f"🧹 验证会话容量超限，清理 {remove_count} 个最旧条目")
        _verification_sessions[(chat_id, user_id)] = {
            "answer": answer,
            "attempts": 0,
            "max_attempts": max_attempts,
            "timeout_ts": time.time() + timeout,
            "msg_id": None,
            "mode": mode,
            "user_name": user_name,
        }

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
        logger.warning(f"⏰ 验证码超时: uid={user_id} chat_id={chat_id}")
        try:
            bot.send_message(chat_id, f"⏰ {session['user_name']} 验证超时，已移出群组")
        except Exception:
            pass
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

    with _verification_lock:
        if key not in _verification_sessions:
            bot.answer_callback_query(callback_query.id, text="验证已过期")
            return False

        session = _verification_sessions[key]

        if session["mode"] != "button":
            bot.answer_callback_query(callback_query.id, text="此验证不需要点击按钮")
            return False

        # 验证通过
        del _verification_sessions[key]
    bot.answer_callback_query(callback_query.id, text="✅ 验证通过！")

    # 编辑原消息
    try:
        bot.edit_message_text(
            f"✅ {session['user_name']} 验证通过！",
            chat_id=chat_id,
            message_id=callback_query.message.message_id,
        )
    except Exception:
        pass

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
            return False

        # 检查答案
        user_answer = (m.text or "").strip()
        if session["mode"] == "math":
            if user_answer == session["answer"]:
                # 验证通过
                del _verification_sessions[key]
                _do_verify_pass(bot, chat_id, user_id, session)
                return True
            else:
                # 验证失败
                session["attempts"] += 1
                if session["attempts"] >= session["max_attempts"]:
                    del _verification_sessions[key]
                    _do_verify_fail(bot, chat_id, user_id, session)
                else:
                    remaining = session["max_attempts"] - session["attempts"]
                    bot.send_message(chat_id, f"❌ 答案错误！还有 {remaining} 次机会")
                    logger.warning(f"❌ 验证错误 {session['attempts']}/{session['max_attempts']}: uid={user_id}")
                return True

        elif session["mode"] == "text":
            if user_answer.lower() == session["answer"].lower():
                del _verification_sessions[key]
                _do_verify_pass(bot, chat_id, user_id, session)
                return True
            else:
                session["attempts"] += 1
                if session["attempts"] >= session["max_attempts"]:
                    del _verification_sessions[key]
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
    if expired:
        logger.info(f"🧹 清理 {len(expired)} 个过期验证会话")
