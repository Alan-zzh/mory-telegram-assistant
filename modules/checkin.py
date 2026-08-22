"""
签到系统 - 每日签到 + 连续签到奖励 + 签到排行 + 补签 + 签到日历 + 签到卡片

功能：
  1. 每日签到获取基础积分
  2. 连续签到天数达标额外奖励（3/7/15/30天）
  3. 签到排行榜（连续天数TOP10）
  4. 补签（消耗积分补昨日签到）
  5. 签到日历（当月签到状态一览）
  6. 签到卡片（生成图片卡片）

命令：
  签到 / checkin → handle_checkin
  签到排行 → handle_checkin_rank
  补签 → handle_makeup_checkin
  签到日历 → handle_checkin_calendar

数据表：checkin_records（uid, date, continuous_days, points_earned, ts）
"""
import os
import random
import tempfile
import time
from datetime import datetime, timedelta, timezone

from core.helpers import can_delete_message
from core.database import _db_lock
from core.logging_util import get_logger
from modules.points_enhanced import check_level_up

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

logger = get_logger("checkin")

# 北京时间
_CST = timezone(timedelta(hours=8))


def _get_scheduler():
    """获取APScheduler实例"""
    try:
        from tasks.task_scheduler import get_scheduler_instance
        return get_scheduler_instance()
    except Exception:
        return None


def _schedule_delete_message(bot, chat_id, message_id, delay=60, config=None):
    """延迟删除消息（受ENABLE_MESSAGE_DELETION控制）"""
    if config and not can_delete_message(config):
        return

    scheduler = _get_scheduler()
    if scheduler:
        try:
            run_at = datetime.now(_CST) + timedelta(seconds=delay)
            scheduler.add_job(
                _do_delete_message, trigger='date', run_date=run_at,
                args=[bot, chat_id, message_id, config],
                id=f"checkin_del_{chat_id}_{message_id}",
                max_instances=1, misfire_grace_time=10,
                replace_existing=False,
            )
            logger.info(f"🗑️ 签到消息已预约删除: chat={chat_id}, msg={message_id}, 延迟{delay}秒")
        except Exception as e:
            logger.warning(f"签到消息定时删除调度失败: {e}")


def _do_delete_message(bot, chat_id, message_id, config=None):
    """执行消息删除"""
    if config and not can_delete_message(config):
        logger.info(f"消息删除已禁用，跳过删除: chat={chat_id}, msg={message_id}")
        return
    try:
        bot.delete_message(chat_id, message_id)
        logger.debug(f"🗑️ 签到消息已自动删除: chat={chat_id}, msg={message_id}")
    except Exception as e:
        logger.debug(f"签到消息删除失败（可能已被手动删除）: {e}")

# 连续签到奖励配置：天数 → 额外积分
BONUS_DAYS = {3: 5, 7: 15, 15: 30, 30: 50}

# 签到卡片随机运势
FORTUNES = [
    "今日宜摸鱼 🐟",
    "好运连连，心想事成 ✨",
    "诸事顺利，万事如意 🎉",
    "今日份元气已充满 🔋",
    "坚持签到，必有收获 💪",
    "幸运之星眷顾着你 ⭐",
    "今天也是元气满满的一天 🌟",
    "签到打卡，快乐加倍 😊",
    "日积月累，厚积薄发 📈",
    "好运正在赶来的路上 🚀",
]

# 多平台中文字体搜索路径（按优先级）
_FONT_PATHS = [
    # Windows
    "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",     # 黑体
    "C:/Windows/Fonts/simsun.ttc",     # 宋体
    # Linux (VPS常用)
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 文泉驿微米黑
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",    # 文泉驿正黑
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",  # Droid Sans Fallback
    "/usr/share/fonts/truetype/arphic/uming.ttc",      # AR PL UMing
    "/usr/share/fonts/truetype/arphic/ukai.ttc",       # AR PL UKai
    # macOS
    "/System/Library/Fonts/PingFang.ttc",              # 苹方
    "/System/Library/Fonts/STHeitiLight.ttc",          # 黑体
]

CHECKIN_FORMAT_HINT = "请直接发送简体“签到”（不要加任何符号）。繁体“簽到”和 QD 都不会生效。"


def is_invalid_checkin_command(text: str) -> bool:
    """识别常见但无效的签到写法，避免用户误以为已经签到。"""
    compact = "".join(str(text or "").strip().split()).lower()
    return compact in {
        "簽到",
        "/簽到",
        "qd",
        "/qd",
        "q.d",
        "q-d",
        "签到。",
        "簽到。",
    }


def is_checkin_enabled(config: dict) -> bool:
    """兼容 Dashboard 新键 enabled 与历史运行配置键 enable。"""
    checkin_cfg = (config or {}).get("CHECKIN_CONFIG", {})
    if "enabled" in checkin_cfg:
        return bool(checkin_cfg.get("enabled"))
    return bool(checkin_cfg.get("enable", False))


def _configured_bonus_days(checkin_cfg: dict) -> dict:
    """读取 Dashboard streak_bonus 与历史 bonus_3d 等配置。"""
    bonus_days = dict(BONUS_DAYS)
    for days in (3, 7, 15, 30):
        legacy_key = f"bonus_{days}d"
        if legacy_key in checkin_cfg:
            try:
                bonus_days[days] = int(checkin_cfg[legacy_key])
            except (TypeError, ValueError):
                continue
    configured = checkin_cfg.get("streak_bonus", {})
    if isinstance(configured, dict):
        for days, points in configured.items():
            try:
                bonus_days[int(days)] = int(points)
            except (TypeError, ValueError):
                continue
    return bonus_days


def handle_checkin(bot, m, config, db):
    """处理签到命令"""
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    # 检查签到开关
    checkin_cfg = config.get("CHECKIN_CONFIG", {})
    if not is_checkin_enabled(config):
        # 功能已关闭，静默忽略
        return

    today = datetime.now(_CST).strftime("%Y-%m-%d")
    base_points = checkin_cfg.get("base_points", 10)

    try:
        # 检查今日是否已签到
        row = db.conn.execute(
            "SELECT date, continuous_days, points_earned FROM checkin_records WHERE uid=? AND date=?",
            (uid, today)
        ).fetchone()

        if row:
            # 已签到
            bot.reply_to(
                m,
                f"✅ {uname}，今日已签到！\n"
                f"📅 连续签到：{row[1]}天\n"
                f"💰 今日获得：{row[2]}积分"
            )
            return

        # 计算连续天数
        yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        prev = db.conn.execute(
            "SELECT continuous_days, current_streak FROM checkin_records WHERE uid=? AND date=?",
            (uid, yesterday)
        ).fetchone()
        continuous = (prev[0] + 1) if prev else 1
        # current_streak：连续签到+1，断签重置为1
        current_streak = (prev[1] + 1) if prev else 1

        # 计算积分（基础 + 连续签到奖励，取最高档）
        earned = base_points
        bonus = 0
        for days, pts in sorted(_configured_bonus_days(checkin_cfg).items()):
            if continuous >= days:
                bonus = pts
        earned += bonus

        # 写入签到记录
        now_ts = int(time.time())
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO checkin_records (uid, date, continuous_days, current_streak, points_earned, ts) VALUES (?,?,?,?,?,?)",
                (uid, today, continuous, current_streak, earned, now_ts)
            )
            db.conn.commit()

        # 增加积分（add_points内部有锁）
        _lv_result = db.add_points(uid, earned)

        # 构建回复
        reply = f"✅ {uname} 签到成功！\n💰 获得积分：{earned}（基础{base_points}"
        if bonus > 0:
            reply += f" + 连续签到奖励{bonus}"
        reply += f"）\n📅 连续签到：{continuous}天"

        current_points = db.get_user_points(uid)
        if current_points is not None:
            reply += f"\n💎 当前积分：{current_points}"

        sent = bot.reply_to(m, reply)
        # 预约删除：用户消息和回复消息60秒后自动删除
        _schedule_delete_message(bot, m.chat.id, m.message_id, 60, config)
        if sent and hasattr(sent, 'message_id'):
            _schedule_delete_message(bot, m.chat.id, sent.message_id, 60, config)
        logger.info(f"签到: uid={uid} 连续{continuous}天 积分+{earned}")

    except Exception as e:
        logger.error(f"签到异常: {e}")
        bot.reply_to(m, "❌ 签到失败，请稍后再试")
        return

    # 以下为非关键操作，失败不影响签到成功提示
    # 检查升级通知
    try:
        check_level_up(bot, m.chat.id, uid, uname, _lv_result, config)
    except Exception as e:
        logger.error(f"签到升级通知异常: {e}")

    # 尝试生成签到卡片
    try:
        if current_points is not None:
            generate_checkin_card(bot, m, config, db, uid, uname, continuous, earned, current_points)
    except Exception as e:
        logger.error(f"签到卡片生成异常: {e}")


def handle_checkin_rank(bot, m, config, db):
    """签到排行 - 当前连续签到天数TOP10"""
    try:
        rows = db.conn.execute(
            "SELECT u.uid, u.name, MAX(cr.current_streak) as streak "
            "FROM checkin_records cr "
            "JOIN users u ON cr.uid = u.uid "
            "GROUP BY cr.uid "
            "ORDER BY streak DESC "
            "LIMIT 10"
        ).fetchall()

        if not rows:
            bot.reply_to(m, "📋 暂无签到记录")
            return

        medals = ["🥇", "🥈", "🥉"]
        text = "📅 签到排行榜（当前连续天数）\n━━━━━━━━━━━━━\n"
        for i, (uid, name, streak) in enumerate(rows, 1):
            name = name or f"用户{uid}"
            medal = medals[i - 1] if i <= 3 else f"{i}."
            text += f"{medal} {name} — {streak}天\n"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"签到排行异常: {e}")


def handle_makeup_checkin(bot, m, config, db):
    """补签 - 消耗积分补昨日签到"""
    uid = m.from_user.id
    uname = m.from_user.first_name or "用户"

    # 检查签到开关
    checkin_cfg = config.get("CHECKIN_CONFIG", {})
    if not is_checkin_enabled(config):
        # 功能已关闭，静默忽略
        return

    cost = config.get("MAKEUP_CHECKIN_COST", 20)
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
    day_before = (datetime.now(_CST) - timedelta(days=2)).strftime("%Y-%m-%d")

    try:
        # 检查昨日是否已签到
        yesterday_row = db.conn.execute(
            "SELECT date FROM checkin_records WHERE uid=? AND date=?",
            (uid, yesterday)
        ).fetchone()
        if yesterday_row:
            bot.reply_to(m, "✅ 昨日已签到，无需补签")
            return

        # 检查今日是否已签到
        today_row = db.conn.execute(
            "SELECT date FROM checkin_records WHERE uid=? AND date=?",
            (uid, today)
        ).fetchone()
        if not today_row:
            bot.reply_to(m, "❌ 请先签到今日")
            return

        # 检查积分是否足够
        current_points = db.get_user_points(uid)
        if current_points is None or current_points < cost:
            deficit = cost - (current_points or 0)
            bot.reply_to(m, f"❌ 积分不足，补签需要{cost}积分，还差{deficit}积分")
            return

        # 计算昨日连续天数：前天的连续天数 + 1
        prev = db.conn.execute(
            "SELECT continuous_days, current_streak FROM checkin_records WHERE uid=? AND date=?",
            (uid, day_before)
        ).fetchone()
        yesterday_continuous = (prev[0] + 1) if prev else 1
        yesterday_streak = (prev[1] + 1) if prev else 1

        # 写入昨日补签记录（积分为0，补签不获得积分）
        now_ts = int(time.time())
        with _db_lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO checkin_records (uid, date, continuous_days, current_streak, points_earned, ts) VALUES (?,?,?,?,?,?)",
                (uid, yesterday, yesterday_continuous, yesterday_streak, 0, now_ts)
            )
            db.conn.commit()

        # 扣除积分
        db.add_points(uid, -cost, source="checkin_makeup")

        # 重新计算今日连续天数
        today_continuous = yesterday_continuous + 1
        today_streak = yesterday_streak + 1
        with _db_lock:
            db.conn.execute(
                "UPDATE checkin_records SET continuous_days=?, current_streak=? WHERE uid=? AND date=?",
                (today_continuous, today_streak, uid, today)
            )
            db.conn.commit()

        bot.reply_to(
            m,
            f"✅ 补签成功！\n💰 消耗积分：{cost}\n📅 连续签到：{today_streak}天"
        )
        logger.info(f"补签: uid={uid} 消耗{cost}积分 连续{today_streak}天")

    except Exception as e:
        logger.error(f"补签异常: {e}")
        bot.reply_to(m, "❌ 补签失败，请稍后再试")


def handle_checkin_calendar(bot, m, config, db):
    """签到日历 - 显示当月签到状态"""
    uid = m.from_user.id
    now_cst = datetime.now(_CST)
    year = now_cst.year
    month = now_cst.month
    today_day = now_cst.day

    try:
        # 查询当月签到记录
        month_prefix = f"{year}-{month:02d}"
        rows = db.conn.execute(
            "SELECT date FROM checkin_records WHERE uid=? AND date LIKE ?",
            (uid, f"{month_prefix}%")
        ).fetchall()
        checked_dates = {row[0] for row in rows}

        # 计算当月天数
        if month == 12:
            next_month = datetime(year + 1, 1, 1)
        else:
            next_month = datetime(year, month + 1, 1)
        total_days = (next_month - datetime(year, month, 1)).days

        # 当月1号是星期几（0=周日）
        first_weekday = datetime(year, month, 1).weekday()
        # 转为周日=0的格式
        first_weekday = (first_weekday + 1) % 7

        # 构建日历
        text = f"📅 {year}年{month}月 签到日历\n\n"
        text += "日 一 二 三 四 五 六\n"

        # 前置空格
        text += "   " * first_weekday

        for day in range(1, total_days + 1):
            date_str = f"{year}-{month:02d}-{day:02d}"
            if date_str in checked_dates:
                symbol = "✅"
            elif day > today_day:
                symbol = "○"
            elif day < today_day:
                symbol = "·"
            else:
                # 今天
                if date_str in checked_dates:
                    symbol = "✅"
                else:
                    symbol = "·"

            text += symbol

            # 计算当前是星期几
            current_weekday = (first_weekday + day - 1) % 7
            if current_weekday == 6:
                text += "\n"
            else:
                text += " "

        text += f"\n\n本月签到：{len(checked_dates)}/{total_days}天"

        bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"签到日历异常: {e}")
        bot.reply_to(m, "❌ 获取签到日历失败，请稍后再试")


def generate_checkin_card(bot, m, config, db, uid, uname, continuous, earned, total_points):
    """生成签到卡片图片"""
    if not _HAS_PIL:
        return

    try:
        width, height = 400, 200
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        # 渐变背景：从 #4A90D9 到 #357ABD
        r1, g1, b1 = 0x4A, 0x90, 0xD9
        r2, g2, b2 = 0x35, 0x7A, 0xBD
        for y in range(height):
            ratio = y / height
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 尝试加载中文字体（多平台兼容）
        font_large = font_medium = font_small = None
        for fp in _FONT_PATHS:
            if os.path.exists(fp):
                try:
                    font_large = ImageFont.truetype(fp, 28)
                    font_medium = ImageFont.truetype(fp, 20)
                    font_small = ImageFont.truetype(fp, 14)
                    logger.info(f"✅ 签到卡片字体加载成功: {fp}")
                    break
                except Exception:
                    continue

        if not font_large:
            logger.warning("⚠️ 未找到可用中文字体，使用默认字体（可能无法正常显示中文）")
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 用户名
        draw.text((20, 15), uname, fill="white", font=font_medium)

        # 签到成功！
        draw.text((20, 45), "签到成功！", fill="white", font=font_large)

        # 连续签到天数
        draw.text((20, 85), f"连续签到 {continuous} 天", fill="white", font=font_medium)

        # 获得积分（金色）
        draw.text((20, 115), f"获得积分 +{earned}", fill=(255, 215, 0), font=font_medium)

        # 当前积分
        draw.text((20, 145), f"当前积分 {total_points}", fill="white", font=font_medium)

        # 随机运势
        fortune = random.choice(FORTUNES)
        draw.text((20, 175), fortune, fill=(220, 220, 220), font=font_small)

        # 保存到临时文件并发送
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            img.save(tmp_path, "PNG")
            with open(tmp_path, "rb") as f:
                bot.send_photo(m.chat.id, f, reply_to_message_id=m.message_id)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        logger.error(f"生成签到卡片异常: {e}")
