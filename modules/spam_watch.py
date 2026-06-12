# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/spam_watch.py  ·  CAS/SpamWatch黑名单检测模块                  ║
║                                                                        ║
║  功能：                                                                ║
║    check_cas          - 检查用户是否在CAS黑名单                        ║
║    check_spamwatch    - 检查用户是否在SpamWatch黑名单                  ║
║    check_user_spam    - 综合检查（新成员入群时调用）                    ║
║    handle_cascheck    - 手动检查命令 /cascheck                          ║
║                                                                        ║
║  数据源：                                                               ║
║    CAS (Combot Anti-Spam) - 免费API，无需Key                           ║
║    SpamWatch - 需要Token，从config读取                                  ║
║  被调用：main.py 新成员处理 + 指令分发                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
from core.logging_util import get_logger

logger = get_logger("spam_watch")

# 默认配置
DEFAULT_SPAM_WATCH_CONFIG = {
    "cas_enabled": True,           # 是否启用CAS检测
    "spamwatch_enabled": False,    # 是否启用SpamWatch（需Token）
    "spamwatch_token": "",         # SpamWatch API Token
    "auto_ban": False,             # 检测到黑名单用户是否自动封禁
}


def _get_config(config: dict) -> dict:
    """获取SpamWatch配置，合并默认值"""
    user_config = config.get("SPAM_WATCH_CONFIG", {})
    merged = dict(DEFAULT_SPAM_WATCH_CONFIG)
    merged.update(user_config)
    return merged


def check_cas(bot, user_id: int, config: dict) -> bool:
    """检查用户是否在CAS黑名单

    Args:
        bot: TeleBot实例
        user_id: 用户ID
        config: 配置字典

    Returns:
        bool: True表示在黑名单中
    """
    cfg = _get_config(config)
    if not cfg.get("cas_enabled", False):
        return False

    try:
        import requests
        url = f"https://api.cas.chat/check?user_id={user_id}"
        resp = requests.get(url, timeout=5)
        data = resp.json()

        if data.get("ok") and data.get("result", {}).get("spam", False):
            logger.warning(f"🚨 CAS黑名单命中: uid={user_id}")
            return True

    except Exception as e:
        logger.error(f"CAS查询异常: uid={user_id} err={e}")

    return False


def check_spamwatch(bot, user_id: int, config: dict) -> bool:
    """检查用户是否在SpamWatch黑名单

    Args:
        bot: TeleBot实例
        user_id: 用户ID
        config: 配置字典

    Returns:
        bool: True表示在黑名单中
    """
    cfg = _get_config(config)
    token = cfg.get("spamwatch_token", "")
    if not token or not cfg.get("spamwatch_enabled", False):
        return False

    try:
        import requests
        url = f"https://api.spamwat.ch/banlist/{user_id}"
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, timeout=5)

        # 200 = 在黑名单中，404 = 不在黑名单
        if resp.status_code == 200:
            logger.warning(f"🚨 SpamWatch黑名单命中: uid={user_id}")
            return True

    except Exception as e:
        logger.error(f"SpamWatch查询异常: uid={user_id} err={e}")

    return False


def check_user_spam(bot, user_id: int, config: dict) -> bool:
    """综合检查用户是否在任一黑名单（新成员入群时调用）

    Args:
        bot: TeleBot实例
        user_id: 用户ID
        config: 配置字典

    Returns:
        bool: True表示在黑名单中（建议封禁）
    """
    in_cas = check_cas(bot, user_id, config)
    in_sw = check_spamwatch(bot, user_id, config)
    return in_cas or in_sw


def handle_cascheck(bot, m, config, db):
    """手动检查用户是否在CAS/SpamWatch黑名单

    用法：
        /cascheck @username
        /cascheck（回复用户消息）

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    text = m.text or ""
    target_uid = None

    # 尝试从命令参数解析用户ID或@username
    parts = text.split(None, 1)
    if len(parts) >= 2:
        arg = parts[1].strip()
        if arg.startswith("@"):
            # 通过用户名获取ID
            try:
                chat_member = bot.get_chat_member(m.chat.id, arg[1:])
                target_uid = chat_member.user.id
            except Exception:
                bot.reply_to(m, f"❌ 未找到用户 {arg}")
                return
        elif arg.isdigit():
            target_uid = int(arg)
        else:
            # 尝试作为用户名（不带@）
            try:
                chat_member = bot.get_chat_member(m.chat.id, arg)
                target_uid = chat_member.user.id
            except Exception:
                bot.reply_to(m, f"❌ 未找到用户 {arg}，请使用 @username 或用户ID")
                return

    # 尝试从回复消息获取
    if target_uid is None and m.reply_to_message:
        target_uid = m.reply_to_message.from_user.id

    if target_uid is None:
        bot.reply_to(m, "❌ 请指定用户：/cascheck @username 或回复用户消息")
        return

    # 执行检查
    checking_msg = bot.reply_to(m, "🔍 正在检查黑名单...")

    cas_result = check_cas(bot, target_uid, config)
    sw_result = check_spamwatch(bot, target_uid, config)

    # 获取用户名
    try:
        chat_member = bot.get_chat_member(m.chat.id, target_uid)
        username = chat_member.user.first_name
    except Exception:
        username = str(target_uid)

    # 构建结果
    text = f"🛡 黑名单检查结果\n"
    text += f"━━━━━━━━━━━━━\n"
    text += f"👤 用户：{username}（{target_uid}）\n"

    # CAS结果
    cfg = _get_config(config)
    if cfg.get("cas_enabled", False):
        if cas_result:
            text += f"🔴 CAS：已列入黑名单 ⚠️\n"
        else:
            text += f"🟢 CAS：未列入黑名单\n"
    else:
        text += f"⚪ CAS：未启用\n"

    # SpamWatch结果
    if cfg.get("spamwatch_enabled", False) and cfg.get("spamwatch_token", ""):
        if sw_result:
            text += f"🔴 SpamWatch：已列入黑名单 ⚠️\n"
        else:
            text += f"🟢 SpamWatch：未列入黑名单\n"
    else:
        text += f"⚪ SpamWatch：未配置\n"

    # 总结
    if cas_result or sw_result:
        text += f"\n⚠️ 该用户存在于黑名单中，建议注意！"
    else:
        text += f"\n✅ 该用户未在已启用的黑名单中"

    try:
        bot.edit_message_text(text, m.chat.id, checking_msg.message_id)
    except Exception:
        bot.reply_to(m, text)
