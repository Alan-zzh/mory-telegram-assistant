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


# ─────────────────────── 图片打码推送 ─────────────────────────────────
def handle_photo(bot, m, config: dict):
    """老板发图片→自动打水印→推群"""
    if m.from_user.id != config["ADMIN_ID"]:
        return
    gid = config.get("GROUP_ID", 0)
    if gid == 0:
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
        file_info = bot.get_file(m.photo[-1].file_id)
        # 用 telebot 内置下载方法，避免 token 暴露在 URL 中
        try:
            img_bytes = bot.download_file(file_info.file_path)
        except Exception:
            # 降级：旧版兼容（某些 telebot 版本不支持 download_file）
            img_bytes = requests.get(
                f"https://api.telegram.org/file/bot{config['TOKEN']}/{file_info.file_path}"
            ).content
        img = Image.open(BytesIO(img_bytes)).convert("RGBA")

        # 半透明水印层
        overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        # 【v4.0 修复】字体加载添加多级兜底，防止跨平台崩溃
        try:
            # 优先用中文字体（Linux）
            font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                                      int(img.width / 15))
        except OSError:
            try:
                # 尝试 Linux 常见字体
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                                          int(img.width / 15))
            except OSError:
                try:
                    # 尝试 Windows 常见字体
                    font = ImageFont.truetype("arial.ttf", int(img.width / 15))
                except OSError:
                    logger.warning("⚠️ 实体字体加载失败，强制使用内存默认字体 (打码样式可能较简陋)")
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


# ─────────────────────── 生物钟警告 ──────────────────────────────────
def is_late_night() -> bool:
    """凌晨0-5点（强制使用北京时间，避免VPS时区偏差）"""
    cst = timezone(timedelta(hours=8))
    h = datetime.now(cst).hour
    return 0 <= h < 5
