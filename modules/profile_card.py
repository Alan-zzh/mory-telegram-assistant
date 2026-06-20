"""
modules/profile_card.py · 用户资料卡

功能：
  handle_profile_card(bot, m, config, db) - 生成并展示用户资料卡

命令：
  我的 / 资料卡         → 查看自己的资料卡
  资料卡 @用户          → 查看他人的资料卡
  回复某人消息+资料卡    → 查看被回复者的资料卡

数据表：
  user_levels     → level, points
  checkin_records → MAX(continuous_days), COUNT(*)
  achievements    → COUNT(*)
  users           → name, group_messages
  speech_daily    → SUM(count)
"""

import os
import time
import tempfile
from datetime import datetime, timezone, timedelta
from core.logging_util import get_logger

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

_CST = timezone(timedelta(hours=8))
logger = get_logger("profile_card")

# 等级称号映射（config中的LEVEL_TITLES优先，此为默认回退）
_DEFAULT_LEVEL_TITLES = {"1": "萌新", "2": "常客", "3": "达人", "4": "大佬"}

# 成就定义总数（与achievement模块的ACHIEVEMENT_DEFS保持一致）
_TOTAL_ACHIEVEMENTS = 12


def _get_level_title(level: int, config: dict) -> str:
    """获取等级称号，优先从config读取，回退到默认"""
    titles = config.get("LEVEL_TITLES", _DEFAULT_LEVEL_TITLES)
    return titles.get(str(level), _DEFAULT_LEVEL_TITLES.get(str(level), "未知"))


def _fetch_profile_data(db, uid: int) -> dict:
    """从数据库查询用户资料卡所需的全部数据"""
    data = {
        "name": f"用户{uid}",
        "level": 1,
        "points": 0,
        "max_continuous": 0,
        "total_checkins": 0,
        "achievement_count": 0,
        "group_messages": 0,
        "rank": 0,
        "month_speech": 0,
        "active_time": "未知",
    }

    # 用户名 + 群消息数
    row = db.conn.execute(
        "SELECT name, group_messages FROM users WHERE uid=?", (uid,)
    ).fetchone()
    if row:
        data["name"] = row[0] or f"用户{uid}"
        data["group_messages"] = row[1] or 0

    # 等级 + 积分
    row = db.conn.execute(
        "SELECT level, points FROM user_levels WHERE uid=?", (uid,)
    ).fetchone()
    if row:
        data["level"] = row[0] or 1
        data["points"] = row[1] or 0

    # 签到：最大连续天数 + 总签到次数
    row = db.conn.execute(
        "SELECT MAX(continuous_days), COUNT(*) FROM checkin_records WHERE uid=?",
        (uid,)
    ).fetchone()
    if row:
        data["max_continuous"] = row[0] or 0
        data["total_checkins"] = row[1] or 0

    # 成就数
    row = db.conn.execute(
        "SELECT COUNT(*) FROM achievements WHERE uid=?", (uid,)
    ).fetchone()
    if row:
        data["achievement_count"] = row[0] or 0

    # 积分排名：比该用户积分高的人数 + 1
    row = db.conn.execute(
        "SELECT COUNT(*)+1 FROM user_levels WHERE points > (SELECT points FROM user_levels WHERE uid=?)",
        (uid,)
    ).fetchone()
    if row:
        data["rank"] = row[0]

    # 本月发言数
    month_prefix = datetime.now(_CST).strftime("%Y-%m")
    row = db.conn.execute(
        "SELECT SUM(count) FROM speech_daily WHERE uid=? AND date LIKE ?",
        (uid, f"{month_prefix}%")
    ).fetchone()
    if row and row[0]:
        data["month_speech"] = row[0]

    # 活跃时段（基于最后活跃时间）
    row = db.conn.execute(
        "SELECT last_active FROM users WHERE uid=?", (uid,)
    ).fetchone()
    if row and row[0]:
        hour = datetime.fromtimestamp(row[0], _CST).hour
        if 0 <= hour < 6:
            data["active_time"] = "深夜活跃"
        elif 6 <= hour < 12:
            data["active_time"] = "上午活跃"
        elif 12 <= hour < 18:
            data["active_time"] = "下午活跃"
        else:
            data["active_time"] = "晚间活跃"

    return data


def _build_text_card(data: dict, config: dict) -> str:
    """构建文本格式资料卡（Pillow不可用时的回退方案）"""
    title = _get_level_title(data["level"], config)
    lines = [
        f"📋 <b>{data['name']}</b> 的资料卡",
        "",
        f"🏷 等级：Lv{data['level']} {title}",
        f"💎 积分：{data['points']}",
        f"📅 签到：连续{data['max_continuous']}天（共{data['total_checkins']}次）",
        f"🎖 成就：{data['achievement_count']}/{_TOTAL_ACHIEVEMENTS}个",
        f"🏆 排名：第{data['rank']}名",
        f"💬 发言：{data['group_messages']}条（本月{data['month_speech']}条）",
        f"🕐 活跃时段：{data['active_time']}",
    ]
    return "\n".join(lines)


def _build_image_card(data: dict, config: dict, db=None) -> object:
    """生成图片格式资料卡（600x400）"""
    width, height = 600, 400
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # 渐变背景：#2C3E50 → #3498DB
    r1, g1, b1 = 0x2C, 0x3E, 0x50
    r2, g2, b2 = 0x34, 0x98, 0xDB
    for y in range(height):
        ratio = y / height
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 加载字体
    try:
        font_title = ImageFont.truetype("msyh.ttc", 32)
        font_large = ImageFont.truetype("msyh.ttc", 24)
        font_medium = ImageFont.truetype("msyh.ttc", 18)
        font_small = ImageFont.truetype("msyh.ttc", 14)
    except Exception:
        try:
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_large = ImageFont.truetype("arial.ttf", 24)
            font_medium = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font_title = ImageFont.load_default()
            font_large = font_title
            font_medium = font_title
            font_small = font_title

    # ── 顶部区域：用户名 + 等级徽章 ──
    title = _get_level_title(data["level"], config)
    draw.text((30, 25), data["name"], fill="white", font=font_title)

    # 等级徽章（金色圆角矩形）
    badge_text = f"Lv{data['level']} {title}"
    badge_x = 30
    badge_y = 70
    bbox = draw.textbbox((0, 0), badge_text, font=font_medium)
    badge_w = bbox[2] - bbox[0] + 20
    badge_h = bbox[3] - bbox[1] + 10
    draw.rounded_rectangle(
        [(badge_x, badge_y), (badge_x + badge_w, badge_y + badge_h)],
        radius=8,
        fill=(241, 196, 15)
    )
    draw.text((badge_x + 10, badge_y + 3), badge_text, fill=(44, 62, 80), font=font_medium)

    # ── 中部区域：数据网格（2列3行）──
    grid_items = [
        ("💎 积分", str(data["points"])),
        ("📅 签到", f"连续{data['max_continuous']}天"),
        ("🎖 成就", f"{data['achievement_count']}/{_TOTAL_ACHIEVEMENTS}个"),
        ("🏆 排名", f"第{data['rank']}名"),
        ("🏷 等级", f"Lv{data['level']} {title}"),
        ("💬 发言", f"{data['group_messages']}条"),
    ]

    col_w = 270
    row_h = 50
    start_y = 115
    for i, (label, value) in enumerate(grid_items):
        col = i % 2
        row = i // 2
        x = 30 + col * col_w
        y = start_y + row * row_h
        # 标签（浅色）
        draw.text((x, y), label, fill=(189, 195, 199), font=font_medium)
        # 值（白色，大字）
        draw.text((x, y + 22), value, fill="white", font=font_large)

    # ── 底部区域：成就图标行 ──
    # 从achievement模块获取成就定义（避免循环导入，只读取数据库）
    unlocked_ids = set()
    if db is not None:
        try:
            rows = db.conn.execute(
                "SELECT achievement_id FROM achievements WHERE uid=?",
                (data.get("_uid", 0),)
            ).fetchall()
            unlocked_ids = {row[0] for row in rows}
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # 成就图标定义（与achievement模块保持一致）
    achievement_icons = [
        ("first_checkin", "🌱"), ("checkin_7d", "🔥"), ("checkin_15d", "💪"),
        ("checkin_30d", "⭐"), ("points_100", "💰"), ("points_500", "💎"),
        ("speech_100", "🗣️"), ("speech_1000", "🎤"), ("invite_3", "🤝"),
        ("blindbox_10", "🎲"), ("tip_5", "💝"), ("wheel_10", "🎡"),
    ]

    icon_y = 310
    icon_x = 30
    for aid, icon in achievement_icons:
        if aid in unlocked_ids:
            # 已解锁：正常显示
            draw.text((icon_x, icon_y), icon, fill="white", font=font_large)
        else:
            # 未解锁：灰色显示
            draw.text((icon_x, icon_y), icon, fill=(100, 100, 100), font=font_large)
        icon_x += 46

    # 底部活跃时段
    draw.text((30, 365), f"🕐 活跃时段：{data['active_time']}", fill=(189, 195, 199), font=font_small)

    return img


def handle_profile_card(bot, m, config, db):
    """处理资料卡命令：我的 / 资料卡 / 资料卡 @用户 / 回复消息+资料卡"""
    # 确定目标用户
    uid = m.from_user.id

    # 优先级：回复消息 > @提及 > 自己
    if m.reply_to_message and m.reply_to_message.from_user:
        uid = m.reply_to_message.from_user.id
    elif hasattr(m, "entities") and m.entities:
        for entity in m.entities:
            if entity.type == "mention":
                # 提及用户时尝试从文本解析（Telegram Bot API限制，无法直接获取uid）
                # 这种情况下只能显示自己的卡片
                break
            elif entity.type == "text_mention" and entity.user:
                uid = entity.user.id
                break

    try:
        data = _fetch_profile_data(db, uid)
        data["_uid"] = uid  # 供图片生成时查询成就用

        if _HAS_PIL:
            # 生成图片资料卡
            img = _build_image_card(data, config, db=db)
            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                img.save(tmp_path, "PNG")
                with open(tmp_path, "rb") as f:
                    bot.send_photo(m.chat.id, f, reply_to_message_id=m.message_id)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        else:
            # 回退到文本格式
            text = _build_text_card(data, config)
            bot.reply_to(m, text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"资料卡生成异常: uid={uid} err={e}")
        bot.reply_to(m, "❌ 资料卡生成失败，请稍后再试")
