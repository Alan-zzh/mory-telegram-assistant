"""
tasks/analytics/daily_report_task.py - 每日数据报告任务

每天 9:10 向管理员私聊发送群+频道数据日报。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort, retry_task

logger = get_logger("tasks.analytics.daily_report")

_CST = timezone(timedelta(hours=8))


def _format_zero_data(value, kind: str = "count") -> str:
    """0 值显示优化：发帖=0 时显示"暂无"，互动=0% 时显示"—"。"""
    if kind == "count":
        return "暂无" if value == 0 else str(value)
    if kind in ("percent", "ratio"):
        return "—" if value == 0 else f"{value:.1f}"
    return str(value)


class DailyReportTask(BaseTask):
    """每日数据报告任务（9:10 私聊发送）。"""

    @property
    def task_id(self) -> str:
        return "daily_report"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "daily_report",
            "trigger": "cron",
            "hour": 9,
            "minute": 10,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 60,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            with TaskTransactionManager("daily_report", ctx.rm.db, min_interval_sec=7200) as tx:
                if not tx.claimed:
                    return
                admin_id = ctx.rm.config.get("ADMIN_ID", 0)
                if not admin_id:
                    raise TaskAbort("ADMIN_ID为0")

                now = datetime.now(_CST)
                today = now.strftime("%Y-%m-%d")
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                gid = ctx.rm.config.get("GROUP_ID", 0)

                def trend(cur, prev):
                    if cur > prev:
                        return "📈"
                    if cur < prev:
                        return "📉"
                    return "➖"

                self._send_daily_group_report(ctx, admin_id, today, yesterday, gid, trend)
                self._send_daily_channel_report(ctx, admin_id, today, trend)

                logger.info("✅ 每日数据报告已发送（群+频道）")
        except TaskAbort:
            pass
        except Exception as e:
            logger.error(f"每日数据报告失败：{e}")
            retry_task(ctx.rm, lambda rm: DailyReportTask(rm).run(), "daily_report")

    def _send_daily_group_report(self, ctx: TaskContext, admin_id: int, today: str, yesterday: str, gid: int, trend_fn):
        """群数据日报：原始数据优先，分析后置，不做主观裁判。"""
        rm = ctx.rm
        token = rm.config.get("TOKEN", "")
        api_data = None
        use_api = False

        if token and gid:
            try:
                api_data = None
                if api_data:
                    use_api = True
                    logger.info("📊 群日报使用API数据")
            except Exception as e:
                logger.debug(f"getChatStatistics群失败: {e}")

        group_stats_today = rm.db.get_group_stats_by_date(today)
        group_stats_yesterday = rm.db.get_group_stats_by_date(yesterday)

        joined_today_db = left_today_db = net_today_db = 0
        for row in group_stats_today:
            if len(row) >= 6:
                joined_today_db += row[2] or 0
                left_today_db += row[3] or 0
                net_today_db += row[4] or 0

        joined_yest_db = left_yest_db = net_yest_db = 0
        for row in group_stats_yesterday:
            if len(row) >= 6:
                joined_yest_db += row[2] or 0
                left_yest_db += row[3] or 0
                net_yest_db += row[4] or 0

        if use_api and api_data:
            joined_today = max(api_data.get("growth_today", 0), 0)
            net_today = api_data.get("growth_today", 0)
            left_today = max(-net_today, 0) if net_today < 0 else 0
            total_members = api_data.get("current_count", 0)
            active_today = api_data.get("interactions_today", 0)
            msgs_today = api_data.get("messages_today", 0)
            if joined_today == 0 and left_today == 0 and net_today == 0 and (joined_today_db or left_today_db):
                joined_today = joined_today_db
                left_today = left_today_db
                net_today = net_today_db
                logger.info(f"📊 API数据为0，用自统计补充: 入群{joined_today} 离群{left_today}")
            data_source = "📡 Telegram官方统计"
        else:
            joined_today = joined_today_db
            left_today = left_today_db
            net_today = net_today_db
            total_members = 0
            if gid:
                try:
                    with rm.locked('bot'):
                        total_members = rm.bot.get_chat_member_count(gid)
                except Exception:
                    total_members = rm.db.get_group_total_members_latest(gid)
            active_today = rm.db.get_daily_active_users(today, gid)
            row = rm.db.conn.execute(
                "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date=? AND chat_id=?",
                (today, gid),
            ).fetchone()
            msgs_today = row[0] if row else 0
            data_source = "📊 自统计（事件追踪+校准）"

        joined_yest = joined_yest_db
        left_yest = left_yest_db
        net_yest = net_yest_db
        active_yest = rm.db.get_daily_active_users(yesterday, gid)
        row = rm.db.conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date=? AND chat_id=?",
            (yesterday, gid),
        ).fetchone()
        msgs_yest = row[0] if row else 0

        activity_rate = (active_today / max(total_members, 1)) * 100
        activity_rate_yest = (active_yest / max(total_members, 1)) * 100
        silence_ratio = ((total_members - active_today) / max(total_members, 1)) * 100
        avg_msgs_per_active = (msgs_today / max(active_today, 1)) if active_today else 0
        if joined_today > 0:
            flow_ratio = f"{(left_today / joined_today) * 100:.0f}%"
        elif left_today > 0:
            flow_ratio = f"无新增 / 离群{left_today}"
        else:
            flow_ratio = "当日无入离群"

        html = f"""🏠 <b>群数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>原始数据</b>
├ 今日入群：{joined_today} {trend_fn(joined_today, joined_yest)}
├ 今日离群：{left_today} {trend_fn(left_today, left_yest)}
├ 净增人数：{net_today:+d} {trend_fn(net_today, net_yest)}
├ 群成员数：{total_members}
├ 活跃互动：{active_today} {trend_fn(active_today, active_yest)}
└ 群内发言：{msgs_today} {trend_fn(msgs_today, msgs_yest)}

━━━━━━━━━━━━━━━━━━

📎 <b>数据分析</b>
├ 活跃覆盖：{activity_rate:.1f}% {trend_fn(activity_rate, activity_rate_yest)}
├ 沉默比例：{silence_ratio:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
└ 离群/入群比：{flow_ratio}

━━━━━━━━━━━━━━━━━━

🌙 <b>昨日同期</b>
├ 入群{joined_yest}/离群{left_yest}/净增{net_yest:+d}
├ 互动{active_yest}/发言{msgs_yest}
└ 活跃覆盖{activity_rate_yest:.1f}%"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info(f"✅ 群日报已发送: 入群{joined_today} 离群{left_today} 净增{net_today} 来源={'API' if use_api else '自统计'}")

    def _send_daily_channel_report(self, ctx: TaskContext, admin_id: int, today: str, trend_fn):
        """频道数据日报：真实数据优先，保留轻量分析，不做打分裁判。"""
        rm = ctx.rm
        channel_ids = rm.config.get("CHANNEL_IDS", [])
        if not channel_ids:
            return

        token = rm.config.get("TOKEN", "")
        yesterday = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        gid = rm.config.get("GROUP_ID", 0)

        channel_lines = []
        stats_lines = []
        ops_lines = []
        total_posts_today = 0
        total_views_today = 0
        total_forwards_today = 0
        total_channel_members = 0
        any_api = False

        for ch in channel_ids:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

            ch_count = 0
            try:
                with rm.locked('bot'):
                    ch_count = rm.bot.get_chat_member_count(cid)
            except Exception as e:
                logger.debug(f"频道成员数获取失败: {cname} err={e}")
                ch_count = rm.db.get_group_total_members_latest(cid)
            total_channel_members += ch_count

            ch_type = ch.get("type", "频道") if isinstance(ch, dict) else "频道"

            member_changes = rm.db.get_channel_member_changes(cid, yesterday, today)
            joined = member_changes["joined"]
            left = member_changes["left"]
            net = joined - left

            if joined > 0 or left > 0:
                channel_lines.append(f"├ {cname}：{ch_count}人 ({ch_type}) 今日+{joined}/-{left} 净{net:+d}")
            else:
                channel_lines.append(f"├ {cname}：{ch_count}人 ({ch_type}) 今日无变化")

            api_ch = None
            if token:
                try:
                    api_ch = None
                    if api_ch:
                        any_api = True
                except Exception as e:
                    logger.debug(f"获取频道统计API失败: {e}")

            yest_stats = rm.db.get_channel_daily_stats(cid, yesterday)
            posts_yest = yest_stats.get("posts", 0)
            views_yest = yest_stats.get("views", 0)

            posts_today = 0
            views_today = 0
            forwards_today = 0
            avg_views = 0
            has_data = False

            if api_ch:
                posts_today = api_ch.get("messages_today", 0)
                views_today = api_ch.get("views_today", 0)
                forwards_today = api_ch.get("forwards_today", 0)
                if posts_today == 0 and views_today == 0:
                    db_stats = rm.db.get_channel_daily_stats(cid, today)
                    posts_today = db_stats.get("posts", 0)
                    views_today = db_stats.get("views", 0)
                    forwards_today = rm.db.get_channel_post_stats(cid, today).get("forwards", 0)
                avg_views = views_today // max(posts_today, 1)
                has_data = posts_today > 0 or views_today > 0
            else:
                try:
                    today_stats = rm.db.get_channel_daily_stats(cid, today)
                    native_stats = rm.db.get_channel_post_stats(cid, today)
                    posts_today = today_stats.get("posts", 0)
                    views_today = today_stats.get("views", 0)
                    forwards_today = native_stats.get("forwards", 0)
                    avg_views = today_stats.get("avg_views", 0)
                    has_data = posts_today > 0 or views_today > 0
                except Exception as e:
                    logger.debug(f"频道统计获取失败: {cname} err={e}")

            total_posts_today += posts_today
            total_views_today += views_today
            total_forwards_today += forwards_today

            posts_str = _format_zero_data(posts_today, "count")
            views_str = _format_zero_data(views_today, "count")
            avg_views_str = "—" if avg_views == 0 else str(avg_views)

            stats_lines.append(
                f"├ {cname}："
                f"发帖{posts_str}{trend_fn(posts_today, posts_yest)} "
                f"浏览{views_str}{trend_fn(views_today, views_yest)} "
                f"均阅{avg_views_str}"
            )

            reach_rate = (views_today / max(ch_count, 1)) * 100
            interact_rate = (forwards_today / max(views_today, 1)) * 100
            hot_posts = rm.db.get_channel_top_posts(cid, today, threshold=2.0)

            reach_str = _format_zero_data(reach_rate, "percent")
            interact_str = _format_zero_data(interact_rate, "percent")

            ops_lines.append(
                f"├ {cname}：触达{reach_str}% 互动{interact_str}% 爆款{hot_posts}条"
            )

            if not has_data:
                logger.info(f"📊 频道 {cname} 当日无发帖/浏览数据，显示为'暂无'")

        if channel_lines:
            channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
        if stats_lines:
            stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
        if ops_lines:
            ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

        group_stats_today = rm.db.get_group_stats_by_date(today)
        net_group = 0
        for row in group_stats_today:
            if len(row) >= 6:
                net_group += row[4] or 0
        total_net = net_group + sum(
            rm.db.get_channel_member_changes(
                ch.get("id", 0) if isinstance(ch, dict) else ch, yesterday, today
            )["joined"] - rm.db.get_channel_member_changes(
                ch.get("id", 0) if isinstance(ch, dict) else ch, yesterday, today
            )["left"]
            for ch in channel_ids
        )
        total_reach_rate = (total_views_today / max(total_channel_members, 1)) * 100

        active_today = rm.db.get_daily_active_users(today)
        total_members_group = 0
        if gid:
            try:
                with rm.locked('bot'):
                    total_members_group = rm.bot.get_chat_member_count(gid)
            except Exception:
                total_members_group = rm.db.get_group_total_members_latest(gid)
        activity_rate = (active_today / max(total_members_group, 1)) * 100

        growth_note = f"全域净增 {total_net:+d}"
        avg_views_per_post = (total_views_today / total_posts_today) if total_posts_today else 0

        data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"

        html = f"""📢 <b>频道数据日报</b> · {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📈 <b>各频道概况</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📊 <b>原始数据</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

📎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 频道总触达：{total_reach_rate:.1f}%
├ 群活跃覆盖：{activity_rate:.1f}%
├ 单帖均阅：{avg_views_per_post:.1f}
└ 汇总：发帖{total_posts_today}条 / 浏览{total_views_today}次 / 转发{total_forwards_today}次 / {growth_note}"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info(f"✅ 频道日报已发送: 发帖{total_posts_today} 浏览{total_views_today} API={'是' if any_api else '否'}")
