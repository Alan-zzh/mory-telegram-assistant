"""
modules/visual_dashboard.py · 可视化数据面板

功能：
  handle_group_dashboard(bot, m, config, db)    - 群数据面板（800x600图片）
  handle_personal_dashboard(bot, m, config, db)  - 个人数据面板（600x400图片）

数据表：
  speech_daily   → 发言统计（uid, date, chat_id, count）
  user_levels    → 等级积分（uid, level, points）
  checkin_records → 签到记录（uid, date, continuous_days）
  points_log     → 积分变动（uid, change_amount, balance_after, source, ts）

Pillow不可用时自动回退到文本格式。
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger
from core.database import _db_lock

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

_CST = timezone(timedelta(hours=8))
logger = get_logger("visual_dashboard")

# 等级称号映射（config中的LEVEL_TITLES优先，此为默认回退）
_DEFAULT_LEVEL_TITLES = {"1": "萌新", "2": "常客", "3": "达人", "4": "大佬"}

# 等级积分阈值（与database.py中add_points逻辑一致）
_LEVEL_THRESHOLDS = [(1, 0), (2, 20), (3, 100), (4, 500)]

# 配色方案
_COLORS = {
    "bg_top": (44, 62, 80),       # #2C3E50
    "bg_bottom": (52, 152, 219),   # #3498DB
    "title": (255, 255, 255),
    "subtitle": (189, 195, 199),
    "bar": (46, 204, 113),         # #2ECC71
    "bar_alt": (52, 152, 219),     # #3498DB
    "progress_bg": (127, 140, 141),
    "progress_fill": (241, 196, 15),  # #F1C40F
    "text_dark": (44, 62, 80),
    "text_light": (236, 240, 241),
    "pie_colors": [
        (46, 204, 113),    # 绿
        (52, 152, 219),    # 蓝
        (241, 196, 15),    # 黄
        (231, 76, 60),     # 红
        (155, 89, 182),    # 紫
    ],
    "line": (231, 76, 60),         # #E74C3C
    "line_point": (241, 196, 15),  # #F1C40F
}


def _get_level_title(level: int, config: dict) -> str:
    """获取等级称号，优先从config读取，回退到默认"""
    titles = config.get("LEVEL_TITLES", _DEFAULT_LEVEL_TITLES)
    return titles.get(str(level), _DEFAULT_LEVEL_TITLES.get(str(level), "未知"))


def _load_fonts():
    """加载字体，返回 (font_title, font_subtitle, font_medium, font_small)"""
    font_sizes = (28, 20, 16, 13)
    # 尝试中文字体
    for font_name in ("msyh.ttc", "simhei.ttf", "simsun.ttc"):
        try:
            fonts = tuple(ImageFont.truetype(font_name, s) for s in font_sizes)
            return fonts
        except Exception:
            continue
    # 尝试英文字体
    for font_name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            fonts = tuple(ImageFont.truetype(font_name, s) for s in font_sizes)
            return fonts
        except Exception:
            continue
    # 最终回退
    default = ImageFont.load_default()
    return (default, default, default, default)


def _draw_gradient_bg(img, draw):
    """绘制渐变背景"""
    w, h = img.size
    r1, g1, b1 = _COLORS["bg_top"]
    r2, g2, b2 = _COLORS["bg_bottom"]
    for y in range(h):
        ratio = y / h
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _draw_bar_chart(draw, x, y, w, h, data, labels, title, font_subtitle, font_small):
    """绘制简单柱状图

    Args:
        draw: ImageDraw对象
        x, y: 左上角坐标
        w, h: 图表区域宽高
        data: 数值列表
        labels: 标签列表
        title: 图表标题
        font_subtitle: 副标题字体
        font_small: 小字体
    """
    # 标题
    draw.text((x, y), title, fill=_COLORS["title"], font=font_subtitle)
    chart_y = y + 28
    chart_h = h - 40

    if not data or max(data) == 0:
        draw.text((x + 10, chart_y + chart_h // 2 - 8), "暂无数据",
                  fill=_COLORS["subtitle"], font=font_small)
        return

    max_val = max(data)
    bar_count = len(data)
    bar_gap = 6
    bar_w = max((w - bar_gap * (bar_count + 1)) // bar_count, 8)
    # 居中偏移
    total_bars_w = bar_count * bar_w + (bar_count + 1) * bar_gap
    offset_x = (w - total_bars_w) // 2

    for i, val in enumerate(data):
        bar_h = int((val / max_val) * (chart_h - 20)) if max_val > 0 else 0
        bar_h = max(bar_h, 2)
        bx = x + offset_x + (i + 1) * bar_gap + i * bar_w
        by = chart_y + chart_h - bar_h - 15

        # 柱体
        color = _COLORS["bar"] if i % 2 == 0 else _COLORS["bar_alt"]
        draw.rectangle([(bx, by), (bx + bar_w, chart_y + chart_h - 15)], fill=color)

        # 数值
        draw.text((bx, by - 16), str(val), fill=_COLORS["text_light"], font=font_small)

        # 标签
        label = labels[i] if i < len(labels) else ""
        draw.text((bx - 2, chart_y + chart_h - 12), label,
                  fill=_COLORS["subtitle"], font=font_small)


def _draw_progress_bar(draw, x, y, w, h, progress, label, font_small):
    """绘制进度条

    Args:
        draw: ImageDraw对象
        x, y: 左上角坐标
        w, h: 进度条宽高
        progress: 进度值 0.0~1.0
        label: 进度条标签
        font_small: 小字体
    """
    # 标签
    draw.text((x, y - 18), label, fill=_COLORS["text_light"], font=font_small)

    # 背景条
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=h // 2,
                           fill=_COLORS["progress_bg"])

    # 填充条
    fill_w = max(int(w * min(progress, 1.0)), h)  # 至少一个圆点
    if fill_w > 0:
        draw.rounded_rectangle([(x, y), (x + fill_w, y + h)], radius=h // 2,
                               fill=_COLORS["progress_fill"])

    # 百分比文字
    pct_text = f"{int(progress * 100)}%"
    bbox = draw.textbbox((0, 0), pct_text, font=font_small)
    tw = bbox[2] - bbox[0]
    draw.text((x + w + 8, y + (h - (bbox[3] - bbox[1])) // 2),
              pct_text, fill=_COLORS["text_light"], font=font_small)


def _draw_pie_chart(draw, x, y, w, h, data, labels, title, font_subtitle, font_small):
    """绘制简易饼图（用彩色矩形块表示比例）

    Args:
        draw: ImageDraw对象
        x, y: 左上角坐标
        w, h: 图表区域宽高
        data: 数值列表
        labels: 标签列表
        title: 图表标题
        font_subtitle: 副标题字体
        font_small: 小字体
    """
    draw.text((x, y), title, fill=_COLORS["title"], font=font_subtitle)
    chart_y = y + 28

    total = sum(data)
    if not data or total == 0:
        draw.text((x + 10, chart_y + 20), "暂无数据",
                  fill=_COLORS["subtitle"], font=font_small)
        return

    # 水平比例条
    bar_y = chart_y + 5
    bar_h = 24
    cur_x = x
    for i, val in enumerate(data):
        seg_w = int((val / total) * w)
        if seg_w <= 0:
            continue
        color = _COLORS["pie_colors"][i % len(_COLORS["pie_colors"])]
        draw.rectangle([(cur_x, bar_y), (cur_x + seg_w, bar_y + bar_h)], fill=color)
        cur_x += seg_w

    # 图例
    legend_y = bar_y + bar_h + 12
    for i, val in enumerate(data):
        label = labels[i] if i < len(labels) else f"项目{i + 1}"
        color = _COLORS["pie_colors"][i % len(_COLORS["pie_colors"])]
        # 色块
        draw.rectangle([(x, legend_y), (x + 12, legend_y + 12)], fill=color)
        pct = f"{val / total * 100:.1f}%" if total > 0 else "0%"
        draw.text((x + 16, legend_y - 2), f"{label} {val}人 ({pct})",
                  fill=_COLORS["text_light"], font=font_small)
        legend_y += 20


def _draw_line_chart(draw, x, y, w, h, data, labels, title, font_subtitle, font_small):
    """绘制简易折线图

    Args:
        draw: ImageDraw对象
        x, y: 左上角坐标
        w, h: 图表区域宽高
        data: 数值列表
        labels: 标签列表
        title: 图表标题
        font_subtitle: 副标题字体
        font_small: 小字体
    """
    draw.text((x, y), title, fill=_COLORS["title"], font=font_subtitle)
    chart_y = y + 28
    chart_h = h - 40

    if not data or max(data) == 0:
        draw.text((x + 10, chart_y + chart_h // 2 - 8), "暂无数据",
                  fill=_COLORS["subtitle"], font=font_small)
        return

    max_val = max(data)
    point_count = len(data)
    if point_count < 2:
        # 只有一个点，画个圆点
        px = x + w // 2
        py = chart_y + chart_h // 2
        draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill=_COLORS["line_point"])
        if data:
            draw.text((px + 8, py - 8), str(data[0]), fill=_COLORS["text_light"], font=font_small)
        return

    # 计算各点坐标
    step_x = (w - 20) / (point_count - 1)
    points = []
    for i, val in enumerate(data):
        px = x + 10 + int(i * step_x)
        py = chart_y + chart_h - 15 - int((val / max_val) * (chart_h - 25))
        points.append((px, py))

    # 连线
    for i in range(len(points) - 1):
        draw.line([points[i], points[i + 1]], fill=_COLORS["line"], width=2)

    # 数据点 + 标签
    for i, (px, py) in enumerate(points):
        draw.ellipse([(px - 3, py - 3), (px + 3, py + 3)], fill=_COLORS["line_point"])
        # 数值
        draw.text((px - 6, py - 16), str(data[i]), fill=_COLORS["text_light"], font=font_small)
        # X轴标签
        label = labels[i] if i < len(labels) else ""
        draw.text((px - 8, chart_y + chart_h - 10), label,
                  fill=_COLORS["subtitle"], font=font_small)


# ═══════════════════════════════════════════════════════════════
#  群数据面板
# ═══════════════════════════════════════════════════════════════

def _fetch_group_data(db, chat_id: int) -> dict:
    """查询群面板所需的全部数据"""
    now_cst = datetime.now(_CST)
    today = now_cst.strftime("%Y-%m-%d")
    seven_days_ago = (now_cst - timedelta(days=6)).strftime("%Y-%m-%d")

    data = {
        "speech_trend": [],       # [(date, count), ...]
        "top_users": [],          # [(uid, name, count), ...]
        "level_dist": [],         # [(level_range, count), ...]
        "checkin_trend": [],      # [(date, count), ...]
    }

    with _db_lock:
        # 1. 近7天发言趋势
        rows = db.conn.execute(
            """SELECT date, COALESCE(SUM(count),0) FROM speech_daily
               WHERE date>=? AND date<=? AND chat_id=?
               GROUP BY date ORDER BY date""",
            (seven_days_ago, today, chat_id)
        ).fetchall()
        # 补全缺失日期
        trend_map = {r[0]: r[1] for r in rows}
        for i in range(7):
            d = (now_cst - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            data["speech_trend"].append((d, trend_map.get(d, 0)))

        # 2. TOP5活跃用户（近7天）
        rows = db.conn.execute(
            """SELECT sd.uid, COALESCE(u.name, '未知'), SUM(sd.count)
               FROM speech_daily sd LEFT JOIN users u ON sd.uid=u.uid
               WHERE sd.date>=? AND sd.date<=? AND sd.chat_id=?
               GROUP BY sd.uid ORDER BY SUM(sd.count) DESC LIMIT 5""",
            (seven_days_ago, today, chat_id)
        ).fetchall()
        data["top_users"] = list(rows)

        # 3. 积分等级分布
        rows = db.conn.execute(
            """SELECT
                 CASE
                   WHEN points < 20 THEN 'Lv1 萌新'
                   WHEN points < 100 THEN 'Lv2 常客'
                   WHEN points < 500 THEN 'Lv3 达人'
                   ELSE 'Lv4 大佬'
                 END as level_range,
                 COUNT(*) as cnt
               FROM user_levels GROUP BY level_range
               ORDER BY MIN(points)"""
        ).fetchall()
        data["level_dist"] = list(rows)

        # 4. 近7天签到人数
        rows = db.conn.execute(
            """SELECT date, COUNT(DISTINCT uid) FROM checkin_records
               WHERE date>=? AND date<=?
               GROUP BY date ORDER BY date""",
            (seven_days_ago, today)
        ).fetchall()
        checkin_map = {r[0]: r[1] for r in rows}
        for i in range(7):
            d = (now_cst - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            data["checkin_trend"].append((d, checkin_map.get(d, 0)))

    return data


def _build_group_image(data: dict, config: dict) -> object:
    """生成群数据面板图片（800x600）"""
    width, height = 800, 600
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    _draw_gradient_bg(img, draw)

    font_title, font_subtitle, font_medium, font_small = _load_fonts()

    # 标题
    draw.text((30, 18), "📊 群数据面板", fill=_COLORS["title"], font=font_title)

    # 分区：4个象限
    half_w = (width - 90) // 2
    half_h = (height - 100) // 2
    left_x, right_x = 30, 30 + half_w + 30
    top_y, bottom_y = 65, 65 + half_h + 20

    # 左上：7天发言趋势（柱状图）
    speech_labels = [d[5:] for d, _ in data["speech_trend"]]  # MM-DD
    speech_values = [v for _, v in data["speech_trend"]]
    _draw_bar_chart(draw, left_x, top_y, half_w, half_h,
                    speech_values, speech_labels, "💬 近7天发言趋势",
                    font_subtitle, font_small)

    # 右上：TOP5用户（文字+横条）
    draw.text((right_x, top_y), "🏆 TOP5活跃用户", fill=_COLORS["title"], font=font_subtitle)
    max_count = max((c for _, _, c in data["top_users"]), default=1) or 1
    for i, (uid, name, count) in enumerate(data["top_users"]):
        ry = top_y + 30 + i * 42
        # 排名
        medals = ["🥇", "🥈", "🥉"]
        rank_str = medals[i] if i < 3 else f" {i + 1}."
        draw.text((right_x, ry), f"{rank_str} {name}", fill=_COLORS["text_light"], font=font_medium)
        # 横条
        bar_w = int((count / max_count) * (half_w - 80))
        bar_w = max(bar_w, 4)
        draw.rounded_rectangle(
            [(right_x, ry + 20), (right_x + bar_w, ry + 30)],
            radius=3, fill=_COLORS["bar"]
        )
        draw.text((right_x + bar_w + 6, ry + 17), str(count),
                  fill=_COLORS["subtitle"], font=font_small)

    if not data["top_users"]:
        draw.text((right_x + 10, top_y + 60), "暂无数据",
                  fill=_COLORS["subtitle"], font=font_small)

    # 左下：积分分布（简易饼图）
    dist_labels = [r[0] for r in data["level_dist"]]
    dist_values = [r[1] for r in data["level_dist"]]
    _draw_pie_chart(draw, left_x, bottom_y, half_w, half_h,
                    dist_values, dist_labels, "💎 积分等级分布",
                    font_subtitle, font_small)

    # 右下：签到趋势（折线图）
    checkin_labels = [d[5:] for d, _ in data["checkin_trend"]]  # MM-DD
    checkin_values = [v for _, v in data["checkin_trend"]]
    _draw_line_chart(draw, right_x, bottom_y, half_w, half_h,
                     checkin_values, checkin_labels, "📅 近7天签到人数",
                     font_subtitle, font_small)

    return img


def _build_group_text(data: dict, config: dict) -> str:
    """群面板文本回退"""
    lines = ["📊 群数据面板", "━━━━━━━━━━━━━"]

    # 发言趋势
    lines.append("💬 近7天发言趋势：")
    for date_str, count in data["speech_trend"]:
        bar = "█" * min(count // 10, 20) or "▏"
        lines.append(f"  {date_str[5:]} {bar} {count}")

    # TOP5
    if data["top_users"]:
        lines.append("🏆 TOP5活跃用户：")
        medals = ["🥇", "🥈", "🥉"]
        for i, (uid, name, count) in enumerate(data["top_users"]):
            prefix = medals[i] if i < 3 else f"  {i + 1}."
            lines.append(f"  {prefix} {name} - {count}条")

    # 积分分布
    if data["level_dist"]:
        lines.append("💎 积分等级分布：")
        for label, cnt in data["level_dist"]:
            lines.append(f"  {label}: {cnt}人")

    # 签到趋势
    lines.append("📅 近7天签到人数：")
    for date_str, count in data["checkin_trend"]:
        lines.append(f"  {date_str[5:]}: {count}人")

    return "\n".join(lines)


def handle_group_dashboard(bot, m, config, db):
    """生成群数据面板图片并发送

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    chat_id = m.chat.id if m.chat else 0
    try:
        data = _fetch_group_data(db, chat_id)

        if _HAS_PIL:
            img = _build_group_image(data, config)
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
            text = _build_group_text(data, config)
            bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"群数据面板生成异常: chat_id={chat_id} err={e}")
        bot.reply_to(m, "❌ 群数据面板生成失败，请稍后再试")


# ═══════════════════════════════════════════════════════════════
#  个人数据面板
# ═══════════════════════════════════════════════════════════════

def _fetch_personal_data(db, uid: int, chat_id: int) -> dict:
    """查询个人面板所需的全部数据"""
    now_cst = datetime.now(_CST)
    today = now_cst.strftime("%Y-%m-%d")
    seven_days_ago = (now_cst - timedelta(days=6)).strftime("%Y-%m-%d")

    data = {
        "name": f"用户{uid}",
        "level": 1,
        "points": 0,
        "speech_trend": [],       # [(date, count), ...]
        "points_log": [],         # [(change, balance, source, ts), ...]
        "progress": 0.0,          # 等级进度 0~1
        "level_title": "萌新",
        "next_threshold": 20,
    }

    with _db_lock:
        # 用户名
        row = db.conn.execute(
            "SELECT name FROM users WHERE uid=?", (uid,)
        ).fetchone()
        if row:
            data["name"] = row[0] or f"用户{uid}"

        # 等级 + 积分
        row = db.conn.execute(
            "SELECT level, points FROM user_levels WHERE uid=?", (uid,)
        ).fetchone()
        if row:
            data["level"] = row[0] or 1
            data["points"] = row[1] or 0

        # 近7天发言趋势
        rows = db.conn.execute(
            """SELECT date, COALESCE(SUM(count),0) FROM speech_daily
               WHERE uid=? AND date>=? AND date<=? AND chat_id=?
               GROUP BY date ORDER BY date""",
            (uid, seven_days_ago, today, chat_id)
        ).fetchall()
        trend_map = {r[0]: r[1] for r in rows}
        for i in range(7):
            d = (now_cst - timedelta(days=6 - i)).strftime("%Y-%m-%d")
            data["speech_trend"].append((d, trend_map.get(d, 0)))

        # 积分变动记录（最近7条）
        try:
            rows = db.conn.execute(
                """SELECT change_amount, balance_after, source, ts
                   FROM points_log WHERE uid=?
                   ORDER BY ts DESC LIMIT 7""",
                (uid,)
            ).fetchall()
            data["points_log"] = list(rows)
        except Exception:
            data["points_log"] = []

    # 等级进度计算
    points = data["points"]
    current_threshold = 0
    next_threshold = 20
    for lvl, thresh in _LEVEL_THRESHOLDS:
        if points >= thresh:
            current_threshold = thresh
    # 找下一级阈值
    for lvl, thresh in _LEVEL_THRESHOLDS:
        if thresh > points:
            next_threshold = thresh
            break
    else:
        next_threshold = points + 1  # 已满级

    if next_threshold > current_threshold:
        data["progress"] = (points - current_threshold) / (next_threshold - current_threshold)
    else:
        data["progress"] = 1.0
    data["next_threshold"] = next_threshold

    return data


def _build_personal_image(data: dict, config: dict) -> object:
    """生成个人数据面板图片（600x400）"""
    width, height = 600, 400
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    _draw_gradient_bg(img, draw)

    font_title, font_subtitle, font_medium, font_small = _load_fonts()

    # 标题
    level_title = _get_level_title(data["level"], config)
    title_text = f"📊 我的数据 - {data['name']}"
    draw.text((25, 15), title_text, fill=_COLORS["title"], font=font_title)

    # 副标题：等级信息
    sub_text = f"Lv{data['level']} {level_title}  |  💎 {data['points']}积分"
    draw.text((25, 52), sub_text, fill=_COLORS["subtitle"], font=font_medium)

    # 分区：左半发言趋势，右半等级进度+积分记录
    left_w = 280
    right_x = 320

    # 左侧：7天发言趋势（柱状图）
    speech_labels = [d[5:] for d, _ in data["speech_trend"]]
    speech_values = [v for _, v in data["speech_trend"]]
    _draw_bar_chart(draw, 25, 80, left_w, 200,
                    speech_values, speech_labels, "💬 近7天发言",
                    font_subtitle, font_small)

    # 右上：等级进度条
    progress_label = f"Lv{data['level']} → Lv{data['level'] + 1}  ({data['points']}/{data['next_threshold']})"
    _draw_progress_bar(draw, right_x, 108, 240, 18,
                       data["progress"], progress_label, font_small)

    # 右侧：等级称号
    draw.text((right_x, 140), f"🏷 {level_title}",
              fill=_COLORS["text_light"], font=font_medium)

    # 底部：最近积分变动
    draw.text((25, 295), "📝 最近积分变动", fill=_COLORS["title"], font=font_subtitle)
    source_names = {
        "speech": "发言", "checkin": "签到", "invite": "邀请",
        "tip": "打赏", "exchange": "兑换", "blindbox": "盲盒",
        "wheel": "转盘", "transfer": "转账", "quest": "任务",
        "achievement": "成就", "system": "系统",
    }
    for i, (change, balance, source, ts) in enumerate(data["points_log"][:5]):
        ry = 320 + i * 18
        sign = "+" if change > 0 else ""
        source_cn = source_names.get(source, source)
        time_str = datetime.fromtimestamp(ts, _CST).strftime("%m/%d %H:%M") if ts else ""
        line = f"{sign}{change}  {source_cn}  余额{balance}  {time_str}"
        color = (46, 204, 113) if change > 0 else (231, 76, 60) if change < 0 else _COLORS["subtitle"]
        draw.text((30, ry), line, fill=color, font=font_small)

    if not data["points_log"]:
        draw.text((30, 325), "暂无积分记录", fill=_COLORS["subtitle"], font=font_small)

    return img


def _build_personal_text(data: dict, config: dict) -> str:
    """个人面板文本回退"""
    level_title = _get_level_title(data["level"], config)
    lines = [
        f"📊 我的数据 - {data['name']}",
        "━━━━━━━━━━━━━",
        f"🏷 Lv{data['level']} {level_title}  |  💎 {data['points']}积分",
        f"📈 升级进度：{data['points']}/{data['next_threshold']} ({int(data['progress'] * 100)}%)",
        "",
        "💬 近7天发言：",
    ]

    for date_str, count in data["speech_trend"]:
        bar = "█" * min(count // 5, 20) or "▏"
        lines.append(f"  {date_str[5:]} {bar} {count}")

    source_names = {
        "speech": "发言", "checkin": "签到", "invite": "邀请",
        "tip": "打赏", "exchange": "兑换", "blindbox": "盲盒",
        "wheel": "转盘", "transfer": "转账", "quest": "任务",
        "achievement": "成就", "system": "系统",
    }

    if data["points_log"]:
        lines.append("📝 最近积分变动：")
        for change, balance, source, ts in data["points_log"][:5]:
            sign = "+" if change > 0 else ""
            source_cn = source_names.get(source, source)
            time_str = datetime.fromtimestamp(ts, _CST).strftime("%m/%d %H:%M") if ts else ""
            lines.append(f"  {sign}{change} {source_cn} 余额{balance} {time_str}")

    return "\n".join(lines)


def handle_personal_dashboard(bot, m, config, db):
    """生成个人数据面板图片并发送

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    uid = m.from_user.id
    chat_id = m.chat.id if m.chat else 0

    try:
        data = _fetch_personal_data(db, uid, chat_id)

        if _HAS_PIL:
            img = _build_personal_image(data, config)
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
            text = _build_personal_text(data, config)
            bot.reply_to(m, text)

    except Exception as e:
        logger.error(f"个人数据面板生成异常: uid={uid} err={e}")
        bot.reply_to(m, "❌ 个人数据面板生成失败，请稍后再试")
