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
║    价格/购买  -> 按阶段给预览或自助订阅入口（不直接展示价格表）         ║
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
import time
from io import BytesIO
from datetime import datetime, timezone, timedelta
from core.logging_util import get_logger
from core.keyword_manager import (
    _DEFAULT_TAROT_CARDS,
    _DEFAULT_FORTUNE_TEXTS,
    _DEFAULT_BADGES,
)

_CST = timezone(timedelta(hours=8))

logger = get_logger("content")

# ─────────────────────── 完整22张大阿卡那塔罗牌库 ───────────────────────
# 【重构】默认值已迁移到 core/keyword_manager.py + data/tarot_cards.json
# 此处保留为兼容旧代码的 fallback
TAROT_CARDS = _DEFAULT_TAROT_CARDS

# ─────────────────────── 今日运势签库 ─────────────────────────────────
FORTUNE_TEXTS = _DEFAULT_FORTUNE_TEXTS


def draw_tarot(name: str = "亲爱的") -> str:
    """随机抽取塔罗牌"""
    card_name, card_desc = random.choice(list(TAROT_CARDS.items()))
    return (f"✨ {name} 今天抽到的牌：\n\n"
            f"【{card_name}】\n{card_desc}\n\n"
            f"🔮 别想太多。")


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
            f"✨ 扫完了。你和Mory契合度99.9%。没救了。💫")
        return True

    # 大冒险
    if "大冒险" in msg:
        dares = [
            f"🎲 说一句你最想对Mory说的话。",
            f"🎲 老实交代，手机里存了几张Mory照片？",
            f"🎲 梦到过Mory吗？描述一下。",
            f"🎲 三个词，形容Mory。",
        ]
        mory_bot.reply_and_track(m, random.choice(dares))
        return True

    # Mory密码彩蛋
    if f"{bot_name}密码" in msg or "密码" == msg.strip():
        mory_bot.reply_and_track(m, f"🤫 被你发现了。💋 今天心情还行。")
        return True

    # 碎片寻宝
    puzzle_word = config.get("PUZZLE_WORD", "心动")
    if puzzle_word in msg and m.chat.type != "private":
        score, already_today, consecutive = db.inc_puzzle_score(uid)
        if already_today:
            mory_bot.reply_and_track(m,
                f"👀 今天收过了。\n"
                f"进度：{score}/7（连续{consecutive}天）\n"
                f"凑齐7天领奖励。🎁")
        elif score >= 7:
            mory_bot.reply_and_track(m,
                f"🎉 连续{consecutive}天集齐了。\n"
                f"私聊我领奖励。🎁\n"
                f"（进度重置，下一轮开始。）")
        else:
            mory_bot.reply_and_track(m,
                f"🔍 找到暗号碎片。\n"
                f"进度：{score}/7（连续{consecutive}天）\n"
                f"每天说「{puzzle_word}」收一次。")
        return False  # 不消费，允许AI继续正常回复

    # 叫醒服务注册
    if msg.startswith("/叫醒 "):
        parts = msg.split(" ")
        if len(parts) >= 2:
            wake_time = parts[1]
            if ":" in wake_time and len(wake_time) == 5:
                db.set_wake_up(uid, wake_time)
                mory_bot.reply_and_track(m,
                    f"⏰ 记下了。每天{wake_time}叫你。")
                return True
        mory_bot.reply_and_track(m, "⚠️ 格式：/叫醒 08:30")
        return True

    # 价格/购买入口：在 P8 早返回阶段也必须遵守 ReplyContract v1。
    if msg.strip() in ("价格表", "价格", "多少钱", "怎么买", "门槛"):
        from core.growth_optimizer import resolve_conversion_target

        target, _ = resolve_conversion_target(msg, mode="convert")
        if target == "subscribe":
            reply = (
                "想继续的话去 @MorychannelBot 看当前可选内容和档位，"
                "按提示自助完成。"
            )
        else:
            reply = "想先了解的话可以去 @moryselect 看预览，没写清楚的再问我呀。"
        mory_bot.reply_and_track(m, reply)
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
            mory_bot.reply_and_track(m, "🌱 新人，多说话攒积分。")
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
    # [TRAE SOLO CN] 安全修复：不再将 Token 拼入 URL（防止异常日志泄露 Token）
    try:
        file_info = bot.get_file(m.photo[-1].file_id)
        try:
            img_bytes = bot.download_file(file_info.file_path)
        except Exception:
            # 二次重试 download_file，避免将 Token 拼入 URL 导致泄露风险
            try:
                img_bytes = bot.download_file(file_info.file_path)
            except Exception as dl_err:
                logger.error(f"图片下载失败（重试后）: {dl_err}")
                return
    except Exception as e:
        logger.error(f"图片下载失败：{e}")
        return

    # 管理员：打码推群
    if is_admin:
        _handle_admin_photo(bot, m, config, img_bytes, mory_bot)
        return

    # 普通用户：AI识图撩人回复
    if ai and config.get("ENABLE_VISION_REPLY", False):
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

        text = "想先看看？去 @moryselect 看预览"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        x = (img.width - tw) / 2
        y = img.height / 2
        draw.text((x, y), text, fill=(255, 255, 255, 170), font=font)

        watermarked = Image.alpha_composite(img, overlay).convert("RGB")
        bio = BytesIO()
        watermarked.save(bio, "JPEG", quality=88)
        bio.seek(0)

        bot.send_photo(
            gid,
            bio,
            caption="想先了解的话可以去 @moryselect 看预览，没写清楚的再问我呀。",
        )
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
    uname = m.from_user.first_name or "你"
    cid = m.chat.id
    
    # 随机概率触发（避免每张图都分析，节省token）
    if random.random() > config.get("VISION_REPLY_RATE", 0.3):
        logger.debug(f"👁️ 图片识图随机跳过: uid={uid}")
        return
    
    # AI识图prompt
    prompt = f"""你是Mory，嘴硬心软，有点傲娇。

用户「{uname}」在群里发了一张照片，评价这张照片，可以调侃、吐槽、偶尔夸一句，不要撒娇卖萌。

要求：
1. 30-60字，自然像朋友说话
2. 根据照片内容具体评价（不要泛泛而谈）
3. 可以调侃、吐槽、偶尔夸一句
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
# 【重构】默认值已迁移到 core/keyword_manager.py + data/badges.json
BADGES = _DEFAULT_BADGES


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
