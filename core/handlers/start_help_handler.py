# -*- coding: utf-8 -*-
"""用户入口命令 /start 与 /help 处理器。

普通用户私聊 ``/start`` 使用独立的 Mory 小助理业务欢迎卡，不进入普通 AI
对话，避免把明确的办事入口生成成陪聊式开场。管理员和群聊继续保留各自入口。
"""

from core.logging_util import get_logger

logger = get_logger("start_help_handler")


def _is_private(message) -> bool:
    """判断是否私聊（chat.type == "private"）。"""
    try:
        return getattr(getattr(message, "chat", None), "type", "") == "private"
    except Exception:
        return False


def _get_admin_ids(config: dict) -> set:
    """获取管理员 ID 集合（ADMIN_IDS + ADMIN_ID），与项目其他 handler 保持一致。"""
    admin_ids = set(config.get("ADMIN_IDS", []) or [])
    admin_id = config.get("ADMIN_ID", 0)
    if admin_id:
        admin_ids.add(admin_id)
    return admin_ids


# ── /start 管理员 / 群聊文案 ──────────────────────────────────────────

_START_ADMIN_PRIVATE_TEXT = (
    "👋 你好，我是 Mory 小助理， Telegram 群组助手。\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🎯 我能在群里帮你做这些事：\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "✅ 入群验证：新成员进群自动触发验证码，防广告号突袭\n"
    "🚫 广告检测：文字 / 图片 OCR / 头像 / Bio 多信号识别，自动封禁并清理历史\n"
    "🛡️ 联邦封禁：跨群共享黑名单，一处封禁处处生效\n"
    "🎁 积分商城：签到 / 红包 / 抽奖 / 优惠券，成员互动留得住\n"
    "📚 传统文化栏目：定时栏目播报，群文化氛围拉满\n"
    "🤖 AI 对话：私聊我或 @我 即可触发人设对话\n"
    "🎟️ 优惠券：管理员可生成 / 用户可领取核销\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "🚀 群主快速上手：\n"
    "1️⃣ 把我拉进群组\n"
    "2️⃣ 给我管理员权限（至少要有“删除消息”和“禁言用户”）\n"
    "3️⃣ 在群里发 /start 即可激活\n"
    "4️⃣ 私聊我发 /help 查看完整配置指引\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👉 输入 /help 查看完整命令清单\n"
    "👉 在群里？直接 @我 或回复我的消息就能聊天\n"
)

_START_GROUP_TEXT = (
    "👋 我是 Mory 小助理，群组助手。\n"
    "👉 输入 /help 查看命令；私聊我可以看完整功能清单。\n"
    "👉 @我 或回复我的消息可以跟我聊天。"
)


# ── /help 用户级文案 ───────────────────────────────────────────────────

_HELP_USER_TEXT = (
    "📖 Mory 小助理 · 用户命令清单\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "/help - 查看本帮助\n"
    "/myid - 查看自己的 Telegram UID\n"
    "/sign - 每日签到（积分）\n"
    "/shop - 打开积分商城\n"
    "/redpacket - 红包玩法（详见群内说明）\n"
    "/lottery - 抽奖玩法（详见群内说明）\n"
    "/mystic - 传统文化栏目入口\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "💬 私聊我或 @我可以触发 AI 对话\n"
    "🎁 群内还可以：领券 / 核券 / 转账 / 打赏 / AFK 等自然语言指令\n"
    "❓ 遇到问题请联系群管理员"
)


# ── /help 管理员级文案 ─────────────────────────────────────────────────

_HELP_ADMIN_TEXT = (
    "━━━━━━━━━━━━━━━━━━━━\n"
    "👑 管理员命令清单（仅 ADMIN_ID / ADMIN_IDS 可用）\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "【广告 / 封禁】\n"
    "/scan_ads [start_id] [end_id] - 追溯扫描广告（可选范围）\n"
    "/unban @user | /unban <uid> | 解封 @user - 解除广告封禁\n"
    "/fban @user [reason] - 联邦封禁\n"
    "/unfban @user - 解除联邦封禁\n"
    "/feds - 查询联邦封禁列表\n"
    "【认证 / 标签】\n"
    "/certify @user | /certify <uid> - 认证用户\n"
    "/uncertify @user | /uncertify <uid> - 取消认证\n"
    "标签 @user <tag> - 给用户打标签（例：标签 @user vip）\n"
    "备注 @user <note> - 给用户加备注（例：备注 @user 老客户，可赊账）\n"
    "查看标签 @user - 查看用户标签\n"
    "【群欢迎 / 规则】\n"
    "/setwelcome <text> - 设置欢迎语\n"
    "💡 欢迎语可用变量：{user} {mention} {first_name} {id}\n"
    "/setgoodbye <text> - 设置离别语\n"
    "/setrules <text> - 设置群规\n"
    "/cleanwelcome - 清除欢迎语\n"
    "/getwelcome - 查看当前欢迎语\n"
    "【设置面板 / 业务模块】\n"
    "/settings - 打开设置面板\n"
    "/sales - 销售中心\n"
    "/security - 安全中心\n"
    "/managed - 多群托管\n"
    "/content_audit - 内容审核\n"
    "/analytics - 新成员分析\n"
    "/membership - 会员管理\n"
    "【优惠券】\n"
    "生成优惠券 <args> - 生成优惠券\n"
    "领券 <code> - 领取优惠券\n"
    "核券 <code> - 核销优惠券\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "完整说明见仓库 README.md「管理员命令清单」一节。"
)


def handle_start_command(bot, message, ctx):
    """/start 命令处理器。

    - 普通用户私聊：随机横版欢迎卡 + 业务助理文案 + 两个自助入口。
    - 管理员私聊：返回群管理功能清单。
    - 群聊：只回简短引导，避免刷屏。
    """
    try:
        if _is_private(message):
            config = getattr(ctx, "config", {}) or {}
            uid = getattr(getattr(message, "from_user", None), "id", 0) or 0
            if uid in _get_admin_ids(config):
                bot.send_message(message.chat.id, _START_ADMIN_PRIVATE_TEXT)
                return

            from core.start_welcome_card import (
                build_start_welcome_caption,
                build_start_welcome_card,
                build_start_welcome_markup,
                normalize_display_name,
            )
            from core.telebot_compat import send_photo_compat

            user = getattr(message, "from_user", None)
            first_name = getattr(user, "first_name", "") or ""
            last_name = getattr(user, "last_name", "") or ""
            display_name = normalize_display_name(f"{first_name} {last_name}")
            caption = build_start_welcome_caption(display_name)
            markup = build_start_welcome_markup(config)

            try:
                card = build_start_welcome_card(display_name)
                try:
                    send_photo_compat(
                        bot,
                        message.chat.id,
                        card.stream,
                        caption=caption,
                        reply_markup=markup,
                    )
                finally:
                    card.stream.close()
                logger.info(
                    "/start 普通用户欢迎卡已发送 uid=%s asset=%s",
                    uid,
                    card.asset_name,
                )
            except Exception as image_error:
                # 图片渲染/上传失败时仍保证办事入口可用，并明确记录 degraded 原因。
                logger.warning(
                    "/start 欢迎卡降级为文本 uid=%s reason=%s",
                    uid,
                    image_error,
                )
                bot.send_message(message.chat.id, caption, reply_markup=markup)
        else:
            # 群里只回简短引导，避免刷屏
            bot.reply_to(message, _START_GROUP_TEXT)
    except Exception as e:
        logger.error(f"/start 命令处理异常: {e}")


def handle_help_command(bot, message, ctx):
    """/help 命令处理器。

    - 私聊：返回用户级帮助。
    - 群聊：只回“私聊我查看完整帮助”，避免刷屏。
    - 管理员发起 /help 时额外附带管理员命令清单。
    """
    try:
        config = getattr(ctx, "config", {}) or {}
        uid = getattr(getattr(message, "from_user", None), "id", 0) or 0
        is_admin = uid in _get_admin_ids(config)

        if _is_private(message):
            text = _HELP_USER_TEXT
            if is_admin:
                text = text + "\n" + _HELP_ADMIN_TEXT
            bot.send_message(message.chat.id, text)
        else:
            # 群聊：先主动私聊完整帮助；私聊成功才在群里回复"已私聊"，失败则提示重新 /start
            try:
                if is_admin:
                    bot.send_message(uid, _HELP_USER_TEXT + "\n" + _HELP_ADMIN_TEXT)
                else:
                    bot.send_message(uid, _HELP_USER_TEXT)
            except Exception as e:
                logger.warning(f"主动私聊用户帮助失败 uid={uid}: {e}")
                try:
                    bot.reply_to(message, "📖 完整帮助已私聊你；如未收到，请先私聊我发送 /start 后再试。")
                except Exception:
                    pass
            else:
                # 私聊成功才回复"已私聊"
                bot.reply_to(message, "📖 完整帮助已私聊你，请查看私聊窗口。")
    except Exception as e:
        logger.error(f"/help 命令处理异常: {e}")
