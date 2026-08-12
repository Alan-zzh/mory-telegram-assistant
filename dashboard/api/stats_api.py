# -*- coding: utf-8 -*-
"""Dashboard数据统计API"""
import io
import csv
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, Response, session
from dashboard.helpers import (
    login_required, get_db, read_config, get_vps_status, _CST
)
from core.logging_util import get_logger

stats_bp = Blueprint('stats', __name__, url_prefix='/api')
logger = get_logger("stats_api")


@stats_bp.route("/stats/overview")
@login_required
def api_stats_overview():
    """数据概览
    ---
    tags:
      - 数据统计
    summary: 获取系统整体运行数据概览
    description: |
      返回用户总数、活跃用户、消息统计、在线趋势、小时分布、
      转化漏斗、群组统计、频道统计及 VPS 运行状态。
    responses:
      200:
        description: 成功返回概览数据
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            data:
              type: object
              properties:
                total_users:
                  type: integer
                  description: 用户总数
                today_active:
                  type: integer
                  description: 今日活跃用户数
                week_active:
                  type: integer
                  description: 近 7 天活跃用户数
                month_active:
                  type: integer
                  description: 近 30 天活跃用户数
                total_group_msgs:
                  type: integer
                  description: 群消息总数
                total_private_msgs:
                  type: integer
                  description: 私聊消息总数
                online_trend:
                  type: array
                  description: 近 7 天新增用户趋势
                hourly_dist:
                  type: object
                  description: 小时活跃分布
                conversion_funnel:
                  type: object
                  description: 转化漏斗
                group_stats:
                  type: object
                  description: 群组近 7 天加入/退出统计
                channel_stats:
                  type: object
                  description: 频道帖子及阅读量统计
                vps:
                  type: object
                  description: VPS 运行状态
      500:
        description: 内部错误
    """
    stats = {
        "total_users": 0, "today_active": 0, "week_active": 0, "month_active": 0,
        "total_group_msgs": 0, "total_private_msgs": 0,
        "online_trend": [], "hourly_dist": {}, "conversion_funnel": {},
        "group_stats": {}, "channel_stats": {}
    }
    try:
        conn = get_db()
        r = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        stats["total_users"] = r[0] if r else 0
        # [TRAE SOLO CN] v5.12.3 修复：today_start 应为今天0点的 Unix 时间戳
        # 【v5.31.2 修复】原 datetime.now() 无 tz 返回 UTC，CST 0:00-8:00 漏算今日活跃
        today_start = int(datetime.now(_CST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (today_start,)).fetchone()
        stats["today_active"] = r[0] if r else 0
        week_start = int((datetime.now(_CST) - timedelta(days=7)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (week_start,)).fetchone()
        stats["week_active"] = r[0] if r else 0
        month_start = int((datetime.now(_CST) - timedelta(days=30)).timestamp())
        r = conn.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (month_start,)).fetchone()
        stats["month_active"] = r[0] if r else 0
        r = conn.execute("SELECT COALESCE(SUM(group_messages),0), COALESCE(SUM(private_messages),0) FROM users").fetchone()
        stats["total_group_msgs"] = r[0] if r else 0
        stats["total_private_msgs"] = r[1] if r else 0
        r = conn.execute("SELECT conversion_status, COUNT(*) FROM users GROUP BY conversion_status").fetchall()
        for row in r:
            stats["conversion_funnel"][row[0] or "unknown"] = row[1]
        for i in range(7):
            day = datetime.now(_CST) - timedelta(days=6-i)
            day_start = int(day.replace(hour=0, minute=0, second=0).timestamp())
            day_end = int(day.replace(hour=23, minute=59, second=59).timestamp())
            r = conn.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ? AND first_seen <= ?", (day_start, day_end)).fetchone()
            stats["online_trend"].append({"date": day.strftime("%m-%d"), "value": r[0] if r else 0})
        r = conn.execute("""
            SELECT strftime('%H', datetime(last_active, 'unixepoch', 'localtime')) as hour, COUNT(*)
            FROM users WHERE last_active > 0 GROUP BY hour ORDER BY hour
        """).fetchall()
        for row in r:
            stats["hourly_dist"][int(row[0]) if row[0] else 0] = row[1]
        try:
            r = conn.execute("""SELECT COALESCE(SUM(joined_count),0), COALESCE(SUM(left_count),0), COALESCE(SUM(net_count),0)
                               FROM group_stats WHERE date >= date('now', '-7 days')""").fetchone()
            stats["group_stats"] = {"week_joined": r[0] if r else 0, "week_left": r[1] if r else 0, "week_net": r[2] if r else 0}
        except Exception:
            stats["group_stats"] = {"week_joined": 0, "week_left": 0, "week_net": 0}
        try:
            r = conn.execute("SELECT COUNT(*), COALESCE(SUM(current_views),0) FROM channel_tracking").fetchone()
            stats["channel_stats"] = {"total_posts": r[0] if r else 0, "total_views": r[1] if r else 0, "avg_views": r[1] // max(r[0], 1) if r else 0}
        except Exception:
            stats["channel_stats"] = {"total_posts": 0, "total_views": 0, "avg_views": 0}
    except Exception as e:
        return jsonify({"ok": False, "error": "内部错误，请稍后重试"}), 500
    stats["vps"] = get_vps_status()
    return jsonify({"ok": True, "data": stats})


@stats_bp.route("/stats/users")
@login_required
def api_stats_users():
    """用户列表
    ---
    tags:
      - 数据统计
    summary: 分页获取用户列表
    description: |
      支持分页、搜索（按用户名或 UID）、排序。
      返回用户信息及等级积分。
    parameters:
      - name: page
        in: query
        type: integer
        required: false
        default: 1
        description: 页码
      - name: per_page
        in: query
        type: integer
        required: false
        default: 20
        description: 每页数量
      - name: search
        in: query
        type: string
        required: false
        description: 搜索关键词（用户名或 UID）
      - name: sort
        in: query
        type: string
        required: false
        default: last_active
        enum: [uid, name, first_seen, last_active, group_messages, private_messages]
        description: 排序字段
      - name: order
        in: query
        type: string
        required: false
        default: desc
        enum: [asc, desc]
        description: 排序方向
    responses:
      200:
        description: 成功返回用户列表
        schema:
          type: object
          properties:
            ok:
              type: boolean
              example: true
            data:
              type: object
              properties:
                users:
                  type: array
                  description: 用户列表
                pagination:
                  type: object
                  description: 分页信息
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "").strip()
    sort = request.args.get("sort", "last_active")
    order = request.args.get("order", "desc")
    conn = get_db()
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE name LIKE ? OR CAST(uid AS TEXT) LIKE ?"
        params = [f"%{search}%", f"%{search}%"]
    allowed_sorts = {"uid", "name", "first_seen", "last_active", "group_messages", "private_messages"}
    if sort not in allowed_sorts:
        sort = "last_active"
    allowed_orders = {"asc", "desc"}
    if order.lower() not in allowed_orders:
        order = "desc"
    else:
        order = order.lower()
    order_by_map = {
        ("uid", "asc"): "uid ASC", ("uid", "desc"): "uid DESC",
        ("name", "asc"): "name ASC", ("name", "desc"): "name DESC",
        ("first_seen", "asc"): "first_seen ASC", ("first_seen", "desc"): "first_seen DESC",
        ("last_active", "asc"): "last_active ASC", ("last_active", "desc"): "last_active DESC",
        ("group_messages", "asc"): "group_messages ASC", ("group_messages", "desc"): "group_messages DESC",
        ("private_messages", "asc"): "private_messages ASC", ("private_messages", "desc"): "private_messages DESC",
    }
    order_by = order_by_map.get((sort, order), "last_active DESC")
    # 安全：where_clause 为字面量（"" 或 "WHERE name LIKE ? OR CAST(uid AS TEXT) LIKE ?"），
    # order_by 来自白名单映射，均非用户输入；查询值通过 params 参数化绑定。
    total = conn.execute(f"SELECT COUNT(*) FROM users {where_clause}", params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = conn.execute(f"SELECT * FROM users {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?", params + [per_page, offset]).fetchall()
    users = [dict(r) for r in rows]
    # [TRAE SOLO CN] 修复N+1查询：批量获取用户等级积分，替代逐个查询
    if users:
        uids = [u["uid"] for u in users]
        # 安全：placeholders 仅生成 ? 占位符，uid 值通过 uids 参数化绑定
        placeholders = ','.join('?' * len(uids))
        levels = conn.execute(f"SELECT uid, level, points FROM user_levels WHERE uid IN ({placeholders})", uids).fetchall()
        level_map = {r[0]: {'level': r[1], 'points': r[2]} for r in levels}
    else:
        level_map = {}
    for u in users:
        r = level_map.get(u["uid"])
        u["level"] = r['level'] if r else 0
        u["points"] = r['points'] if r else 0
    pagination = {"page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page if total > 0 else 0}
    return jsonify({"ok": True, "data": {"users": users, "pagination": pagination}})


@stats_bp.route("/groups")
@login_required
def api_groups():
    """群组数据"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT chat_id, title, type,
                   COALESCE(SUM(joined_count), 0) as joined,
                   COALESCE(SUM(left_count), 0) as left_count,
                   COALESCE(SUM(net_count), 0) as net_count,
                   COUNT(*) as msg_count
            FROM group_events
            WHERE date >= date('now', '-30 days')
            GROUP BY chat_id, title, type
        """).fetchall()
        groups = [{"chat_id": r[0], "title": r[1], "type": r[2],
                   "joined": r[3], "left": r[4], "net": r[5], "msg_count": r[6]} for r in rows]
        return jsonify({"ok": True, "data": {"groups": groups}})
    except Exception as e:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@stats_bp.route("/channels")
@login_required
def api_channels():
    """频道数据"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT chat_id, msg_id, posted_at, current_views
            FROM channel_tracking ORDER BY posted_at DESC LIMIT 50
        """).fetchall()
        channels = [{"chat_id": r[0], "msg_id": r[1], "posted_at": r[2], "views": r[3]} for r in rows]
        return jsonify({"ok": True, "data": {"channels": channels}})
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@stats_bp.route("/logs")
@login_required
def api_logs():
    """日志查看"""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM reply_tracking").fetchone()[0]
        offset = (page - 1) * per_page
        rows = conn.execute("""
            SELECT bot_msg_id, chat_id, user_msg_id, ts, replied
            FROM reply_tracking ORDER BY ts DESC LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        logs = [{"bot_msg_id": r[0], "chat_id": r[1], "user_msg_id": r[2],
                 "ts": r[3], "replied": r[4]} for r in rows]
        pagination = {"page": page, "per_page": per_page, "total": total,
                      "pages": (total + per_page - 1) // per_page if total > 0 else 0}
        return jsonify({"ok": True, "data": {"logs": logs, "pagination": pagination}})
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@stats_bp.route("/logs/search")
@login_required
def api_logs_search():
    """日志搜索"""
    keyword = request.args.get("keyword", "").strip()[:50]
    if not keyword:
        return jsonify({"ok": False, "msg": "关键词不能为空"}), 400
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT bot_msg_id, chat_id, user_msg_id, ts, replied
            FROM reply_tracking
            WHERE CAST(bot_msg_id AS TEXT) LIKE ? OR CAST(chat_id AS TEXT) LIKE ?
            ORDER BY ts DESC LIMIT 100
        """, (f"%{keyword}%", f"%{keyword}%")).fetchall()
        logs = [{"bot_msg_id": r[0], "chat_id": r[1], "user_msg_id": r[2],
                 "ts": r[3], "replied": r[4]} for r in rows]
        return jsonify({"ok": True, "data": {"logs": logs, "total": len(logs)}})
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@stats_bp.route("/report/download")
@login_required
def api_report_download():
    """运营报表下载"""
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT uid, name, group_messages, private_messages, last_active, tags
            FROM users ORDER BY last_active DESC LIMIT 1000
        """).fetchall()
        output = io.StringIO()
        output.write('\ufeff')
        writer = csv.writer(output)
        writer.writerow(["UID", "用户名", "群消息", "私聊消息", "最后活跃", "标签"])
        for u in users:
            writer.writerow([u[0], u[1] or '', u[2], u[3], datetime.fromtimestamp(u[4], _CST).strftime("%Y-%m-%d %H:%M") if u[4] else '', u[5] or ''])
        return Response(output.getvalue(), mimetype='text/csv',
                       headers={"Content-Disposition": "attachment;filename=mory_report.csv"})
    except Exception:
        return jsonify({"ok": False, "msg": "内部错误，请稍后重试"}), 500


@stats_bp.route("/feedback/stats")
@login_required
def api_feedback_stats():
    """用户反馈统计"""
    conn = get_db()
    try:
        row = conn.execute("SELECT feedback, COUNT(*) FROM reply_feedback GROUP BY feedback").fetchall()
        counts = {"like": 0, "dislike": 0}
        for r in row:
            if r[0] in counts:
                counts[r[0]] = r[1]
        total = counts["like"] + counts["dislike"]
        rate = round(counts["like"] / total * 100, 1) if total > 0 else 0
    except Exception:
        counts, total, rate = {"like": 0, "dislike": 0}, 0, 0
    try:
        recent = conn.execute("SELECT bot_msg_id, chat_id, user_id, feedback, ts FROM reply_feedback ORDER BY ts DESC LIMIT 20").fetchall()
        recent_list = [{"bot_msg_id": r[0], "chat_id": r[1], "user_id": r[2], "feedback": r[3], "ts": r[4]} for r in recent]
    except Exception:
        recent_list = []
    return jsonify({"ok": True, "data": {"like": counts["like"], "dislike": counts["dislike"], "total": total, "satisfaction_rate": rate, "recent": recent_list}})


@stats_bp.route("/user/analytics")
@login_required
def api_user_analytics():
    """用户画像分析"""
    conn = get_db()
    now_ts = int(datetime.now(_CST).timestamp())
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except Exception:
        total_users = 0
    try:
        dau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 86400,)).fetchone()[0]
    except Exception:
        dau = 0
    try:
        wau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 7 * 86400,)).fetchone()[0]
    except Exception:
        wau = 0
    try:
        mau = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=?", (now_ts - 30 * 86400,)).fetchone()[0]
    except Exception:
        mau = 0
    try:
        churn_risk = conn.execute("SELECT COUNT(*) FROM users WHERE last_active<? AND last_active>0", (now_ts - 14 * 86400,)).fetchone()[0]
    except Exception:
        churn_risk = 0
    try:
        lost = conn.execute("SELECT COUNT(*) FROM users WHERE last_active<? AND last_active>0", (now_ts - 30 * 86400,)).fetchone()[0]
    except Exception:
        lost = 0
    trend = []
    try:
        for i in range(6, -1, -1):
            day_str = (datetime.now(_CST) - timedelta(days=i)).strftime("%Y-%m-%d")
            day_start = int(datetime.strptime(day_str, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            day_end = day_start + 86400
            cnt = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>=? AND last_active<?", (day_start, day_end)).fetchone()[0]
            trend.append({"date": day_str, "dau": cnt})
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    top_users = []
    try:
        rows = conn.execute("SELECT uid, name, group_messages, last_active FROM users ORDER BY group_messages DESC LIMIT 10").fetchall()
        for r in rows:
            top_users.append({"uid": r[0], "name": r[1] or "未知", "messages": r[2], "last_active": r[3]})
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    return jsonify({"ok": True, "data": {
        "total_users": total_users, "dau": dau, "wau": wau, "mau": mau,
        "churn_risk": churn_risk, "lost": lost,
        "dau_trend": trend, "top_users": top_users,
    }})


@stats_bp.route("/help/docs")
@login_required
def api_help_docs():
    """帮助文档"""
    docs = {
        "user_commands": [
            {"cmd": "直接发消息", "desc": "跟Mory聊天，自动回复", "example": "你好呀"},
            {"cmd": "签到", "desc": "每日签到领积分", "example": "签到"},
            {"cmd": "积分/排行榜", "desc": "查看积分和排名", "example": "排行榜"},
            {"cmd": "我的等级", "desc": "查看当前等级", "example": "我的等级"},
            {"cmd": "碎片寻宝", "desc": "猜暗号赢积分", "example": "碎片寻宝"},
            {"cmd": "塔罗牌", "desc": "抽一张塔罗牌", "example": "塔罗牌"},
            {"cmd": "叫醒服务 HH:MM", "desc": "设置叫醒时间", "example": "叫醒服务 07:30"},
            {"cmd": "👍👎按钮", "desc": "对Bot回复点反馈", "example": "点击Bot消息下方按钮"},
        ],
        "admin_commands": [
            {"section": "配置管理", "items": [
                {"cmd": "查看配置", "desc": "查看所有配置状态"},
                {"cmd": "设置概率 [0-100]", "desc": "修改群聊随机回复概率"},
                {"cmd": "开启/关闭 [功能名]", "desc": "开关功能（早安/晚安/新闻/签到等）"},
            ]},
            {"section": "人设与知识", "items": [
                {"cmd": "设置人设 [文本]", "desc": "修改机器人核心人设"},
                {"cmd": "投喂资料 [文本]", "desc": "追加业务知识库"},
                {"cmd": "学知识 [内容]", "desc": "让机器人学习新知识"},
                {"cmd": "忘记 [关键词]", "desc": "从知识库移除内容"},
            ]},
            {"section": "模型管理", "items": [
                {"cmd": "当前模型", "desc": "查看所有模型和当前使用"},
                {"cmd": "切换模型 [名称]", "desc": "手动切换AI模型"},
                {"cmd": "模型恢复 [模型名]", "desc": "从黑名单恢复模型"},
            ]},
            {"section": "群管理", "items": [
                {"cmd": "增加敏感词 [词]", "desc": "添加违禁词（支持批量，逗号分隔）"},
                {"cmd": "删除敏感词 [词]", "desc": "移除违禁词"},
                {"cmd": "增加反感词 [词]", "desc": "添加反感关键词"},
                {"cmd": "/blacklist @ID", "desc": "拉黑用户"},
                {"cmd": "/mute @ID 分钟", "desc": "禁言用户"},
                {"cmd": "健康检查", "desc": "一键诊断Bot运行状态"},
            ]},
            {"section": "动态进化", "items": [
                {"cmd": "加热词 [词汇...]", "desc": "给热词库追加新词汇"},
                {"cmd": "改风格 [描述]", "desc": "快速调整说话风格"},
                {"cmd": "进化 [指令]", "desc": "高级进化：直接修改任意配置项"},
            ]},
        ],
        "dashboard_guide": [
            {"page": "运行状态", "desc": "Bot运行状态、当前模型、黑名单等"},
            {"page": "模型总览", "desc": "6池模型状态、到期倒计时、三层路由"},
            {"page": "定时任务", "desc": "11项定时任务执行状态"},
            {"page": "群管设置", "desc": "敏感词/刷屏/禁言/欢迎语可视化管理"},
            {"page": "系统配置", "desc": "表单式配置编辑器+自然语言配置"},
            {"page": "用户反馈", "desc": "👍👎满意度统计"},
        ],
    }
    return jsonify({"ok": True, "data": docs})
