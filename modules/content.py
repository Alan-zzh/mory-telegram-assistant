"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/content.py  ·  内容彩蛋模块                                  ║
║                                                                        ║
║  功能：所有不需要调用AI的快速响应内容。                                ║
║                                                                        ║
║  塔罗牌库：22张大阿卡那卡牌（愚人-世界），每张有专属解读。              ║
║  运势签库：10条简短运势签，随机抽取。                                   ║
║                                                                        ║
║  彩蛋触发（handle_easter_eggs）：                                      ║
║    "契合度"  -> 星盘扫描彩蛋                                           ║
║    "大冒险"  -> 随机大冒险任务                                          ║
║    "Mory密码" -> 专属飞吻彩蛋                                           ║
║    碎片寻宝  -> 群聊触发暗号攒积分，7次领奖励                          ║
║    /叫醒 HH:MM -> 注册每日叫醒服务                                     ║
║    价格表     -> 显示会员价格（同时触发购物车+转化漏斗）                ║
║    我的等级   -> 查看个人积分和等级                                     ║
║                                                                        ║
║  图片打码（handle_photo）：                                            ║
║    管理员发图片 -> 自动加半透明水印 -> 推送到主群                       ║
║    需要 Pillow 库 + VPS有中文字体                                      ║
║                                                                        ║
║  生物钟（is_late_night）：凌晨0-5点，教育粉丝去睡觉                     ║
║                                                                        ║
║  被调用：main.py -> P8彩蛋响应 + 图片处理器                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import random
import logging
import time
import requests
from io import BytesIO
from datetime import datetime, timezone, timedelta
from core.logging_util import get_logger

logger = get_logger("content")

# ─────────────────────── 完整22张大阿卡那塔罗牌库 ───────────────────────
TAROT_CARDS = {
    "愚人":     "❌ 鲁莽的新开始。今天要三思而后行。",
    "魔术师":   "✨ 掌握主动权的日子。该出手就出手。",
    "女祭司":   "🔮 神秘而深邃。今天会有惊喜发现。",
    "皇帝":     "👑 权力与掌控。你今天有主宰感。",
    "皇后":     "👸 优雅而富有。这是收获的预兆。",
    "教皇":     "⛪ 精神升华。修身养性的好时机。",
    "恋人":     "💕 二选一的困局，但无论选什么都是对的。",
    "战车":     "🏃 飞快前进。不要踩刹车。",
    "力量":     "💪 内在磨练成果。你比想象中更强大。",
    "隐士":     "🕯️ 沉默与思考的周期。充电时刻到了。",
    "命运之轮": "♻️ 轮回与变化。运气随时可能转向。",
    "正义":     "⚖️ 公平与因果。该来的都会来。",
    "倒吊人":   "🙃 换个角度看世界。困境即机遇。",
    "死神":     "💀 结束与开始的交界。不是坏事，是蜕变。",
    "节制":     "🌊 平衡与和谐。温和的力量最强大。",
    "恶魔":     "😈 欲望的引诱。要分辨真心与迷恋。",
    "塔":       "⚡ 突如其来的变故。改变后会更好。",
    "星星":     "⭐ 希望与憧憬。梦想就在不远处。",
    "月亮":     "🌙 直觉与潜意识。听从内心的声音。",
    "太阳":     "☀️ 光明与喜悦。好运马上就来。",
    "审判":     "📯 觉醒与重生。你将成为新的自己。",
    "世界":     "🌍 完成与圆满。一个完美的结局。",
}

# ─────────────────────── 今日运势签库 ─────────────────────────────────
FORTUNE_TEXTS = [
    "今日宜大胆，运气偏爱勇者。",
    "桃花暗涌，保持神秘感最迷人。",
    "财运流动，注意把握时机。",
    "贵人就在身边，多表达感谢。",
    "直觉比逻辑更准，相信自己。",
    "今天适合说出那句话。",
    "低调行事，暗中积累能量。",
    "一切顺遂，今日宜主动出击。",
    "静待花开，着急没有用。",
    "好事将至，耐心是你的武器。",
]


def draw_tarot(name: str = "亲爱的") -> str:
    """随机抽取塔罗牌"""
    card_name, card_desc = random.choice(list(TAROT_CARDS.items()))
    return (f"✨ {name} 的今日运势卡牌是：\n\n"
            f"【{card_name}】\n{card_desc}\n\n"
            f"🔮 记住：命运掌握在自己手中，牌只是镜子。")


def get_fortune() -> str:
    """随机运势签"""
    return random.choice(FORTUNE_TEXTS)


# ─────────────────────── 彩蛋快速响应 ─────────────────────────────────
def handle_easter_eggs(mory_bot, m, config: dict, db) -> bool:
    """
    处理固定彩蛋（不需要AI，立刻响应）。
    返回True表示已消费，主分发器不再处理。
    """
    msg = m.text or ""
    uid = m.from_user.id
    name = m.from_user.first_name or "亲爱的"
    bot_name = config.get("BOT_NAME", "Mory")

    # 契合度测试
    if "契合度" in msg:
        mory_bot.reply_and_track(m,
            f"✨ 星盘扫描中...\n\n"
            f"结论：你的灵魂和 {bot_name} 老板契合度高达 **99.9%**！\n"
            f"你简直就是为她量身定制的守护者！💫")
        return True

    # 大冒险
    if "大冒险" in msg:
        dares = [
            f"🎲 请在群里发一句对{bot_name}老板最深情的告白！",
            f"🎲 说出你手机里存了{bot_name}老板几张照片？",
            f"🎲 描述一下你梦里的{bot_name}老板是什么样的？",
            f"🎲 用3个词形容你眼中的{bot_name}老板！",
        ]
        mory_bot.reply_and_track(m, random.choice(dares))
        return True

    # Mory密码彩蛋
    if f"{bot_name}密码" in msg or "密码" == msg.strip():
        mory_bot.reply_and_track(m, f"🤫 嘘... 奖励你一个专属飞吻 💋\n悄悄告诉你，{bot_name}老板今天心情特别好哦～")
        return True

    # 碎片寻宝
    puzzle_word = config.get("PUZZLE_WORD", "心动")
    if puzzle_word in msg and m.chat.type != "private":
        score, already_today, consecutive = db.inc_puzzle_score(uid)
        if already_today:
            mory_bot.reply_and_track(m,
                f"👀 你今天已经收集过暗号了～\n"
                f"当前进度：{score}/7（连续{consecutive}天）\n"
                f"坚持每天来一次，凑齐7天就能领盲盒奖励哦！🎁")
        elif score >= 7:
            mory_bot.reply_and_track(m,
                f"🎉 恭喜你连续{consecutive}天收集齐了暗号！\n"
                f"快去私聊{bot_name}老板领专属盲盒奖励吧～ 🎁\n"
                f"（进度已重置，可以重新开始新一轮收集～）")
        else:
            mory_bot.reply_and_track(m,
                f"🔍 发现暗号碎片！今日收集成功～\n"
                f"当前进度：{score}/7（已连续{consecutive}天）\n"
                f"每天在群里提到「{puzzle_word}」即可收集一次～")
        return False  # 不消费，允许AI继续正常回复

    # 叫醒服务注册
    if msg.startswith("/叫醒 "):
        parts = msg.split(" ")
        if len(parts) >= 2:
            wake_time = parts[1]
            if ":" in wake_time and len(wake_time) == 5:
                db.set_wake_up(uid, wake_time)
                mory_bot.reply_and_track(m,
                    f"⏰ 记下啦～ 以后每天 {wake_time} "
                    f"小助理会准时叫你起床哦！好好休息～")
                return True
        mory_bot.reply_and_track(m, "⚠️ 格式：/叫醒 08:30")
        return True

    # 价格表查询
    if msg.strip() in ("价格表", "价格", "多少钱", "怎么买"):
        price_list = config.get("PRICE_LIST", {})
        lines = [
            "💎 Mory 付费服务一览\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📥 付费订阅（完整版内容）\n"
        ]
        # 付费订阅类
        sub_items = ["至臻精选", "至臻全享", "精选图集"]
        for item in sub_items:
            info = price_list.get(item, {})
            if not info:
                continue
            details = []
            if "monthly" in info:
                details.append(f"月付¥{info['monthly']}")
            if "quarterly" in info:
                details.append(f"季付¥{info['quarterly']}")
            if "yearly" in info:
                details.append(f"年付¥{info['yearly']}")
            price_str = " / ".join(details)
            note = info.get("note", "")
            lines.append(f"  ✨ {item}：{price_str}")
            if note:
                lines.append(f"     {note}")

        lines.append("\n💌 社交解锁")
        social_items = ["社交解锁1阶", "社交解锁2阶", "社交解锁3阶"]
        social_desc = ["加QQ/TG，1v1聊天，解锁定制/原味/寄拍权限",
                       "私人微信朋友圈，更新最真的日常，私密感拉满",
                       "线下见面资格，支持视频验证，确保真人"]
        for i, item in enumerate(social_items):
            info = price_list.get(item, {})
            if info:
                desc = social_desc[i] if i < len(social_desc) else ""
                lines.append(f"  {i+1}⃣ ¥{info['price']} | {desc}")

        lines.append("\n🎬 独家定制（@MorychannelBot自助下单）")
        custom_items = ["不露脸软核定制", "深度剧本演绎", "极致互动狙击"]
        custom_desc = ["5分钟，指定服装/台词/动作，只要你想我就演绎",
                       "10分钟，全剧本角色扮演，灵魂演技全场景",
                       "15分钟，精准狙击XP，非会员不下单"]
        for i, item in enumerate(custom_items):
            info = price_list.get(item, {})
            if info:
                lines.append(f"  ¥{info['price']} | {custom_desc[i]}")

        lines.append("\n👕 原味套餐（@MorychannelBot自助下单）")
        orig_items = ["原味-贴身袜类", "原味-私密内裤", "原味-深度袜类",
                      "原味-撕裂套装", "原味-精选内裤", "原味-运动Bra", "原味-私藏旧鞋"]
        orig_desc = ["船袜/短袜/丝袜任选，穿戴1天",
                     "私密内裤，穿戴1天，保留最真实体味",
                     "连续穿戴3天，多穿一天+20r，支持天数定制",
                     "连体袜/袜套装，含撕裂全过程视频",
                     "蕾丝/丁字裤任选，穿戴2天，支持经期特供+拍摄视频",
                     "运动出汗后直接打包，最纯正运动汗味",
                     "高跟鞋/球鞋长期穿戴，老粉丝首选"]
        for i, item in enumerate(orig_items):
            info = price_list.get(item, {})
            if info:
                lines.append(f"  {i+1}⃣ ¥{info['price']} | {orig_desc[i]}")

        lines.append("\n━━━━━━━━━━━━━━━━━━")
        lines.append("@MorychannelBot 自助下单 | 联系小助理咨询")
        lines.append("未成年禁入 | 理智消费")

        mory_bot.reply_and_track(m, "\n".join(lines))
        db.set_cart(uid)
        db.log_conversion_event(uid, "interested")
        return True

    # 我的等级查询
    if msg.strip() in ("我的等级", "/level"):
        # 【修复】直接查用户积分，不再依赖排行榜前100名限制
        level_names = {1: "新人🌱", 2: "活跃⭐", 3: "VIP💎", 4: "至尊👑"}
        pts = db.get_user_points(uid)
        if pts is not None:
            level = 1
            if pts >= 500: level = 4
            elif pts >= 100: level = 3
            elif pts >= 20: level = 2
            mory_bot.reply_and_track(m,
                f"🎖 你的当前等级：{level_names.get(level, '新人')}\n"
                f"积分：{pts} 分\n\n"
                f"发言+1分 | 购买+10分 | 邀请+5分")
        else:
            mory_bot.reply_and_track(m, "🌱 你还是新人，多发言积累积分吧～")
        return True

    return False


# ─────────────────────── 图片处理（打码+识图） ─────────────────────────────
def handle_photo(bot, m, config: dict, mory_bot=None, ai=None):
    """
    【v4.3.0重构】图片处理：
    - 管理员发图片 → 打码推群
    - 普通用户发图片 → AI识图撩人回复
    """
    uid = m.from_user.id
    is_admin = uid == config["ADMIN_ID"]

    # 获取图片数据（通用）
    try:
        file_info = bot.get_file(m.photo[-1].file_id)
        try:
            img_bytes = bot.download_file(file_info.file_path)
        except Exception:
            img_bytes = requests.get(
                f"https://api.telegram.org/file/bot{config['TOKEN']}/{file_info.file_path}"
            ).content
    except Exception as e:
        logger.error(f"图片下载失败：{e}")
        return

    # 管理员：打码推群
    if is_admin:
        _handle_admin_photo(bot, m, config, img_bytes, mory_bot)
        return

    # 普通用户：AI识图撩人回复
    if ai and config.get("ENABLE_VISION_REPLY", True):
        _handle_user_photo_vision(bot, m, config, img_bytes, ai)


def _handle_admin_photo(bot, m, config: dict, img_bytes: bytes, mory_bot):
    """管理员图片 → 打码推群"""
    gid = config.get("GROUP_ID", 0)
    if gid == 0:
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(BytesIO(img_bytes)).convert("RGBA")

        # 半透明水印层
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        
        # 字体加载多级兜底
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                                      int(img.width / 15))
        except OSError:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                          int(img.width / 15))
            except OSError:
                try:
                    font = ImageFont.truetype("arial.ttf", int(img.width / 15))
                except OSError:
                    font = ImageFont.load_default()

        text = "🔒 订阅解锁完整版 @MorychannelBot"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (img.width - tw) / 2
        y = img.height / 2
        draw.text((x, y), text, fill=(255, 255, 255, 170), font=font)

        watermarked = Image.alpha_composite(img, overlay).convert("RGB")
        bio = BytesIO()
        watermarked.save(bio, "JPEG", quality=88)
        bio.seek(0)

        bot.send_photo(gid, bio,
                       caption=f"{config['BOT_NAME']}老板发新图啦～ 想看无遮挡版？你懂的～ 🔥")
        mory_bot.reply_and_track(m, "✅ 打码完成并已推群")
        logger.info("📸 图片打码推群成功")

    except Exception as e:
        logger.error(f"图片打码失败：{e}")
        mory_bot.reply_and_track(m, f"⚠️ 图像处理失败：{str(e)[:60]}")


def _handle_user_photo_vision(bot, m, config: dict, img_bytes: bytes, ai):
    """
    【v4.3.0新增】用户图片 → AI识图撩人回复
    
    让Mory能"看懂"用户发的照片，并给出走心的撩人评论
    """
    from core.ai_engine import analyze_image
    
    uid = m.from_user.id
    uname = m.from_user.first_name or "哥哥"
    cid = m.chat.id
    
    # 随机概率触发（避免每张图都分析，节省token）
    if random.random() > config.get("VISION_REPLY_RATE", 0.3):
        logger.debug(f"👁️ 图片识图随机跳过: uid={uid}")
        return
    
    # AI识图prompt
    prompt = f"""你是Mory老板，一个可爱又有点小色色的闺蜜。

用户「{uname}」在群里发了一张照片，请用傲娇又撩人的语气评价这张照片。

要求：
1. 30-60字，像闺蜜私聊一样自然
2. 根据照片内容具体评价（不要泛泛而谈）
3. 可以调侃、撩人、吃醋、羡慕等情绪
4. 结尾要有emoji
5. 绝对不要提"AI"、"识别"、"分析"等字眼
6. 不要重复相同的开头

【图片】：用户发的照片"""
    
    try:
        # 调用AI识图
        analysis = analyze_image(img_bytes, prompt, config)
        
        if analysis and len(analysis) > 5:
            # 根据回复长度计算typing延迟
            from core.ai_engine import calc_typing_delay
            delay = calc_typing_delay(analysis)
            
            # 显示typing状态
            bot.send_chat_action(cid, "typing")
            time.sleep(delay)
            
            # 发送AI回复
            bot.reply_to(m, analysis)
            logger.info(f"👁️ AI识图回复成功: uid={uid}")
        else:
            logger.debug(f"👁️ AI识图返回为空，跳过")
            
    except Exception as e:
        logger.error(f"👁️ AI识图失败: {e}")


# ─────────────────────── 生物钟警告 ──────────────────────────────────
def is_late_night() -> bool:
    """凌晨0-5点（强制使用北京时间，避免VPS时区偏差）"""
    cst = timezone(timedelta(hours=8))
    h = datetime.now(cst).hour
    return 0 <= h < 5


# ═══════════════════════════════════════════════════════════════════════════
# 【v4.3.0新增】活跃勋章系统
# ═══════════════════════════════════════════════════════════════════════════

# 勋章定义
BADGES = {
    # 活跃类勋章
    "early_bird": {"name": "早起鸟", "emoji": "🐦", "desc": "每天8点前发消息"},
    "night_owl": {"name": "夜猫子", "emoji": "🦉", "desc": "每天23点后发消息"},
    "social_butterfly": {"name": "社牛", "emoji": "🦋", "desc": "群消息超过100条"},
    "chatty_cathy": {"name": "话痨", "emoji": "💬", "desc": "单日消息超过50条"},
    
    # 互动类勋章
    "first_fan": {"name": "铁粉", "emoji": "❤️", "desc": "连续7天活跃"},
    "super_fan": {"name": "超级铁粉", "emoji": "💖", "desc": "连续30天活跃"},
    "og_member": {"name": "OG会员", "emoji": "👑", "desc": "加入超过30天"},
    
    # 特殊类勋章
    "treasure_hunter": {"name": "寻宝达人", "emoji": "💎", "desc": "碎片寻宝满7天"},
    "tarot_master": {"name": "塔罗师", "emoji": "🔮", "desc": "查看运势超过10次"},
    "lucky_star": {"name": "幸运星", "emoji": "⭐", "desc": "被随机点名3次"},
    
    # 消费类勋章
    "early_adopter": {"name": "尝鲜客", "emoji": "🚀", "desc": "首日体验会员"},
    "loyal_customer": {"name": "老会员", "emoji": "💎", "desc": "连续付费超过3个月"},
}


def check_and_award_badges(uid: int, db, msg_count_today: int = 0) -> list:
    """
    【v4.3.0新增】检查并授予用户勋章
    
    Args:
        uid: 用户ID
        db: 数据库管理器
        msg_count_today: 今日消息数（可选）
    
    Returns:
        新获得的勋章列表（用于播报）
    """
    new_badges = []
    now = datetime.now(_CST)
    hour = now.hour
    
    # 早起鸟：8点前发消息
    if hour < 8:
        if db.earn_badge(uid, "early_bird"):
            new_badges.append("early_bird")
    
    # 夜猫子：23点后发消息
    if hour >= 23:
        if db.earn_badge(uid, "night_owl"):
            new_badges.append("night_owl")
    
    # 话痨：单日消息超过50条
    if msg_count_today > 50:
        if db.earn_badge(uid, "chatty_cathy"):
            new_badges.append("chatty_cathy")
    
    # 社牛：群消息超过100条
    if msg_count_today > 100:
        if db.earn_badge(uid, "social_butterfly"):
            new_badges.append("social_butterfly")
    
    return new_badges


def format_badges_display(badges: list) -> str:
    """格式化勋章展示"""
    if not badges:
        return ""
    
    lines = ["🏅 你的勋章墙："]
    for badge_id, earned_at in badges:
        badge = BADGES.get(badge_id, {})
        emoji = badge.get("emoji", "🏅")
        name = badge.get("name", badge_id)
        lines.append(f"  {emoji} {name}")
    
    return "\n".join(lines)


def get_badge_summary_text(db, uid: int) -> str:
    """获取用户勋章汇总（用于/我的等级等命令）"""
    badges = db.get_user_badges(uid)
    
    if not badges:
        return "🏅 你还没有获得任何勋章，继续活跃吧！"
    
    lines = ["🏅 你的勋章墙："]
    for badge_id, earned_at in badges[:5]:  # 最多显示5个
        badge = BADGES.get(badge_id, {})
        emoji = badge.get("emoji", "🏅")
        name = badge.get("name", badge_id)
        lines.append(f"  {emoji} {name}")
    
    if len(badges) > 5:
        lines.append(f"\n...还有 {len(badges) - 5} 个勋章，发送「我的勋章」查看全部")
    
    return "\n".join(lines)
