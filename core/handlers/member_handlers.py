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


def _get_member_bio(bot, user_id):
    """读取 Telegram 私聊资料；失败时显式返回不可用，供延迟复审补偿。"""
    try:
        chat_info = bot.get_chat(user_id)
        return (getattr(chat_info, "bio", "") or "")[:500], ""
    except Exception as e:
        return "", str(e)


def _enforce_member_ad(bot, db, config, chat_id, user_id, user_display, reason):
    """所有入群资料/头像命中统一走广告处置链。"""
    from modules.ad_enforcement import enforce_ad_user
    enforce_ad_user(
        bot=bot,
        db=db,
        config=config,
        chat_id=chat_id,
        uid=user_id,
        uname=user_display,
        reason=reason[:500],
        notify_admin=True,
    )


def _is_member_ad_exempt(bot, config, chat_id, user_id):
    """白名单和群管理员在任何资料/头像检测前免检。"""
    whitelist_cfg = config.get("AD_WHITELIST", {})
    whitelist_uids = whitelist_cfg.get("user_ids", []) if isinstance(whitelist_cfg, dict) else []
    if user_id in whitelist_uids or str(user_id) in {str(uid) for uid in whitelist_uids}:
        logger.info(f"[入群广告审核] uid={user_id} outcome=skip reason=whitelist")
        return True
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member and member.status in ("administrator", "creator"):
            logger.info(
                f"[入群广告审核] uid={user_id} outcome=skip reason=role status={member.status}"
            )
            return True
    except Exception as e:
        logger.debug(f"入群管理员身份查询失败 uid={user_id}: {e}")
    return False


def _review_member_profile(bot, user, bio, config, db, chat_id, ctx=None, stage="join"):
    """审核显示名、username、Bio 与 Premium emoji 状态。命中返回 True。"""
    user_id = user.id
    user_display = (user.first_name or "") + (user.last_name or "")
    profile_result = {"is_ad": False, "score": 0, "reason": ""}

    try:
        from modules.ad_profile_signals import detect_profile_ad_signal
        profile_result = detect_profile_ad_signal(bot, user, bio, config)
        if profile_result.get("is_ad"):
            reason = profile_result.get("reason", "")
            logger.warning(
                f"🚫 [入群资料审核] stage={stage} uid={user_id} "
                f"bio_available={bool(bio)} score={profile_result.get('score', 0)} outcome=block "
                f"reason={reason[:120]}"
            )
            _enforce_member_ad(
                bot, db, config, chat_id, user_id, user_display,
                f"入群资料审核({stage}): {reason} BIO:{bio[:120]}",
            )
            return True
    except Exception as e:
        logger.error(f"入群资料信号检测异常 stage={stage} uid={user_id}: {e}")

    ad_detector = getattr(ctx, "ad_detector", None) if ctx else None
    if ad_detector:
        try:
            ad_result = ad_detector.detect(
                username=user_display,
                msg="",
                user_id=user_id,
                bot=bot,
                bio=bio,
                chat_id=chat_id,
            )
            score = int(ad_result.get("score", 0) or 0)
            if ad_result.get("is_ad") and ad_result.get("action") == "ban":
                reason = ad_result.get("reason", "")
                logger.warning(
                    f"🚫 [入群资料审核] stage={stage} uid={user_id} "
                    f"bio_available={bool(bio)} score={score} outcome=block reason={reason[:120]}"
                )
                _enforce_member_ad(
                    bot, db, config, chat_id, user_id, user_display,
                    f"入群资料审核({stage}): {reason} BIO:{bio[:120]}",
                )
                return True
            if score >= 2:
                try:
                    ad_detector.track_suspicious_user(
                        user_id, 0, chat_id, f"[入群资料审核:{stage}] {ad_result.get('reason', '')[:80]}", score
                    )
                except Exception as e:
                    logger.debug(f"追踪可疑入群资料失败 uid={user_id}: {e}")
        except Exception as e:
            logger.error(f"入群广告检测器异常 stage={stage} uid={user_id}: {e}")

    logger.info(
        f"[入群资料审核] stage={stage} uid={user_id} bio_available={bool(bio)} "
        f"score={profile_result.get('score', 0)} outcome=pass"
    )
    return False


def _review_member_avatar(
    bot, user, config, db, chat_id, stage="join", check_similarity=False
):
    """审核头像并记录辅助证据；头像或相似头像不得单信号封禁。"""
    user_id = user.id
    user_display = (user.first_name or "") + (user.last_name or "")
    try:
        from modules.avatar_detector import (
            check_avatar_marketing,
            check_avatar_similarity,
        )

        avatar_hit, avatar_reason, avatar_score, ai_result = check_avatar_marketing(
            bot, user_id, config
        )
        if avatar_hit and avatar_score >= 2:
            logger.warning(
                f"⚠️ [入群头像审核] stage={stage} uid={user_id} score={avatar_score} "
                f"ai_type={ai_result.get('type', 'none')} outcome=evidence_only reason={avatar_reason[:120]}"
            )

        if check_similarity:
            similar, similarity_reason, _ = check_avatar_similarity(bot, user_id, chat_id, db)
            if similar:
                logger.warning(
                    f"⚠️ [入群头像审核] stage={stage} uid={user_id} score=2 "
                    f"outcome=evidence_only reason={similarity_reason[:120]}"
                )

        logger.info(
            f"[入群头像审核] stage={stage} uid={user_id} score={avatar_score} "
            f"ai_type={ai_result.get('type', 'none')} outcome=pass"
        )
    except Exception as e:
        logger.warning(f"入群头像审核异常 stage={stage} uid={user_id}: {e}")
    return False


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
                _handle_chat_member_update(bot, update, ctx.config, ctx.db, ctx=ctx)
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
    # 步骤0：反突袭检测
    try:
        from modules.anti_raid import check_raid
        check_raid(bot, m, config, db)
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    for user in m.new_chat_members:
        user_id = user.id
        user_display = (user.first_name or "") + (user.last_name or "")

        # 已进入任一广告黑名单的账号重进群时必须在验证码/欢迎语之前再次统一处置。
        try:
            if db.is_blacklisted(user_id):
                _enforce_member_ad(
                    bot, db, config, chat_id, user_id, user_display,
                    "广告黑名单账号重新入群",
                )
                logger.warning(f"🚫 [入群广告审核] uid={user_id} outcome=block reason=existing_blacklist")
                continue
        except Exception as e:
            logger.warning(f"入群黑名单前置查询失败 uid={user_id}: {e}")

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

        ad_exempt = _is_member_ad_exempt(bot, config, chat_id, user_id)

        # 步骤2：emoji面具检测（用户名藏广告词）
        from modules.emoji_mask_detector import check_emoji_mask_in_username
        emoji_hit, emoji_reason = check_emoji_mask_in_username(user_display, config)
        if emoji_hit and not ad_exempt:
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

        if not ad_exempt:
            # 步骤2.4：显示名、用户名、BIO、Premium emoji 状态统一资料审核。
            user_bio, bio_error = _get_member_bio(bot, user_id)
            if bio_error:
                logger.warning(
                    f"[入群资料审核] stage=join uid={user_id} bio_available=False fetch_failed=True"
                )
            if _review_member_profile(
                bot, user, user_bio, config, db, chat_id, ctx=ctx, stage="join"
            ):
                continue

            # 步骤2.5：明确头像视觉/OCR证据 + 批量相似头像。
            if _review_member_avatar(
                bot, user, config, db, chat_id, stage="join", check_similarity=True
            ):
                continue

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
def _handle_chat_member_update(bot, update, config, db, ctx=None):
    """追踪成员变动，并在验证码解限后用最新 Bio/头像做第二道审核。"""
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

            # Telegram 刚入群时 get_chat(uid) 可能尚无 Bio；验证码通过后的
            # restricted -> member 是稳定的补偿点，必须重新审核而不是只存库。
            if old_status == "restricted" and new_status == "member":
                logger.info(
                    f"[入群延迟复审] uid={uid} chat={chat_id} bio_available={bool(bio)} stage=verify_release"
                )
                if _is_member_ad_exempt(bot, config, chat_id, uid):
                    return
                if _review_member_profile(
                    bot, user, bio, config, db, chat_id, ctx=ctx, stage="verify_release"
                ):
                    return
                _review_member_avatar(
                    bot, user, config, db, chat_id, stage="verify_release", check_similarity=False
                )
        elif new_status in ('left', 'kicked'):
            db.remove_group_member(uid, chat_id)
            logger.debug(f"[成员追踪] 离群: uid={uid} chat={chat_id}")
    except Exception as e:
        logger.debug(f"chat_member处理异常: {e}")
