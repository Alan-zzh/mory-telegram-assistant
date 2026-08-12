# -*- coding: utf-8 -*-
"""
安全处理器 - P1/P3/P3.2/P3.5 优先级安全检查

包含：
- P1 黑名单用户过滤
- P3 敏感词检测+删除
- P3.2 夜间模式检查
- P3.5 广告检测（AdDetector调用 + emoji面具检测）
- P3.5 延迟封禁追踪
- P3.5 旧版关键词检测兜底
"""

import concurrent.futures

from core.helpers import can_delete_message, format_user_mention
from core.logging_util import get_logger, clear_logging_context

logger = get_logger("security_handlers")


_BENIGN_AD_BYPASS_TEXTS = {
    "签到",
    "打卡",
    "每日签到",
    "今日签到",
    "/checkin",
    "/checkin@",
    "/sign",
    "/signin",
    "/daily",
    # 积分相关正常业务问题
    "积分可以干嘛",
    "积分能干嘛",
    "积分有什么用",
    "积分怎么用",
    "积分怎么获得",
    "怎么获得积分",
    "积分多少",
    "我的积分",
    "查看积分",
    "积分排行",
    "排行榜",
    "积分抽奖",
    "抽奖",
    "签到有什么用",
    "签到干嘛",
    "签到干嘛用",
    "签到有什么好处",
    "签到干嘛的",
    "签到有什么奖励",
    # 积分商城相关（避免误触发自动回复）
    "积分商城",
    "商城",
}


def _is_benign_ad_bypass_text(text: str) -> bool:
    """明确的正常业务动作不进入广告检测，防止资料层小分累计误封。"""
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if normalized in _BENIGN_AD_BYPASS_TEXTS:
        return True
    for prefix in ("/checkin@", "/sign@", "/signin@", "/daily@"):
        if normalized.startswith(prefix):
            return True
    return False


def _direct_message_ad_result(ad_detector, text: str) -> dict:
    """只用消息正文复判逐条广告真值，不混入昵称、Bio、头像或历史评分。"""
    if not ad_detector or not (text or "").strip():
        return {"is_ad": False, "action": "none", "score": 0}
    try:
        return ad_detector.detect(username="", msg=text, bio="")
    except Exception as e:
        logger.debug(f"[AD] 正文独立复判失败: {e}")
        return {"is_ad": False, "action": "none", "score": 0}


def _has_direct_message_ad_evidence(ad_detector, text: str) -> bool:
    result = _direct_message_ad_result(ad_detector, text)
    return bool(result.get("is_ad") and result.get("action") == "ban")


def check_blacklist(dctx) -> bool:
    """P1 黑名单用户过滤（在活跃度更新之前，避免污染数据）

    返回 True 表示用户已被拦截，应终止分发
    """
    db = dctx.ctx.db
    uid = dctx.uid

    if db.is_blacklisted(uid):
        if getattr(dctx, "is_group", False):
            try:
                from modules.ad_enforcement import enforce_ad_user
                enforce_ad_user(
                    bot=dctx.ctx.bot,
                    db=db,
                    config=dctx.ctx.config,
                    chat_id=dctx.chat_id,
                    uid=uid,
                    uname=dctx.uname,
                    reason=f"黑名单拦截:{dctx.uname}",
                    message=dctx.msg,
                    current_msg_id=getattr(dctx.msg, "message_id", 0),
                    notify_admin=False,
                )
            except Exception as e:
                logger.warning(f"P1黑名单统一处置失败: uid={uid} err={e}")
        clear_logging_context()
        return True
    return False


def check_banned_words(dctx) -> bool:
    """P3 黑名单词过滤 + 执行封禁动作

    返回 True 表示消息已被处理（含敏感词已删除），应终止分发
    """
    if not dctx.is_group:
        return False

    from modules.group_mgr import check_banned_words
    from modules.blocklist_modes import apply_blocklist_action

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    db = dctx.ctx.db
    chat_id = dctx.chat_id
    uid = dctx.uid

    if check_banned_words(bot, m, CONFIG, db):
        try:
            apply_blocklist_action(bot, m, CONFIG, db, chat_id, uid)
        except Exception as e:
            logger.debug(f"操作异常: {e}")
        clear_logging_context()
        return True
    return False


def check_night_mode(dctx) -> bool:
    """P3.2 夜间模式拦截（非管理员夜间发言）

    返回 True 表示消息已被夜间模式拦截
    """
    if not dctx.is_group:
        return False

    from modules.night_mode import should_mute_for_night_mode

    bot = dctx.ctx.bot
    m = dctx.msg
    CONFIG = dctx.ctx.config
    chat_id = dctx.chat_id
    uid = dctx.uid
    msg = dctx.text

    if should_mute_for_night_mode(bot, m, CONFIG):
        if can_delete_message(CONFIG):
            try:
                bot.delete_message(chat_id, m.message_id)
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        logger.info(f"🌙 夜间模式拦截: uid={uid} msg={msg[:30]}")
        clear_logging_context()
        return True
    return False


def check_ad_detection(dctx) -> bool:
    """P3.5 智能广告检测（零TOKEN消耗）

    流程：
    1. 先用 detect() 判断是否为广告（即时封禁场景）
    2. 如果不是即时广告，用 track_suspicious_user() 累计评分
    3. 累计评分达到阈值 → 延迟封禁 + 删除该用户所有历史消息
    4. emoji面具检测（消息内容藏广告词）
    5. 旧版关键词检测兜底

    返回 True 表示广告已处理，应终止分发
    """
    if not dctx.is_group:
        return False

    # CHANNEL_IDS 中的自有频道自动转发是可信内部内容，只能由频道联动处理；
    # 其他频道不豁免，仍按普通广告证据门禁检测。
    try:
        from modules.linked_channel_sync import get_trusted_forward_channel_id
        if get_trusted_forward_channel_id(dctx.msg, dctx.ctx.config):
            return False
    except Exception as e:
        logger.debug(f"自有频道转发识别失败，继续广告检测: {e}")

    # [v5.38.29] 外部频道转发不再完全豁免广告检测；上面的自有频道白名单是唯一例外。
    # 旧版 AD_EXEMPT_CHANNEL_FORWARDS=true 会导致色情/灰产频道转发广告完全漏检。
    m = dctx.msg
    CONFIG = dctx.ctx.config

    msg = dctx.text
    m = dctx.msg
    from modules.ad_detector import AdDetector
    ad_text = AdDetector.extract_message_ad_text(m, msg)
    if not ad_text:
        return False

    # 跳过 Bot 命令，避免误封 /start@Bot 等正常指令
    if msg.startswith("/"):
        return False

    from modules.edit_detector import snapshot_message
    from modules.emoji_mask_detector import check_emoji_mask_in_message
    from modules.group_mgr import check_ad_content

    bot = dctx.ctx.bot
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    ad_detector = ctx.ad_detector
    keyword_manager = getattr(ctx, 'keyword_manager', None)
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id

    if _is_benign_ad_bypass_text(msg):
        try:
            if hasattr(ad_detector, "clear_user_tracking"):
                ad_detector.clear_user_tracking(uid)
        except Exception as e:
            logger.debug(f"[AD] 清理正常签到追踪失败: uid={uid} err={e}")
        logger.debug(f"[AD] 正常业务动作跳过广告检测: uid={uid} msg={msg[:30]}")
        return False

    # 白名单和群管理员必须在任何资料层检测前放行，避免 Bio/emoji 状态误伤正常用户。
    whitelist_cfg = CONFIG.get("AD_WHITELIST", {})
    raw_wl = whitelist_cfg.get("user_ids", []) if isinstance(whitelist_cfg, dict) else []
    whitelist_uids = set()
    for item in (raw_wl or []):
        try:
            whitelist_uids.add(int(item))
        except (TypeError, ValueError):
            continue
    if int(uid) in whitelist_uids:
        logger.debug(f"[AD] 白名单用户免检: uid={uid}")
        return False
    try:
        from modules.ad_enforcement import _is_chat_admin_member
        admin_status = _is_chat_admin_member(bot, chat_id, uid)
        if admin_status == "admin":
            logger.debug(f"[AD] 群管理员免检: uid={uid}")
            return False
        if admin_status == "unknown":
            # 网络失败不能默认有罪：跳过本轮自动处置，保留后续消息再判
            logger.warning(f"[AD] 群管身份查询失败，跳过本轮广告检测: uid={uid} chat={chat_id}")
            return False
    except Exception as e:
        logger.warning(f"[AD] 群管身份检查异常，跳过本轮: uid={uid} err={e}")
        return False

    # 短消息也必须先看资料层信号：广告号常用“1”等无意义内容探活。
    profile_score = 0
    profile_result = None
    profile_chat_info = None
    try:
        user_bio = ""
        try:
            profile_chat_info = bot.get_chat(uid)
            user_bio = (getattr(profile_chat_info, "bio", "") or "")[:500]
        except Exception as e:
            logger.debug(f"[AD] 短消息资料检测拉取Bio失败: uid={uid} err={e}")
        from modules.ad_profile_signals import detect_profile_ad_signal
        profile_result = detect_profile_ad_signal(
            bot, m.from_user, user_bio, CONFIG, chat_info=profile_chat_info
        )
        profile_score = int(profile_result.get("score", 0) or 0)
        if profile_result.get("is_ad"):
            from modules.ad_enforcement import enforce_ad_user
            message_is_ad = _has_direct_message_ad_evidence(ad_detector, ad_text)
            enforce_ad_user(
                bot=bot,
                db=db,
                config=CONFIG,
                chat_id=chat_id,
                uid=uid,
                uname=uname,
                reason=f"资料广告检测-{profile_result.get('reason', '')}",
                message=m,
                current_msg_id=getattr(m, "message_id", 0),
                current_message_is_ad=message_is_ad,
                notify_admin=True,
            )
            clear_logging_context()
            return True
    except Exception as e:
        logger.debug(f"[AD] 资料层广告检测异常: uid={uid} err={e}")

    # 短消息 + 有资料层可疑信号 → 不跳过，进入后续累计评分
    if len(ad_text) < 2 and profile_score <= 0:
        return False

    # [TRAE SOLO CN] v5.8.2 追踪群消息发送者到 group_members 表（渐进式构建完整成员列表）
    try:
        if dctx.is_group and m.from_user and not m.from_user.is_bot:
            _su = m.from_user
            _s_uname = getattr(_su, 'username', '') or ''
            _s_display = (_su.first_name or '') + (_su.last_name or '')
            db.upsert_group_member(_su.id, chat_id, _s_uname, _s_display, '', 'member')
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # 保存消息快照（用于编辑消息检测）
    snapshot_message(chat_id, m.message_id, msg)

    username = (m.from_user.first_name or "") + (m.from_user.last_name or "")

    # [TRAE SOLO CN] v5.7.5 新增：获取用户Bio用于广告检测
    user_bio = None
    try:
        if bot and m and m.from_user:
            user_chat = profile_chat_info or bot.get_chat(m.from_user.id)
            if user_chat and hasattr(user_chat, 'bio'):
                user_bio = user_chat.bio
                if user_bio:
                    logger.info(f"[AD] 获取用户Bio: uid={m.from_user.id}, bio={user_bio[:60]}")
    except Exception as e:
        logger.debug(f"[AD] 获取用户Bio失败: {e}")
        user_bio = None

    # [TRAE SOLO CN] v5.7.5 新增：短随机用户名检测（如@gc8181）
    telegram_username = ""
    if m.from_user.username:
        telegram_username = m.from_user.username
        # 检测短随机用户名：2-4位字母/数字组合，常见于广告小号
        import re as _re
        if _re.match(r'^[a-z]{1,4}\d{2,4}$', telegram_username, _re.IGNORECASE):
            logger.info(f"[AD] 检测到短随机用户名: @{telegram_username} uid={uid}")

    # [TRAE SOLO CN] v5.8.0 新增：提取消息元数据
    message_meta = {}
    try:
        if hasattr(m, 'forward_date') and m.forward_date:
            message_meta["is_forwarded"] = True
            message_meta["forward_date"] = m.forward_date.isoformat() if m.forward_date else None
            if not getattr(m, 'forward_from', None):
                message_meta["is_anonymous_forward"] = True
            if hasattr(m, 'forward_from_chat') and m.forward_from_chat:
                message_meta["forward_from_channel"] = True
        if hasattr(m, 'photo') and m.photo:
            message_meta["has_photo"] = True
        if hasattr(m, 'sticker') and m.sticker:
            message_meta["has_sticker"] = True
        if getattr(m, 'media_group_id', None):
            message_meta["is_media_group"] = True
        if getattr(m, 'web_page', None):
            message_meta["has_link_preview"] = True
        if hasattr(m, 'entities') and m.entities:
            url_count = sum(1 for e in m.entities if e.type == "url")
            if url_count > 0:
                message_meta["url_count"] = url_count
    except Exception as e:
        logger.debug(f"[AD] 提取消息元数据异常: {e}")

    # [TRAE SOLO CN] v5.8.0 新增：新用户行为检测
    try:
        member_info = bot.get_chat_member(chat_id, uid)
        if hasattr(member_info, 'joined_date') and member_info.joined_date:
            from datetime import datetime as _dt, timezone as _tz
            joined = member_info.joined_date
            if joined.tzinfo is None:
                joined = joined.replace(tzinfo=_tz.utc)
            elapsed_minutes = (_dt.now(_tz.utc) - joined).total_seconds() / 60
            if elapsed_minutes < 5:
                message_meta["is_new_user"] = True
                message_meta["joined_minutes_ago"] = int(elapsed_minutes)
                logger.info(f"[AD] 新用户行为: uid={uid}, 加入{int(elapsed_minutes)}分钟前")
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    # [Trae] v5.3.1 优化：传递user_id和bot参数，确保显示名称被正确捕获
    # [TRAE SOLO CN] v5.7.5 新增：传入bio进行联合检测
    # [TRAE SOLO CN] v5.8.0 新增：传入message_meta进行元数据辅助检测
    ad_result = ad_detector.detect(username=username, msg=msg, user_id=uid, bot=bot, bio=user_bio, message_meta=message_meta if message_meta else None, chat_id=chat_id, message=m)

    # emoji面具检测（消息内容藏广告词）
    emoji_suspicious, emoji_reason = check_emoji_mask_in_message(ad_text, CONFIG)
    if emoji_suspicious:
        logger.warning(f"🎭 消息emoji面具检测: uid={uid} reason={emoji_reason}")
        ad_result["is_ad"] = True
        ad_result["action"] = "ban"
        ad_result["reason"] = emoji_reason

    # [Trae] v5.3.1 新增：可疑用户名触发头像检测（双重确认机制）
    # [TRAE SOLO CN] v5.7.5 增强：头像检测触发条件扩展
    # 以下情况触发头像检测：
    # 1. 用户名可疑（原有）
    # 2. Bio含广告（新增）
    # 3. 短随机用户名（新增）
    uname_clean = username.strip()
    should_check_avatar = False
    avatar_trigger_reason = ""
    if not ad_result["is_ad"] and uname_clean:
        # 条件1：用户名异常分析得分 >= 1
        if ad_result.get("username_anomaly_score", 0) >= 1:
            should_check_avatar = True
            avatar_trigger_reason = f"用户名可疑({uname_clean[:20]})"
        # 条件2：bio检测得分 >= 2
        elif ad_result.get("bio_score", 0) >= 2:
            should_check_avatar = True
            avatar_trigger_reason = "bio含广告"
        # 条件3：短随机用户名（如 @gc8181）
        elif telegram_username and _re.match(r'^[a-z]{1,4}\d{2,4}$', telegram_username, _re.IGNORECASE):
            should_check_avatar = True
            avatar_trigger_reason = f"短随机用户名(@{telegram_username})"

    if should_check_avatar:
        try:
            from modules.avatar_detector import check_avatar_ocr_text
            # [TRAE SOLO CN] v5.8.5 新增：头像OCR文字检测（5秒超时保护）
            avatar_ocr_suspicious, avatar_ocr_text, avatar_ocr_score = False, "", 0
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ocr_executor:
                    _ocr_future = _ocr_executor.submit(check_avatar_ocr_text, bot, uid, CONFIG)
                    avatar_ocr_suspicious, avatar_ocr_text, avatar_ocr_score = _ocr_future.result(timeout=5)
            except concurrent.futures.TimeoutError:
                logger.warning("[AD] 头像OCR检测超时(5秒)，跳过")
                avatar_ocr_suspicious, avatar_ocr_text, avatar_ocr_score = False, "", 0
            except Exception as _ocr_err:
                logger.debug(f"[AD] 头像OCR检测异常: {_ocr_err}")
                avatar_ocr_suspicious, avatar_ocr_text, avatar_ocr_score = False, "", 0
            if avatar_ocr_suspicious and avatar_ocr_score >= 2:
                # 头像OCR明确命中广告文字
                bio_score_val = ad_result.get("bio_score", 0)
                content_score_before_avatar = ad_result.get("score", 0)
                if bio_score_val >= 1:
                    # Bio+头像OCR组合直接封禁
                    logger.warning(f"[AD] 🚫 Bio+头像OCR组合直接封禁: uid={uid} 头像文字={avatar_ocr_text[:30]}, Bio得分={bio_score_val}")
                    ad_result["is_ad"] = True
                    ad_result["action"] = "ban"
                    ad_result["reason"] = f"Bio+头像OCR组合封禁: 头像含'{avatar_ocr_text[:20]}'"
                elif content_score_before_avatar >= 1:
                    # 头像只可强化独立的正文信号，不能凭头像或昵称异常单独定罪。
                    logger.info(f"[AD] 头像OCR命中广告文字: uid={uid} 文字={avatar_ocr_text[:30]}, 评分+{avatar_ocr_score}")
                    ad_result["score"] = ad_result.get("score", 0) + avatar_ocr_score
                    # 如果总分达到阈值，也触发封禁
                    if ad_result["score"] >= 3:
                        ad_result["is_ad"] = True
                        ad_result["action"] = "ban"
                        ad_result["reason"] = f"头像OCR广告文字触发: {avatar_ocr_text[:30]}"
                else:
                    logger.info(
                        f"[AD] 头像OCR仅作辅助证据，不单独处置: uid={uid} "
                        f"文字={avatar_ocr_text[:30]}"
                    )
            
        except Exception as e:
            logger.debug(f"头像检测异常: {e}")

    # [TRAE SOLO CN] v5.8.1 修改：用户名+Bio两层组合直接封禁（不再等阈值）
    # [TRAE SOLO CN] v5.8.5 优化：Bio得分>=2 + 头像OCR命中 也触发封禁
    if not ad_result["is_ad"]:
        bio_score_val = ad_result.get("bio_score", 0)
        uname_anomaly_val = ad_result.get("username_anomaly_score", 0)
        if uname_anomaly_val >= 1 and bio_score_val >= 3:
            ad_result["is_ad"] = True
            ad_result["action"] = "ban"
            ad_result["reason"] = f"两层组合直接封禁(用户名+Bio): 用户名异常+Bio广告"
            logger.warning(f"[AD] 两层组合直接封禁: uid={uid} 用户名+Bio全部命中")

    # 场景A：即时命中广告规则 → 直接处理
    if ad_result["is_ad"]:
        if _handle_immediate_ad(dctx, ad_result):
            return True

    # 场景B：追踪所有用户消息历史（无论score多少，用于连续消息模式检测）
    # [TRAE SOLO CN] 修复：无条件追踪，避免短广告（如"找人合作"）评分不足漏网
    # 无视觉模型时 profile_score=2（有emoji状态），加到累计评分中
    content_score = ad_result.get("score", 0)
    total_score = content_score + profile_score
    if profile_score > 0:
        logger.info(f"[AD] 资料层可疑信号: uid={uid} profile_score={profile_score} reason={profile_result.get('reason', '')[:80] if profile_result else ''}")
    direct_result = _direct_message_ad_result(ad_detector, ad_text)
    direct_message_is_ad = bool(
        direct_result.get("is_ad") and direct_result.get("action") == "ban"
    )
    track_result = ad_detector.track_suspicious_user(
        user_id=uid,
        msg_id=m.message_id,
        chat_id=chat_id,
        text=ad_result.get("ad_text", msg) or msg,
        score=total_score,
        is_ad=ad_result.get("is_ad", False) is True,
        direct_message_score=int(direct_result.get("score", 0) or 0),
        direct_message_is_ad=direct_message_is_ad,
    )
    if track_result["action"] == "ban":
        if _handle_delayed_ad_tracking(dctx, track_result):
            return True

    # 连续消息模式：一小时同文/极近 3 次只删重复组；其他独立强证据沿用广告处置。
    consecutive_result = ad_detector.check_consecutive_patterns(uid, chat_id, bot)
    if consecutive_result["is_spam"]:
        logger.warning(f"连续消息模式检测: uid={uid} reason={consecutive_result['reason']}")
        if consecutive_result.get("behavior_only"):
            from modules.ad_enforcement import delete_repeated_spam_messages
            cleanup = delete_repeated_spam_messages(
                bot, db, consecutive_result.get("messages", [])
            )
            logger.warning(
                f"重复刷屏消息清理: uid={uid} chat={chat_id} "
                f"deleted={cleanup['deleted_count']} absent={cleanup['already_absent_count']} "
                f"failed={cleanup['failed_count']}"
            )
            # 即使 Telegram 某条删除失败，本轮也必须在 P10 AI 前停止，避免机器人接话。
            clear_logging_context()
            return True
        # 创建广告结果并处理
        ad_result["is_ad"] = True
        ad_result["action"] = "ban"
        ad_result["score"] = consecutive_result["score"]
        ad_result["reason"] = consecutive_result["reason"]
        if _handle_immediate_ad(dctx, ad_result):
            return True

    # 旧版关键词检测兜底（防漏网）
    if check_ad_content(bot, m, CONFIG, db, keyword_manager):
        clear_logging_context()
        return True

    return False


def _check_bot_permission(bot, chat_id, permission: str) -> bool:
    """检查Bot在群中的权限"""
    try:
        me = bot.get_me()
        bot_id = me.id
        bot_member = bot.get_chat_member(chat_id, bot_id)
        if bot_member.status not in ("administrator", "creator"):
            logger.warning(f"[权限检查] Bot不是管理员，缺少权限: {permission}")
            return False
        
        if hasattr(bot_member, 'can_delete_messages') and permission == "delete_messages":
            return bot_member.can_delete_messages
        if hasattr(bot_member, 'can_restrict_members') and permission == "restrict_members":
            return bot_member.can_restrict_members
        
        if hasattr(bot_member, 'permissions'):
            perms = bot_member.permissions
            if permission == "delete_messages" and hasattr(perms, 'can_delete_messages'):
                return perms.can_delete_messages
            if permission == "restrict_members" and hasattr(perms, 'can_restrict_members'):
                return perms.can_restrict_members
        
        return True
    except Exception as e:
        logger.warning(f"[权限检查] 获取Bot权限失败: {e}")
        return False


def _handle_immediate_ad(dctx, ad_result: dict) -> bool:
    """处理即时命中的广告：永久禁言+删消息+双黑名单，不踢人。"""
    from modules.ad_enforcement import enforce_ad_user

    reason = str(ad_result.get("reason", "") or "")
    message_is_ad = _has_direct_message_ad_evidence(dctx.ctx.ad_detector, dctx.text)
    if "emoji" in reason.lower() or "消息emoji面具" in reason:
        message_is_ad = True
    enforce_ad_user(
        bot=dctx.ctx.bot,
        db=dctx.ctx.db,
        config=dctx.ctx.config,
        chat_id=dctx.chat_id,
        uid=dctx.uid,
        uname=dctx.uname,
        reason=f"广告检测-{ad_result.get('reason', '')}",
        message=dctx.msg,
        current_msg_id=getattr(dctx.msg, "message_id", 0),
        current_message_is_ad=message_is_ad,
        notify_admin=True,
    )
    clear_logging_context()
    return True


def _handle_delayed_ad_tracking(dctx, track_result: dict) -> bool:
    """处理延迟封禁追踪（累计评分达到阈值后封禁）

    Args:
        dctx: 分发上下文
        track_result: track_suspicious_user 返回的结果字典
    """
    bot = dctx.ctx.bot
    m = dctx.msg
    ctx = dctx.ctx
    CONFIG = ctx.config
    db = ctx.db
    ad_detector = ctx.ad_detector
    uid = dctx.uid
    uname = dctx.uname
    chat_id = dctx.chat_id

    if track_result["action"] == "ban":
        # 证据门禁：累计分 alone 不能永久禁言；至少 1 条直证广告消息
        msgs = track_result.get("messages") or []
        has_direct = any(
            bool(item.get("direct_message_is_ad") or item.get("is_ad"))
            for item in msgs
            if isinstance(item, dict)
        )
        if not has_direct:
            logger.warning(
                f"[AD] 延迟封禁被证据门禁拦截（仅累计分/资料分无直证）: "
                f"uid={uid} total={track_result.get('total_score')} msgs={len(msgs)}"
            )
            return False

        logger.warning(f"[AD] 🚫 延迟封禁执行: uid={uid}, 累计评分={track_result['total_score']}")
        from modules.ad_enforcement import enforce_ad_user

        enforce_ad_user(
            bot=bot,
            db=db,
            config=CONFIG,
            chat_id=chat_id,
            uid=uid,
            uname=uname,
            reason=f"延迟广告累计评分{track_result['total_score']}",
            message=m,
            current_msg_id=getattr(m, "message_id", 0),
            notify_admin=True,
        )

        # 4. 清除追踪记录
        ad_detector.clear_user_tracking(uid)
        clear_logging_context()
        return True

    elif track_result["action"] == "watch":
        # 继续观察，只记录不拦截
        logger.info(f"[AD] 👁️ 用户追踪中: uid={uid}, 累计评分={track_result['total_score']}")

    return False
