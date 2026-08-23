"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/group_mgr.py  ·  超级群管模块                                ║
║                                                                        ║
║  功能：群组自动化管理。                                                 ║
║                                                                        ║
║  handle_new_members() -> 新人入群欢迎                                   ║
║    - 自动发送群规科普                                                  ║
║    - 群内只提供一个预览入口，不主动私聊推销                            ║
║    - 初始化用户等级记录                                                ║
║                                                                        ║
║  check_banned_words() -> 敏感词过滤                                     ║
║    - 检测到黑名单词 -> 删除消息 + 通知用户 + 告知管理员                 ║
║                                                                        ║
║  check_ad_content() -> AI广告检测（v4.5.26新增）                        ║
║    - 消息内容AI判断是否为广告/引流/诈骗                                 ║
║    - 检测到广告 -> 删除消息 + 永久禁言 + 举报 + 清空历史消息            ║
║    - 通知管理员（用户名+@ID格式）                                       ║
║                                                                        ║
║  check_spam() -> 反刷屏机制                                             ║
║    - 60秒内超过阈值 -> 自动禁言 + 通知群                               ║
║    - 阈值在config.json SPAM_LIMIT中配置                                ║
║                                                                        ║
║  handle_left_member() -> 流失打捞                                       ║
║    - 用户退群 -> 只记录统计；可选中性问候默认关闭                       ║
║                                                                        ║
║  detect_keywords() -> 消息特征提取                                      ║
║    - 识别AI模式(tarot/treehole/dream/convert等)                       ║
║    - 提取用户偏好标签(写入数据库画像)                                  ║
║    - 检测仇恨词                                                        ║
║    - 返回dict: {mode, is_cart, keyword_tag, is_hate}                   ║
║                                                                        ║
║  被调用：main.py -> P1新人/P2黑名单/P3广告/P3.5反刷/P9特征提取         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import random
import re
from core.logging_util import get_logger
from core.keyword_manager import (
    _DEFAULT_AD_KEYWORDS,
    _DEFAULT_AUTO_MUTE_NAMES,
    _DEFAULT_CONVERT_SUBSTR,
    _DEFAULT_CONVERT_WORD,
    is_convert_rejection_message,
)
from modules.ad_detector import check_username_suspicious
from modules.avatar_detector import check_and_ban_if_porn_avatar, check_avatar_ocr_text
from modules.ad_profile_signals import detect_profile_ad_signal
from modules.ad_patterns_encoded import BIO_PATTERNS

logger = get_logger("group_mgr")

# 这些词有大量正常业务语境，旧版子串兜底不得把它们作为单一封禁证据。
# 强组合与拆字变体由 AdDetector 的多维规则负责。
_AMBIGUOUS_LEGACY_AD_KEYWORDS = frozenset({"代收", "代付"})

# 模块级缓存bot id，避免每次调用bot.get_me()
_bot_cached_id = None

def _get_bot_id(bot):
    """获取bot用户ID（带缓存）"""
    global _bot_cached_id
    if _bot_cached_id is None:
        _bot_cached_id = bot.get_me().id
    return _bot_cached_id


def handle_new_members(bot, m, config: dict, db, keyword_manager=None):
    """新人入群欢迎"""
    _bot_id = _get_bot_id(bot)
    # 优先从 KeywordManager 获取，兼容旧调用方式
    if keyword_manager:
        auto_mute_names = keyword_manager.get_auto_mute_names()
    else:
        auto_mute_names = config.get("AUTO_MUTE_NAMES", _DEFAULT_AUTO_MUTE_NAMES)
    
    for user in m.new_chat_members:
        if user.id == _bot_id:
            continue
        
        user_name = (user.first_name or "") + (user.last_name or "")
        username = getattr(user, 'username', None)
        user_display = f"{user_name}"
        if username:
            user_display += f" @{username}"

        if db:
            db.record_group_join(m.chat.id, user.id)

        matched_keyword = None
        for kw in auto_mute_names:
            if len(kw) <= 2 and kw.isascii():
                pattern = r'(?<![a-zA-Z0-9])' + re.escape(kw) + r'(?![a-zA-Z0-9])'
                if re.search(pattern, user_name, re.IGNORECASE):
                    matched_keyword = kw
                    break
            else:
                if kw.lower() in user_name.lower():
                    matched_keyword = kw
                    break

        # ── v4.5.36 新增：检测可疑用户名（Custom Emoji贴图/引流文字）──
        is_suspicious, suspicious_reason = check_username_suspicious(user_name)

        # ── v5.30.2 新增：头像OCR文字检测（"看我简介"类视觉广告） ──
        avatar_ocr_hit = False
        avatar_ocr_text = ""
        avatar_ocr_score = 0
        try:
            avatar_ocr_hit, avatar_ocr_text, avatar_ocr_score = check_avatar_ocr_text(
                bot, user.id, config
            )
            if avatar_ocr_hit:
                logger.warning(
                    f"🚫 头像OCR命中广告: {user_display}({user.id}) "
                    f"文字={avatar_ocr_text[:50]} 评分={avatar_ocr_score}"
                )
        except Exception as e:
            logger.warning(f"头像OCR检测失败 {user_display}: {e}")

        # ── v5.30.2 新增：BIO简介广告检测 ──
        bio_hit = False
        bio_text = ""
        chat_info = None
        try:
            chat_info = bot.get_chat(user.id)
            bio_text = getattr(chat_info, "bio", "") or ""
            if bio_text:
                # 直接用 BIO_PATTERNS 做正则匹配（零TOKEN消耗）
                for pattern in BIO_PATTERNS:
                    try:
                        if re.search(pattern, bio_text, re.IGNORECASE):
                            bio_hit = True
                            logger.warning(
                                f"🚫 BIO命中广告规则: {user_display}({user.id}) "
                                f"bio={bio_text[:50]} pattern={pattern[:30]}"
                            )
                            break
                    except re.error:
                        continue
            # 无 Bio 时 personal_chat 仍可能有广告；复用已取 Chat，禁止二次 getChat。
            if not bio_hit:
                profile_result = detect_profile_ad_signal(
                    bot, user, bio_text, config, chat_info=chat_info
                )
                if profile_result.get("is_ad"):
                    bio_hit = True
                    logger.warning(
                        f"🚫 资料信号命中广告: {user_display}({user.id}) "
                        f"reason={profile_result.get('reason', '')}"
                    )
        except Exception as e:
            logger.debug(f"BIO检测失败 {user_display}: {e}")

        # 头像只作为辅助证据，不能单信号封禁；名字/Bio仍按各自强规则处置。
        if matched_keyword or is_suspicious or bio_hit:
            if matched_keyword:
                logger.warning(f"🚫 已加黑名单：{user_display} 命中关键词={matched_keyword}")
                notify_reason = f"🔑 命中关键词：{matched_keyword}"
            elif bio_hit:
                logger.warning(f"🚫 已加黑名单：{user_display} 原因=BIO简介广告")
                avatar_note = f"；头像OCR辅助={avatar_ocr_text[:20]}" if avatar_ocr_hit else ""
                notify_reason = f"🔑 原因：简介/BIO包含广告内容 bio={bio_text[:30]}{avatar_note}"
            else:
                logger.warning(f"🚫 已加黑名单：{user_display} 原因={suspicious_reason}")
                notify_reason = f"🔑 原因：{suspicious_reason}"
            from modules.ad_enforcement import enforce_ad_user
            enforce_ad_user(
                bot=bot,
                db=db,
                config=config,
                chat_id=m.chat.id,
                uid=user.id,
                uname=user_display,
                reason=f"入群广告资料拦截: {notify_reason}",
                notify_admin=True,
            )
            continue

        db.upsert_user(user.id, user.first_name or "新人", "group")
        db.add_points(user.id, 0)

        welcome = f"""👋 {user.first_name or '你'}，欢迎加入。

想先了解内容，可以去 @moryselect 看当前预览，没写清楚的直接问我呀。

有问题直接在群里问小助理；未成年请勿参与。"""

        bot.send_message(m.chat.id, welcome)

        logger.info(f"👋 新人欢迎：{user.id} {user.first_name}")


def check_banned_words(bot, m, config: dict, db) -> bool:
    """检查黑名单词，返回True表示消息已处理（删除）"""
    msg = m.text or ""
    for word in config.get("BANNED_WORDS", []):
        if word in msg:
            try:
                bot.delete_message(m.chat.id, m.message_id)
                bot.send_message(m.from_user.id,
                    f"⚠️ 你的消息含有敏感词已被删除，请遵守社群规则～")
                # 【v4.5.35修复】管理员通知中不再泄露原始消息内容，只显示触发词
                _uname = getattr(m.from_user, 'username', None)
                _user_display = m.from_user.first_name or ""
                if _uname:
                    _user_display += f" @{_uname}"
                bot.send_message(config["ADMIN_ID"],
                    f"🚨 用户 {_user_display} "
                    f"触发了敏感词「{word}」\n"
                    f"💡 消息已删除，原始内容未记录")
            except Exception as e:
                logger.warning(f"删除敏感词消息失败：{e}")
            logger.warning(f"⚠️ 敏感词拦截：uid={m.from_user.id} word={word}")
            return True
    return False


def check_ad_content(bot, m, config: dict, db, keyword_manager=None) -> bool:
    """
    广告检测（v4.5.26新增）— 纯规则匹配，零token消耗
    检测消息内容是否为广告/引流/诈骗/营销
    
    流程：
    1. 关键词匹配（从 KeywordManager 或 config 加载），命中直接处理
    2. 确认广告 → 删除消息 + 永久禁言 + 通知管理员
    
    Returns:
        True表示已处理（删除+禁言），False表示非广告
    """
    msg = (m.text or "").strip()
    if not msg or len(msg) < 2:
        return False
    
    chat_id = m.chat.id
    uid = m.from_user.id
    uname = m.from_user.first_name or ""
    uusername = getattr(m.from_user, 'username', None)
    user_display = uname
    if uusername:
        user_display += f" @{uusername}"
    
    # 优先从 KeywordManager 获取，兼容旧调用方式
    if keyword_manager:
        ad_keywords = keyword_manager.get_ad_keywords()
    else:
        ad_keywords = config.get("AD_KEYWORDS", _DEFAULT_AD_KEYWORDS)

    hit_kw = None
    message_hit_kw = None
    msg_lower = msg.lower()
    uname_lower = uname.lower()
    # 先完整扫描正文，再扫描昵称，避免较早的昵称词遮住后续正文证据。
    for kw in ad_keywords:
        kw_lower = kw.lower()
        if kw_lower in _AMBIGUOUS_LEGACY_AD_KEYWORDS:
            continue
        if kw_lower in msg_lower:
            hit_kw = kw
            message_hit_kw = kw
            break
    if not hit_kw:
        for kw in ad_keywords:
            kw_lower = kw.lower()
            if kw_lower in _AMBIGUOUS_LEGACY_AD_KEYWORDS:
                continue
            if kw_lower in uname_lower:
                hit_kw = kw
                break

    if not hit_kw:
        return False
    
    logger.warning(f"🚫 广告检测命中: {user_display} 关键词={hit_kw}")
    
    # 删除、禁言与审计统一由 enforce_ad_user 执行，避免旧链重复删除或受普通总闸影响。
    from modules.ad_enforcement import enforce_ad_user
    enforce_ad_user(
        bot=bot,
        db=db,
        config=config,
        chat_id=chat_id,
        uid=uid,
        uname=user_display,
        reason=f"旧版关键词兜底命中: {hit_kw}",
        message=m,
        current_msg_id=m.message_id,
        current_message_is_ad=message_hit_kw is not None,
        notify_admin=True,
    )
    
    return True


def check_spam(bot, m, config: dict, db) -> bool:
    """反刷机制，返回True代表触发刷屏"""
    limit = config.get("SPAM_LIMIT", {})
    msg_limit = limit.get("messages_per_minute", 10)
    ban_min = limit.get("ban_minutes", 5)
    uid = m.from_user.id
    # 【TRAE SOLO CN v5.18.3审计修复】管理员和白名单用户豁免，避免误伤
    try:
        member = bot.get_chat_member(m.chat.id, uid)
        if member.status in ("administrator", "creator"):
            return False
    except Exception as e:
        logger.debug(f"检查管理员状态失败 uid={uid}: {e}")
    # 白名单用户豁免
    try:
        from modules.approvals import is_approved
        if is_approved(db, m.chat.id, uid):
            return False
    except Exception as e:
        logger.debug(f"检查白名单失败 uid={uid}: {e}")
    if db.check_spam(uid, msg_limit):
        db.mute_user(uid, m.chat.id, ban_min, "刷屏")
        try:
            from telebot.types import ChatPermissions
            import time
            bot.restrict_chat_member(m.chat.id, uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + ban_min * 60)
            # [Trae] v4.5.36 修复：刷屏通知不再发到群里，只通知管理员
            admin_id = config.get("ADMIN_ID", 0)
            if admin_id:
                try:
                    bot.send_message(admin_id,
                        f"🔇 刷屏禁言通知\n"
                        f"👤 用户：{m.from_user.first_name or '未知'}({uid})\n"
                        f"📋 操作：禁言 {ban_min} 分钟\n"
                        f"💡 如误封请手动解禁")
                except Exception as e:
                    logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.warning(f"刷屏禁言操作失败 uid={uid}：{e}")
        logger.warning(f"🔇 刷屏禁言：uid={uid}")
        return True
    return False


def handle_left_member(bot, m, config: dict, db=None):
    """记录用户离群；可选中性问候默认关闭，不做情感施压或销售。"""
    uid = m.left_chat_member.id
    if uid == _get_bot_id(bot):
        return
    name = m.left_chat_member.first_name or "你"
    if db:
        db.record_group_left(m.chat.id, uid)  # 【v4.9.5】记录离群统计（带user_id幂等保护）
    cfg = config.get("LEAVE_FOLLOWUP_CONFIG", {})
    if not isinstance(cfg, dict) or not cfg.get("enabled", False):
        logger.info(f"离群已记录，不主动私聊 uid={uid}")
        return
    try:
        bot.send_message(uid, f"{name}，感谢之前参与群聊。之后想回来时再来就好。")
        logger.info(f"离群中性问候：{uid}")
    except Exception as e:
        logger.warning(f"离群中性问候失败 uid={uid}：{e}")


# 商业关键词集合（v5.14.0 扩展）
# 短词用子串匹配，5字符以上的复合词用全词匹配，避免"包月"误匹配"包月嫂"等无关词
# 【重构】默认值已迁移到 core/keyword_manager.py，此处保留为兼容旧代码的 fallback
_CONVERT_KEYWORDS_SUBSTR = _DEFAULT_CONVERT_SUBSTR

# 全词匹配关键词（仅用于需要避免误匹配的长词）
_CONVERT_KEYWORDS_WORD = _DEFAULT_CONVERT_WORD


def _is_convert_message(msg: str, keyword_manager=None) -> bool:
    """[v5.14.0] 判断消息是否属于商业咨询类（convert 模式）

    匹配规则：
    - 短关键词（≤4字）：子串匹配
    - 长关键词（≥5字）：全词匹配（用空格/标点切分后判断），避免"包月"误匹配"包月嫂"

    Args:
        msg: 用户消息文本
        keyword_manager: KeywordManager 实例（可选，优先使用）
    """
    if not msg:
        return False
    if is_convert_rejection_message(msg):
        return False

    # 优先使用 KeywordManager
    if keyword_manager:
        return keyword_manager.is_convert_message(msg)

    # fallback：使用模块级变量
    # 子串匹配（短词）
    if any(k in msg for k in _CONVERT_KEYWORDS_SUBSTR):
        return True

    # 全词匹配（长词）
    # 用非中文字符切分
    import re as _re
    words = _re.split(r'[^\u4e00-\u9fff]+', msg)
    words = [w for w in words if w]
    for w in words:
        if w in _CONVERT_KEYWORDS_WORD:
            return True

    return False


def detect_keywords(msg: str, config: dict, keyword_manager=None) -> dict:
    """
    提取消息特征，返回模式和标记字典
    {
        'mode': 'normal'|'tarot'|'treehole'|'dream'|'convert'|...
        'is_cart': bool  # 是否触发购物车
        'keyword_tag': str  # 用户偏好标签
        'is_hate': bool  # 是否包含仇恨词
        'slang_reply': str  # 如果匹配到黑话，返回科普回复（空字符串表示无匹配）
    }
    """
    result = {
        "mode": "normal",
        "is_cart": False,
        "keyword_tag": "",
        "is_hate": False,
        "slang_reply": "",
        "weather_empathy": "",  # 天气/城市共情回复
    }

    # 天气/城市共情（硬编码词表，优先于AI模式）
    # 词表只收词组：单字“冷/热/雷”会把“冷知识/热烈欢迎/雷人”全部误触。
    _weather_words = {
        "下雨": "下雨天记得带伞哦，别淋湿了～",
        "暴雨": "暴雨天注意安全，尽量别出门啦！",
        "下雪": "下雪啦！好浪漫，记得穿暖和点～",
        "晴天": "今天天气真好，适合出来走走～",
        "出太阳": "大太阳出来啦，注意防晒哦～",
        "台风": "台风天一定要待在室内，安全第一！",
        "降温": "降温了！多穿点，别感冒了～",
        "升温": "天气热起来了，记得多喝水补水哦！",
        "好冷": "好冷的话多穿点，别逞强冻着自己～",
        "好热": "这么热的天，喝杯奶茶降降温吧～",
        "刮风": "风好大，头发都要被吹乱了哈哈～",
        "阴天": "阴天也要保持好心情哦～",
        "多云": "多云天气刚好，不晒也不冷～",
        "打雷": "打雷了！注意安全，尽量别在空旷处待着～",
        "雾霾": "今天雾霾严重，出门记得戴口罩哦！",
        "大雨": "雨好大，注意安全别涉水哦～",
        "冰雹": "冰雹天千万别出门！安全最重要！",
        "沙尘": "沙尘天气少出门，回家记得洗脸哦～",
    }
    _city_words = [
        "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "武汉",
        "西安", "南京", "天津", "苏州", "长沙", "郑州", "东莞", "青岛",
        "沈阳", "宁波", "昆明", "大连", "厦门", "福州", "无锡", "合肥",
        "济南", "佛山", "唐山", "温州", "哈尔滨", "长春", "贵阳", "南宁",
        "太原", "南昌", "石家庄", "兰州", "呼和浩特", "乌鲁木齐", "拉萨",
        "海口", "三亚", "珠海", "惠州", "中山", "潍坊", "徐州", "烟台",
    ]
    for w, resp in _weather_words.items():
        if w in msg:
            # 找到匹配的城市名
            city = ""
            for c in _city_words:
                if c in msg:
                    city = c
                    break
            if city:
                result["weather_empathy"] = f"{city}也{w}了吗？{resp}"
            else:
                result["weather_empathy"] = resp
            break  # 只匹配第一个天气词
    else:
        # 没有匹配到天气词，检查是否提到城市
        if any(c in msg for c in _city_words):
            for c in _city_words:
                if c in msg:
                    result["weather_empathy"] = f"{c}呀？那边的群友出来打个招呼～"
                    break

    # AI模式识别
    if any(k in msg for k in ["抽牌", "运势", "占卜", "塔罗"]):
        result["mode"] = "tarot"
    elif any(k in msg for k in ["累", "失恋", "难受", "压力", "崩溃", "心疼"]):
        result["mode"] = "treehole"
    elif "梦到" in msg and ("Mory" in msg or "老板" in msg):
        result["mode"] = "dream"
    elif _is_convert_message(msg, keyword_manager):
        result["is_cart"] = True
        result["mode"] = "convert"

    # 用户反馈/找Mory 检测（优先于普通AI闲聊，避免AI瞎撩人）
    # 【v4.7.1 新增】反馈模式 — 用户遇到问题/反馈异常
    # 【v4.12.1 优化】关键词全小写 + msg.lower() 匹配，兼容大小写变体
    msg_lower = msg.lower()
    _feedback_words = [
        # 封禁/踢出类
        "被封", "封了", "禁言", "踢出", "被踢", "踢了", "踢出群", "解封", "解禁",
        "踢回来", "加回来", "加回群", "加回来群",
        # 举报/投诉类
        "举报", "投诉", "反馈", "反应", "有问题", "出bug", "坏了", "登不上", "登录不上",
        "出问题", "不对劲", "有问题找",
        # 找人类（全小写匹配，兼容Mory/mory/MORY）
        "找mory", "找老板", "找boss",
        "叫mory", "叫老板", "叫boss",
        "请mory", "请老板",
        "联系mory", "联系老板", "让mory", "让老板",
        "mory在吗", "老板在吗", "有人在吗", "mory在么", "老板在么",
        "mory呢", "老板呢", "boss呢",
        # 新增变体
        "呼叫mory", "呼叫老板", "呼叫boss",
        "召唤mory", "召唤老板",
    ]
    # 【v4.7.1 新增】找Mory模式 — 用户明确想找Mory/老板本人
    _contact_mory_words = [
        "要找mory", "要找老板", "要找boss", "我要找mory", "我想找老板",
        "mory本人", "老板本人", "见老板", "见mory", "私聊老板", "私聊mory",
        "让mory来", "叫老板来", "喊老板", "喊mory",
        # 新增变体
        "呼叫mory本人", "呼叫老板本人",
        "想见mory", "想见老板",
        "找mory本人", "找老板本人",
    ]
    # 反馈模式（覆盖找人类关键词）
    if any(k in msg_lower for k in _feedback_words):
        result["mode"] = "feedback"
    elif any(k in msg_lower for k in _contact_mory_words):
        result["mode"] = "contact_mory"

    # 黑话/行话自动识别（匹配到的第一个黑话就科普，避免刷屏）
    slang_dict = config.get("SLANG_DICT", {})
    for slang, explanation in slang_dict.items():
        if slang in msg:
            result["slang_reply"] = f"📖 新人科普：「{slang}」的意思是——\n{explanation}"
            break  # 只匹配第一个，避免一条消息触发多条科普

    # 用户偏好画像（扩展版 v4.2.3）
    # 优先级：精准词 > 模糊词，避免一条消息打多个标签
    _tag_rules = [
        # 内容偏好
        (["腿", "黑丝", "丝袜", "美腿"], "偏好黑丝/腿控"),
        (["声音", "音频", "语音", "听"], "偏好声音内容"),
        (["视频", "动态", "gif", "短视频"], "偏好视频内容"),
        (["原味", "原版", "原始"], "偏好原味内容"),
        (["定制", "专属", "定做"], "偏好定制服务"),
        (["图片", "照片", "写真", "图集"], "偏好图片集"),
        (["直播", "真人", "实时"], "偏好直播内容"),
        # 行为偏好
        (["多少钱", "价格", "怎么买", "门槛", "开通", "会员", "订阅"], "付费意向-询问价格"),
        (["优惠", "折扣", "便宜", "划算", "活动", "特价"], "付费意向-关注优惠"),
        (["看看", "想看", "给我", "发一下", "有没有"], "付费意向-主动索要看货"),
        (["付款", "支付", "转账", "红包", "支付宝", "微信"], "付费意向-准备付款"),
        (["先看看", "再考虑", "犹豫", "纠结"], "付费意向-犹豫中"),
        # 互动偏好
        (["早安", "晚安", "早上好", "睡了"], "高活跃-日常问候"),
        (["签到", "打卡", "每日"], "高活跃-签到用户"),
        (["塔罗", "占卜", "抽牌", "运势"], "高活跃-娱乐互动"),
        (["老板", "Mory", "小助理"], "高认同-提及品牌"),
        # 情感状态
        (["累", "困", "疲惫", "辛苦"], "情感状态-疲惫"),
        (["开心", "高兴", "快乐", "爽"], "情感状态-开心"),
        (["无聊", "没事干", "闲着"], "情感状态-无聊"),
        (["失恋", "难受", "难过", "崩溃", "压力"], "情感状态-负面情绪"),
    ]
    for keywords, tag in _tag_rules:
        if any(k in msg for k in keywords):
            result["keyword_tag"] = tag
            break

    # 仇恨词检测
    if any(k in msg for k in config.get("HATE_KEYWORDS", [])):
        result["is_hate"] = True

    return result
