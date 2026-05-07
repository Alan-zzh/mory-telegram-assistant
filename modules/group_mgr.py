"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/group_mgr.py  ·  超级群管模块                                ║
║                                                                        ║
║  功能：群组自动化管理。                                                 ║
║                                                                        ║
║  handle_new_members() -> 新人入群欢迎                                   ║
║    - 自动发送群规科普                                                  ║
║    - 私聊发送会员权益介绍                                              ║
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
║    - 用户退群 -> 私聊发送挽留话术                                       ║
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

import logging
import random
import re
from core.logging_util import get_logger

logger = get_logger("group_mgr")

# 模块级缓存bot id，避免每次调用bot.get_me()
_bot_cached_id = None

def _get_bot_id(bot):
    """获取bot用户ID（带缓存）"""
    global _bot_cached_id
    if _bot_cached_id is None:
        _bot_cached_id = bot.get_me().id
    return _bot_cached_id


def handle_new_members(bot, m, config: dict, db):
    """新人入群欢迎"""
    _bot_id = _get_bot_id(bot)
    auto_mute_names = config.get("AUTO_MUTE_NAMES", [
        "虚拟币", "搬砖", "币圈", "炒币", "数字货币",
        "加密货币", "区块链投资", "合约交易", "量化交易",
        "USDT", "BTC", "ETH交易", "空投", "挖矿",
    ])
    
    for user in m.new_chat_members:
        if user.id == _bot_id:
            continue
        
        user_name = (user.first_name or "") + (user.last_name or "")
        username = getattr(user, 'username', None)
        user_display = f"{user_name}"
        if username:
            user_display += f" @{username}"
        
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
        
        if matched_keyword:
            try:
                bot.restrict_chat_member(
                    m.chat.id, user.id,
                    until_date=0,
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                )
                logger.warning(f"🚫 自动永久禁言：{user_display} 命中关键词={matched_keyword}")
                admin_id = config.get("ADMIN_ID", 0)
                if admin_id:
                    try:
                        bot.send_message(admin_id,
                            f"🚫 自动禁言通知\n"
                            f"👤 用户：{user_display}\n"
                            f"🔑 命中关键词：{matched_keyword}\n"
                            f"📋 操作：永久禁言\n"
                            f"💡 如误封请手动解禁")
                    except Exception:
                        pass
                continue
            except Exception as e:
                logger.error(f"自动禁言失败 {user_display}：{e}")
        
        db.upsert_user(user.id, user.first_name or "新人", "group")
        db.add_points(user.id, 0)
        db.record_group_join(m.chat.id)

        welcome = f"""👋 欢迎 {user.first_name or '亲爱的'} 加入！

🎞 【视觉之窗 · 免费预览】
👉 @moryselect (先看诚意，再谈定力)

🤖 【自助入 VIP · 深夜补给】
👉 @MorychannelBot (4K母版/全量免遮/一键解锁)
💎 海外用户(Fansone)：https://fansone.co/m0i3i4

🔞 【独占特权 · 深度变现】
👕 [原味私藏]：带着体温的内衣/丝袜，顺丰包邮，把我的味道带回家。
📽 [私人定制]：你的剧本，我的身体，1v1 拍摄，满足最脏的幻想。
📞 [私密联系]：仅限付费 VIP 解锁个人联系方式，非诚勿扰。

📢 【咨询与反馈】
有问题请 @小助理或 @Moryfansbot 寻求帮助。

🌐 唯一官网 https://Mory.life
未成年禁入 | 理智消费 | 这里只欢迎有体面的成年人。"""

        bot.send_message(m.chat.id, welcome)

        # 黑话/行话新人提示（10%概率触发，避免每次都发）
        if random.random() < 0.1:
            slang_dict = config.get("SLANG_DICT", {})
            if slang_dict:
                sample = random.sample(list(slang_dict.items()), min(3, len(slang_dict)))
                slang_text = "\n".join([f"  💡 {k}：{v}" for k, v in sample])
                try:
                    bot.send_message(m.chat.id,
                        f"📖 新人小贴士：本群有一些专属术语哦～\n{slang_text}\n"
                        f"听不懂随时问小助理～")
                except Exception as e:
                    logger.warning(f"发送新人术语提示失败：{e}")

        # 私聊发送完整介绍
        intro = (f"嗨～ 我是{config['BOT_NAME']}的小助理！\n\n"
                 f"你已加入{config['BOT_NAME']}的专属私域社群 🎉\n\n"
                 f"想了解完整价格和服务？\n"
                 f"发「价格表」给我，所有付费项目一目了然～\n"
                 f"也可以直接 @MorychannelBot 自助下单 🛒\n\n"
                 f"有问题随时问我哦～")
        try:
            bot.send_message(user.id, intro)
        except Exception as e:
            logger.warning(f"私聊发送新人介绍失败 uid={user.id}：{e}")

        logger.info(f"👋 新人欢迎：{user.id} {user.first_name}")


def check_banned_words(bot, m, config: dict, db) -> bool:
    """检查黑名单词，返回True表示消息已处理（删除）"""
    msg = m.text or ""
    for word in config.get("BANNED_WORDS", []):
        if word in msg:
            try:
                bot.delete_message(m.chat.id, m.message_id)
                bot.send_message(m.from_user.id,
                    f"⚠️ 你的消息含有敏感词「{word}」已被删除，请遵守社群规则～")
                _safe_preview = (msg[:50] + "…") if len(msg) > 50 else msg
                _uname = getattr(m.from_user, 'username', None)
                _user_display = m.from_user.first_name or ""
                if _uname:
                    _user_display += f" @{_uname}"
                bot.send_message(config["ADMIN_ID"],
                    f"🚨 用户 {_user_display} "
                    f"触发了敏感词「{word}」\n消息摘要：{_safe_preview}")
            except Exception as e:
                logger.warning(f"删除敏感词消息失败：{e}")
            logger.warning(f"⚠️ 敏感词拦截：uid={m.from_user.id} word={word}")
            return True
    return False


def check_ad_content(bot, m, config: dict, db, ai) -> bool:
    """
    广告检测（v4.5.26新增）— 纯规则匹配，零token消耗
    检测消息内容是否为广告/引流/诈骗/营销
    
    流程：
    1. 硬编码关键词匹配，命中直接处理
    2. 确认广告 → 删除消息 + 永久禁言 + 通知管理员
    
    Returns:
        True表示已处理（删除+禁言），False表示非广告
    """
    msg = (m.text or "").strip()
    if not msg or len(msg) < 5:
        return False
    
    chat_id = m.chat.id
    uid = m.from_user.id
    uname = m.from_user.first_name or ""
    uusername = getattr(m.from_user, 'username', None)
    user_display = uname
    if uusername:
        user_display += f" @{uusername}"
    
    ad_keywords = [
        "加我", "私聊我", "私我", "关注我", "点击链接", "点我", "扫码",
        "赚钱", "日入", "月入", "躺赚", "稳赚", "暴利",
        "兼职", "副业", "刷单", "做任务", "拉人头",
        "免费领", "免费送", "限时优惠", "抢购", "秒杀",
        "微信号", "QQ群", "Telegram群", "群号",
        "http://", "https://", "t.me/", "t.me+",
        "菠菜", "博彩", "赌博", "娱乐城", "真人视讯",
        "贷款", "信用卡", "套现", "代还",
        "代购", "微商", "代理", "加盟",
        "红包", "返利", "佣金", "拉新",
        "推广", "引流", "精准引流", "涨粉",
        "网赚", "网赚项目", "创业项目", "无货源",
        "日结", "周结", "手工活", "手机赚钱",
        "投注", "彩票", "六合彩", "时时彩",
        "裸聊", "约炮", "同城交友", "上门服务",
    ]
    
    hit_kw = None
    msg_lower = msg.lower()
    for kw in ad_keywords:
        if kw.lower() in msg_lower:
            hit_kw = kw
            break
    
    if not hit_kw:
        return False
    
    logger.warning(f"🚫 广告检测命中: {user_display} 关键词={hit_kw}")
    
    try:
        bot.delete_message(chat_id, m.message_id)
    except Exception as e:
        logger.warning(f"删除广告消息失败: {e}")
    
    try:
        bot.restrict_chat_member(
            chat_id, uid,
            until_date=0,
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
        )
        logger.warning(f"🚫 广告用户永久禁言: {user_display}")
    except Exception as e:
        logger.warning(f"禁言广告用户失败: {e}")
    
    admin_id = config.get("ADMIN_ID", 0)
    if admin_id:
        try:
            bot.send_message(admin_id,
                f"🚫 广告已处理\n"
                f"👤 用户：{user_display}\n"
                f"💬 消息：{msg[:150]}{'...' if len(msg) > 150 else ''}\n"
                f"📋 操作：删除消息 + 永久禁言\n"
                f"🎯 命中关键词：{hit_kw}\n"
                f"💡 如误封请手动解禁")
        except Exception as e:
            logger.warning(f"广告通知发送失败: {e}")
    
    return True


def check_spam(bot, m, config: dict, db) -> bool:
    """反刷机制，返回True代表触发刷屏"""
    limit = config.get("SPAM_LIMIT", {})
    msg_limit = limit.get("messages_per_minute", 10)
    ban_min = limit.get("ban_minutes", 5)
    uid = m.from_user.id
    if db.check_spam(uid, msg_limit):
        db.mute_user(uid, m.chat.id, ban_min, "刷屏")
        try:
            from telebot.types import ChatPermissions
            import time
            bot.restrict_chat_member(m.chat.id, uid,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + ban_min * 60)
            bot.send_message(m.chat.id,
                f"⚠️ {m.from_user.first_name} 因刷屏被禁言 {ban_min} 分钟。")
        except Exception as e:
            logger.warning(f"刷屏禁言操作失败 uid={uid}：{e}")
        logger.warning(f"🔇 刷屏禁言：uid={uid}")
        return True
    return False


def handle_left_member(bot, m, config: dict, db=None):
    """流失打捞：用户离群"""
    uid = m.left_chat_member.id
    if uid == _get_bot_id(bot):
        return
    name = m.left_chat_member.first_name or "亲爱的"
    if db:
        db.record_group_left(m.chat.id)  # 【v4.2.3】记录离群统计
    try:
        bot.send_message(uid,
            f"😢 {name}，你真的要走吗？\n\n"
            f"你这样悄悄离开，{config['BOT_NAME']}老板会很伤心的...\n\n"
            f"欢迎随时回来，我会一直在这里等你的～")
        logger.info(f"💌 流失打捞：{uid}")
    except Exception as e:
        logger.warning(f"流失打捞私聊失败 uid={uid}：{e}")


def detect_keywords(msg: str, config: dict) -> dict:
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
    _weather_words = {
        "下雨": "下雨天记得带伞哦，别淋湿了～",
        "暴雨": "暴雨天注意安全，尽量别出门啦！",
        "下雪": "下雪啦！好浪漫，记得穿暖和点～",
        "晴天": "今天天气真好，适合出来走走～",
        "太阳": "大太阳出来啦，注意防晒哦～",
        "台风": "台风天一定要待在室内，安全第一！",
        "降温": "降温了！多穿点，别感冒了～",
        "升温": "天气热起来了，记得多喝水补水哦！",
        "冷": "冷的话多穿点，别逞强冻着自己～",
        "热": "这么热的天，喝杯奶茶降降温吧～",
        "刮风": "风好大，头发都要被吹乱了哈哈～",
        "阴天": "阴天也要保持好心情哦，像老板一样美～",
        "多云": "多云天气刚好，不晒也不冷～",
        "雷": "打雷了！别怕，小助理陪你～",
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
                    result["weather_empathy"] = f"{c}呀？那边的粉丝出来打个招呼～"
                    break

    # AI模式识别
    if any(k in msg for k in ["抽牌", "运势", "占卜", "塔罗"]):
        result["mode"] = "tarot"
    elif any(k in msg for k in ["累", "失恋", "难受", "压力", "崩溃", "心疼"]):
        result["mode"] = "treehole"
    elif "梦到" in msg and ("Mory" in msg or "老板" in msg):
        result["mode"] = "dream"
    elif any(k in msg for k in ["多少钱", "价格", "怎么买", "门槛", "开通", "会员"]):
        result["is_cart"] = True
        result["mode"] = "convert"

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
