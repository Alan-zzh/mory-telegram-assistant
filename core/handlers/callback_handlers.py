# -*- coding: utf-8 -*-
"""
回调查询处理器 - 处理所有 @bot.callback_query_handler 装饰的函数

包含：
- fb_ 开头的回调查询（反馈按钮）
- verify_ 开头的回调查询（验证码）
- settings_ 开头的回调查询（设置面板）
- rp_ 开头的回调查询（红包）
- lot_ 开头的回调查询（抽奖）
- vk_ 开头的回调查询（投票踢人）
- zc_ 开头的回调查询（僵尸清理确认）
- ghost_ 开头的回调查询（不活跃清理）
- /settings 命令处理器
- 编辑消息检测处理器
"""

from core.logging_util import get_logger

logger = get_logger("callback_handlers")


def register_callback_handlers(bot, ctx):
    """注册所有回调查询处理器到bot实例"""

    def _is_admin(user_id: int) -> bool:
        try:
            raw_admin_ids = (ctx.config or {}).get("ADMIN_IDS", []) or []
            if isinstance(raw_admin_ids, int):
                raw_admin_ids = [raw_admin_ids]
            if not isinstance(raw_admin_ids, (list, tuple, set)):
                raw_admin_ids = []
            admin_ids = set(raw_admin_ids)
            admin_id = (ctx.config or {}).get("ADMIN_ID", 0)
            if admin_id:
                admin_ids.add(admin_id)
            return user_id in admin_ids
        except Exception:
            return False

    def _is_blacklisted_callback(call) -> bool:
        uid = getattr(getattr(call, "from_user", None), "id", 0) or 0
        if not uid:
            return False
        try:
            return not _is_admin(uid) and bool(ctx.db.is_blacklisted(uid))
        except Exception as e:
            logger.debug(f"回调黑名单检查失败 uid={uid}: {e}")
            return False

    @bot.callback_query_handler(func=_is_blacklisted_callback)
    def on_blacklisted_callback(call):
        try:
            bot.answer_callback_query(call.id, text="当前账号无法使用机器人功能", show_alert=False)
            logger.info(f"🚫 黑名单按钮回调拦截: uid={call.from_user.id} data={getattr(call, 'data', '')}")
        except Exception as e:
            logger.debug(f"黑名单按钮回调应答失败: {e}")

    # ── 广告误封解封按钮 ───────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("ad_unban:"))
    def on_ad_unban_callback(call):
        try:
            operator_id = getattr(getattr(call, "from_user", None), "id", 0) or 0
            if not _is_admin(operator_id):
                bot.answer_callback_query(call.id, text="无权限", show_alert=True)
                return
            parts = str(call.data or "").split(":")
            if len(parts) != 3:
                bot.answer_callback_query(call.id, text="解封参数无效", show_alert=True)
                return
            uid = int(parts[1])
            chat_id = int(parts[2])
            from modules.ad_enforcement import restore_ad_user
            result = restore_ad_user(
                bot=bot,
                db=ctx.db,
                config=ctx.config,
                chat_id=chat_id,
                uid=uid,
                actor_id=operator_id,
                ad_detector=getattr(ctx, "ad_detector", None),
            )
            ok = result.get("code") == 200
            text = "已解封，四项状态和发言权限已读回确认" if ok else "解封未完全确认，请看日志"
            bot.answer_callback_query(call.id, text=text, show_alert=True)
            try:
                bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=None,
                )
            except Exception as e:
                logger.debug(f"移除解封按钮失败: {e}")
        except Exception as e:
            logger.error(f"广告解封回调异常：{e}")
            try:
                bot.answer_callback_query(call.id, text="解封异常，请看日志", show_alert=True)
            except Exception:
                pass

    # ── 反馈按钮回调（fb_like / fb_dislike）──────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("fb_"))
    def on_feedback_callback(call):
        try:
            parts = call.data.split("_")
            if len(parts) < 3:
                return
            feedback = parts[1]
            if feedback not in ("like", "dislike"):
                return
            try:
                bot_msg_id = int(parts[2])
            except ValueError:
                return
            chat_id = call.message.chat.id
            user_id = call.from_user.id
            ctx.db.record_feedback(bot_msg_id, chat_id, user_id, feedback)
            emoji = "👍" if feedback == "like" else "👎"
            bot.answer_callback_query(call.id, text=f"已收到{emoji}反馈，谢谢！", show_alert=False)
            try:
                markup = call.message.reply_markup
                if markup and hasattr(markup, 'keyboard'):
                    new_keyboard = []
                    for row in markup.keyboard:
                        new_row = []
                        for btn in row:
                            if hasattr(btn, 'callback_data') and btn.callback_data == call.data:
                                from telebot.types import InlineKeyboardButton as IKB
                                new_row.append(IKB(text=f"{emoji} ✓", callback_data="fb_done"))
                            else:
                                new_row.append(btn)
                        new_keyboard.append(new_row)
                    from telebot.types import InlineKeyboardMarkup
                    bot.edit_message_reply_markup(chat_id=chat_id, message_id=call.message.message_id,
                                                  reply_markup=InlineKeyboardMarkup(new_keyboard))
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.error(f"反馈回调异常：{e}")

    # ── 验证码按钮回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("verify_"))
    def on_verify_callback(call):
        try:
            from modules.verification import check_callback_query
            check_callback_query(bot, call, ctx.config)
        except Exception as e:
            logger.error(f"验证码回调异常：{e}")

    # ── 设置面板回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("settings_"))
    def on_settings_callback(call):
        try:
            from modules.settings_panel import handle_settings_callback
            handle_settings_callback(bot, call, ctx.config, ctx.db)
        except Exception as e:
            logger.error(f"设置面板回调异常：{e}")

    # ── 红包回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("rp_"))
    def on_redpacket_callback(call):
        try:
            from modules.redpacket import handle_claim_redpacket
            handle_claim_redpacket(bot, call, ctx.config, ctx.db)
        except Exception as e:
            logger.error(f"红包回调异常：{e}")

    # ── 抽奖回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("lot_"))
    def on_lottery_callback(call):
        try:
            from modules.lottery import handle_join_lottery
            handle_join_lottery(bot, call, ctx.config, ctx.db)
        except Exception as e:
            logger.error(f"抽奖回调异常：{e}")

    # ── 投票踢人回调（vk_） ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("vk_"))
    def on_vote_kick_callback(call):
        try:
            from modules.vote_kick import handle_vote_kick_callback
            handle_vote_kick_callback(bot, call, ctx.config, ctx.db)
        except Exception as e:
            logger.error(f"投票踢人回调异常：{e}")

    # ── 僵尸清理回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("zc_"))
    def _cb_zombie_clean(call):
        from modules.zombie_clean import handle_zombies_confirm
        handle_zombies_confirm(bot, call, ctx.config, ctx.db)

    # ── 不活跃清理回调 ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("ghost_"))
    def _cb_ghost_clean(call):
        from modules.inactive_clean import handle_ghost_confirm
        handle_ghost_confirm(bot, call, ctx.config, ctx.db)

    # ── 通用按钮点击追踪（v5.18.0 - 按钮点击统计） ─────────────────────────
    # 必须在所有专用 callback handler 之后注册；telebot 首个匹配后会停止分发。
    @bot.callback_query_handler(func=lambda call: True)
    def on_any_callback(call):
        """通用按钮点击追踪 - 记录所有按钮点击到 button_click_stats 表。"""
        try:
            if not call.data:
                return
            data = str(call.data)
            if data.startswith("btn_"):
                parts = data.split("_", 2)
                if len(parts) >= 3:
                    style = parts[1]
                    button_id = parts[2]
                else:
                    style = "default"
                    button_id = data
            else:
                button_id = data.split("_")[0] if "_" in data else data
                style = "default"
            try:
                if hasattr(ctx, 'db') and ctx.db and hasattr(ctx.db, 'record_button_click'):
                    ctx.db.record_button_click(button_id, style)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.debug(f"按钮点击追踪异常（已忽略）: {e}")

    # ── /settings 命令处理器 ──────────────────────────────────────────
    @bot.message_handler(commands=["settings"])
    def on_settings_command(m):
        try:
            uid = m.from_user.id
            from modules.settings_panel import _is_admin
            if not _is_admin(uid, ctx.config):
                bot.reply_to(m, "❌ 仅管理员可操作")
                return
            from modules.settings_panel import render_main_menu
            text, keyboard = render_main_menu(ctx.config)
            bot.send_message(m.chat.id, text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as e:
            logger.error(f"/settings 命令异常：{e}")

    # ── 编辑消息检测处理器 ──────────────────────────────────────────
    @bot.edited_message_handler(func=lambda m: m.text and len(m.text) >= 5)
    def on_edited_message(m):
        try:
            chat_id = m.chat.id
            uid = m.from_user.id
            # 黑名单用户跳过
            if ctx.db.is_blacklisted(uid):
                return
            # 检查编辑后的消息是否含广告
            from modules.edit_detector import check_edited_message
            check_edited_message(bot, m, ctx.config, ctx.db, ctx.ai, ctx.ad_detector)
        except Exception as e:
            logger.error(f"编辑消息检测异常：{e}")
