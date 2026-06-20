# -*- coding: utf-8 -*-
"""
新成员入群处理器 - P0 优先级处理链路

处理流程：
0. 反突袭检测
0.5. CAS/SpamWatch检查
1. 联邦封禁拦截
1.5. 邀请记录
2. emoji面具检测
3. 验证码触发/欢迎语发送
4. 定制欢迎消息
5. 全局黑名单检查
6. 强制订阅检查
"""

from core.logging_util import get_logger

logger = get_logger("member_handlers")


def register_member_handlers(bot, ctx):
    """注册新成员入群处理器到bot实例"""

    @bot.message_handler(func=lambda m: m.content_type == "new_chat_members",
                         content_types=["new_chat_members"])
    def on_new_chat_members(m):
        """P0 新人入群处理入口"""
        try:
            _handle_new_chat_members(bot, m, ctx.config, ctx.db, ctx=ctx)
        except Exception as e:
            logger.error(f"新人入群处理异常：{e}")

    # [TRAE SOLO CN] v5.8.1 新增：chat_member 更新追踪（渐进式构建完整成员列表）
    try:
        @bot.chat_member_handler()
        def on_chat_member_update(update):
            try:
                _handle_chat_member_update(bot, update, ctx.config, ctx.db)
            except Exception as e:
                logger.debug(f"chat_member更新处理异常: {e}")
    except (AttributeError, TypeError):
        logger.info("chat_member_handler 不可用（pyTelegramBotAPI版本不支持），跳过成员追踪")


def _handle_new_chat_members(bot, m, config, db, ctx=None):
    """
    P0 新人入群处理链路（整合多模块）：
    0. 反突袭检测 → 1. 联邦封禁检查 → 2. emoji面具检查 → 2.5 广告检测（名字+BIO+头像三重信号）→ 3. 验证码/欢迎消息
    """
    chat_id = m.chat.id
    ad_detector = getattr(ctx, 'ad_detector', None) if ctx else None

    # 步骤0：反突袭检测
    try:
        from modules.anti_raid import check_raid
        check_raid(bot, m, config, db)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    for user in m.new_chat_members:
        user_id = user.id
        user_display = (user.first_name or "") + (user.last_name or "")

        # 步骤0.5：CAS/SpamWatch检查
        try:
            from modules.spam_watch import check_user_spam
            if check_user_spam(bot, user.id, config):
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user.id,
                    uname=user_display,
                    reason="CAS/SpamWatch广告黑名单",
                    notify_admin=True,
                )
                logger.info(f"🚫 CAS黑名单永久禁言: uid={user.id}")
                continue
        except Exception as e:
            logger.debug(f"CAS检查异常: {e}")

        # 步骤1：联邦封禁拦截
        from modules.federation import execute_fban_on_join
        if execute_fban_on_join(bot, m, config, db, user, user_display):
            logger.warning(f"🚫 联邦封禁拦截新人: {user_display}")
            continue

        # 步骤1.5：邀请记录（检查是否有邀请人）
        try:
            from modules.invite import record_invite
            # Telegram Bot API: 新成员入群时，如果有邀请链接，from_user就是邀请人
            if hasattr(m, 'from_user') and m.from_user and m.from_user.id != user_id:
                record_invite(db, m.from_user.id, user_id, chat_id, config, bot)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        # 步骤2：emoji面具检测（用户名藏广告词）
        from modules.emoji_mask_detector import check_emoji_mask_in_username
        emoji_hit, emoji_reason = check_emoji_mask_in_username(user_display, config)
        if emoji_hit:
            logger.warning(f"🎭 emoji面具拦截新人: {user_display}")
            from modules.ad_enforcement import enforce_ad_user
            enforce_ad_user(
                bot=bot,
                db=db,
                config=config,
                chat_id=chat_id,
                uid=user_id,
                uname=user_display,
                reason=emoji_reason or "入群用户名emoji面具广告",
                notify_admin=True,
            )
            continue

        # 步骤2.4：资料层广告检测（名字 + BIO + Premium emoji状态）
        user_bio = ""
        try:
            chat_info = bot.get_chat(user_id)
            user_bio = (getattr(chat_info, 'bio', '') or '')[:500]
        except Exception as e:
            logger.debug(f"入群拉取用户bio失败 uid={user_id}: {e}")

        try:
            from modules.ad_profile_signals import detect_profile_ad_signal
            profile_result = detect_profile_ad_signal(bot, user, user_bio, config)
            if profile_result.get("is_ad"):
                logger.warning(
                    f"🚫 [入群资料检测] 拦截广告新人: {user_display}({user_id}) "
                    f"原因={profile_result.get('reason', '')[:120]}"
                )
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user_id,
                    uname=user_display,
                    reason=f"入群资料检测: {profile_result.get('reason', '')[:200]} BIO:{user_bio[:120]}",
                    notify_admin=True,
                )
                continue
        except Exception as e:
            logger.error(f"入群资料广告检测异常 uid={user_id}: {e}")

        # [TRAE SOLO CN] v5.14.2 新增：步骤 2.5 - 入群即跑名字+BIO+头像三重广告检测
        # 背景：v5.14.1 修复了变体字规避后，发现入群处理链路没有调用 ad_detector.detect()
        # 导致名字变体字 + BIO 全文广告 的用户在第一条消息时才被检测（已晚一步）
        # 现在入群即检测，符合"绝对不能死"+ 商业项目早期封禁原则
        if ad_detector:
            try:
                # 2) 跑 ad_detector 三重检测（msg="" + username + bio）
                ad_result = ad_detector.detect(
                    username=user_display,
                    msg="",
                    user_id=user_id,
                    bot=bot,
                    bio=user_bio,
                    chat_id=chat_id,
                )
                score = ad_result.get("score", 0)
                is_ad = ad_result.get("is_ad", False)
                action = ad_result.get("action", "none")
                reason = ad_result.get("reason", "")

                if is_ad and action == "ban":
                    logger.warning(
                        f"🚫 [入群即检测] 拦截广告新人: {user_display}({user_id}) "
                        f"评分={score} 动作={action} 原因={reason[:100]}"
                    )
                    from modules.ad_enforcement import enforce_ad_user
                    enforce_ad_user(
                        bot=bot,
                        db=db,
                        config=config,
                        chat_id=chat_id,
                        uid=user_id,
                        uname=user_display,
                        reason=f"入群即检测: {reason[:200]} BIO:{user_bio[:120]}",
                        notify_admin=True,
                    )
                    continue
                elif score >= 2:
                    # 评分 2+ 但未到 ban 阈值：标记为可疑 + 开启追踪窗口
                    # 下次该用户发消息会走 P3.5 完整检测（带 msg 内容）
                    logger.info(
                        f"⚠️ [入群即检测] 可疑新人: {user_display}({user_id}) "
                        f"评分={score} 原因={reason[:100]}"
                    )
                    try:
                        # 入可疑追踪表（ad_suspicious_users），30 分钟内累计评分
                        # 签名: track_suspicious_user(user_id, msg_id, chat_id, text, score)
                        ad_detector.track_suspicious_user(user_id, 0, chat_id, f"[入群即检测] {reason[:80]}", score)
                    except Exception as e:
                        logger.debug(f"追踪可疑用户失败: {e}")
            except Exception as e:
                logger.error(f"入群广告三重检测异常 uid={user_id}: {e}")
                # 失败不影响主流程，继续后续步骤

        # [Trae] v5.3.1 新增：新成员入群时自动检测头像（一次性检测）
        try:
            from modules.avatar_detector import check_user_avatar, check_avatar_similarity
            is_suspicious_avatar, avatar_reason = check_user_avatar(bot, user_id)
            if is_suspicious_avatar:
                logger.warning(f"🚫 新成员头像检测拦截: {user_display}({user_id}) 原因: {avatar_reason}")
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user_id,
                    uname=user_display,
                    reason=f"新成员头像检测: {avatar_reason}",
                    notify_admin=True,
                )
                continue
            
            # 头像相似度检测（批量广告号识别）
            is_similar, similarity_reason, similar_user_ids = check_avatar_similarity(bot, user_id, chat_id, db)
            if is_similar:
                logger.warning(f"🚫 新成员头像相似度拦截: {user_display}({user_id}) 原因: {similarity_reason}")
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=bot,
                    db=db,
                    config=config,
                    chat_id=chat_id,
                    uid=user_id,
                    uname=user_display,
                    reason=f"新成员头像相似: {similarity_reason}",
                    notify_admin=True,
                )
                continue
        except Exception as e:
            logger.debug(f"新成员头像检测异常: {e}")

        # 步骤3：启动验证码（如果启用了验证）
        ver_config = config.get("VERIFICATION_CONFIG", {})
        if ver_config.get("enable", False):
            # 先禁言
            try:
                from telebot.types import ChatPermissions
                bot.restrict_chat_member(
                    chat_id, user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            # 发送验证码
            from modules.verification import start_verification
            question, keyboard = start_verification(bot, chat_id, user_id, user_display, config)
            try:
                if keyboard:
                    bot.send_message(chat_id, question, reply_markup=keyboard)
                else:
                    bot.send_message(chat_id, question)
            except Exception as e:
                logger.error(f"发送验证码失败: {e}")
                # 失败时直接解禁，避免卡住
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
                    logger.debug(f"操作异常: {e}")
        else:
            # 没启用验证，走原始欢迎流程
            from modules.group_mgr import handle_new_members
            keyword_manager = getattr(ctx, 'keyword_manager', None) if ctx else None
            handle_new_members(bot, m, config, db, keyword_manager)

        # 步骤4：发送定制欢迎消息（无论是否启用验证都发）
        try:
            from modules.welcome_customization import send_welcome_message
            send_welcome_message(bot, m, config, db)
        except Exception as e:
            logger.debug(f"发送定制欢迎消息失败: {e}")

        # 全局黑名单检查
        try:
            from modules.global_blacklist import check_global_blacklist
            check_global_blacklist(bot, m, config, db)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        # 强制订阅检查
        try:
            from modules.force_subscribe import check_force_subscribe
            check_force_subscribe(bot, m, config, db)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
def _handle_chat_member_update(bot, update, config, db):
    """[TRAE SOLO CN] v5.8.1 处理 chat_member 更新事件，追踪成员变动"""
    try:
        new_status = update.new_chat_member.status if update.new_chat_member else None
        old_status = update.old_chat_member.status if update.old_chat_member else None
        chat_id = update.chat.id if update.chat else None
        user = update.new_chat_member.user if update.new_chat_member else None

        if not chat_id or not user:
            return

        uid = user.id
        username = getattr(user, 'username', '') or ''
        display_name = (user.first_name or '') + (user.last_name or '')

        if new_status in ('member', 'administrator', 'creator', 'restricted'):
            bio = ''
            try:
                chat_info = bot.get_chat(uid)
                bio = getattr(chat_info, 'bio', '') or ''
            except Exception as e:
                logger.debug(f"操作异常: {e}")
            db.upsert_group_member(uid, chat_id, username, display_name, bio, new_status)
            logger.debug(f"[成员追踪] 入群/更新: uid={uid} chat={chat_id} status={new_status}")
        elif new_status in ('left', 'kicked'):
            db.remove_group_member(uid, chat_id)
            logger.debug(f"[成员追踪] 离群: uid={uid} chat={chat_id}")
    except Exception as e:
        logger.debug(f"chat_member处理异常: {e}")
