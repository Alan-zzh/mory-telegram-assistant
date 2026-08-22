"""
tasks/analytics/weekly_report_task.py - 每周数据报告任务

每周一 9:30 向管理员私聊发送群+频道数据周报。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort, retry_task
from tasks.support.report_utils import pct, trend, fetch_member_count_with_db_fallback

logger = get_logger("tasks.analytics.weekly_report")

_CST = timezone(timedelta(hours=8))


class WeeklyReportTask(BaseTask):
    """每周数据报告任务（每周一 9:30 私聊发送）。"""

    @property
    def task_id(self) -> str:
        return "weekly_report"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "weekly_report",
            "trigger": "cron",
            "day_of_week": "mon",
            "hour": 9,
            "minute": 30,
            "params": {},
            "options": {
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 3600,
            },
        }]

    def execute(self, ctx: TaskContext) -> None:
        try:
            with TaskTransactionManager("weekly_report", ctx.rm.db, min_interval_sec=86400) as tx:
                if not tx.claimed:
                    return
                admin_id = ctx.rm.config.get("ADMIN_ID", 0)
                if not admin_id:
                    raise TaskAbort("ADMIN_ID为0")

                now = datetime.now(_CST)
                today = now.strftime("%Y-%m-%d")
                week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
                two_weeks_ago = (now - timedelta(days=14)).strftime("%Y-%m-%d")
                week_ago_ts = int((now - timedelta(days=7)).timestamp())
                now_ts = int(now.timestamp())

                self._send_weekly_group_report(ctx, admin_id, today, week_ago, two_weeks_ago)
                self._send_weekly_channel_report(ctx, admin_id, today, week_ago, week_ago_ts, now_ts)

                logger.info("✅ 每周数据报告已发送（群+频道）")
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"每周数据报告失败：{e}")
            retry_task(ctx.rm, lambda rm: WeeklyReportTask(rm).run(), "weekly_report")
            raise

    def _send_weekly_group_report(self, ctx: TaskContext, admin_id: int, today: str, week_ago: str, two_weeks_ago: str):
        """群数据周报：原始数据优先，再补充趋势分析，不做主观裁判。"""
        rm = ctx.rm
        gid = rm.config.get("GROUP_ID", 0)
        this_week = rm.db.get_weekly_group_stats(week_ago, today, chat_id=gid)
        last_week = rm.db.get_weekly_group_stats(two_weeks_ago, week_ago, chat_id=gid)

        total_members = fetch_member_count_with_db_fallback(rm, gid) if gid else 0

        activity_rate = (this_week.get("active_users", 0) / max(total_members, 1)) * 100
        row = rm.db.conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
            (week_ago, today, gid),
        ).fetchone()
        speech_total = row[0] if row else 0
        avg_msgs_per_active = (speech_total / max(this_week.get("active_users", 0), 1)) if this_week.get("active_users", 0) else 0
        if this_week["joined"] > 0:
            leave_join_ratio = f"{(this_week['left'] / this_week['joined']) * 100:.0f}%"
        elif this_week["left"] > 0:
            leave_join_ratio = f"无新增 / 离群{this_week['left']}"
        else:
            leave_join_ratio = "本周无入离群"

        data_source = "📊 自统计（事件追踪+校准）"

        html = f"""🏠 <b>群数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>本周群动态</b>
├ 入群：{this_week['joined']} {trend(this_week['joined'], last_week['joined'])}
├ 离群：{this_week['left']} {trend(this_week['left'], last_week['left'])}
├ 净增：{this_week['net']:+d} {trend(this_week['net'], last_week['net'])}
├ 当前成员：{total_members}
└ 群内发言：{speech_total}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
├ 活跃覆盖：{activity_rate:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
├ 离群/入群比：{leave_join_ratio}
└ 周均成员：{this_week['avg_members']}

━━━━━━━━━━━━━━━━━━

📈 <b>周环比</b>
├ 入群变化：{pct(this_week['joined'], last_week['joined'])}
├ 离群变化：{pct(this_week['left'], last_week['left'])}
└ 净增变化：{pct(this_week['net'], last_week['net'])}

━━━━━━━━━━━━━━━━━━

📉 <b>上周同期</b>
├ 入群{last_week['joined']}/离群{last_week['left']}/净增{last_week['net']:+d}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info("✅ 群周报已发送")

    def _send_weekly_channel_report(self, ctx: TaskContext, admin_id: int, today: str, week_ago: str, week_ago_ts: int, now_ts: int):
        """频道数据周报：先给真实统计，再补充触达和转发趋势。"""
        rm = ctx.rm
        channel_ids = rm.config.get("CHANNEL_IDS", [])
        if not channel_ids:
            return

        channel_lines = []
        stats_lines = []
        ops_lines = []
        total_posts = 0
        total_views = 0

        for ch in channel_ids:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

            ch_count = fetch_member_count_with_db_fallback(rm, cid)

            member_changes = rm.db.get_channel_weekly_member_changes(cid, week_ago, today)
            joined = member_changes["joined"]
            left = member_changes["left"]
            net = joined - left

            channel_lines.append(f"├ {cname}：{ch_count}人 周+{net:+d} (+{joined}/-{left})")

            db_stats = rm.db.get_channel_posts_in_range(cid, week_ago_ts, now_ts)
            posts = db_stats.get("posts", 0) if db_stats else 0
            views = db_stats.get("views", 0) if db_stats else 0
            forwards = db_stats.get("forwards", 0) if db_stats else 0
            stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")

            reach_rate = (views / max(ch_count, 1)) * 100
            interact_rate = (forwards / max(views, 1)) * 100
            ops_lines.append(f"├ {cname}：触达约{reach_rate:.0f}% 转发率{interact_rate:.1f}%")
            total_posts += posts
            total_views += views

        if channel_lines:
            channel_lines[-1] = channel_lines[-1].replace("├", "└", 1)
        if stats_lines:
            stats_lines[-1] = stats_lines[-1].replace("├", "└", 1)
        if ops_lines:
            ops_lines[-1] = ops_lines[-1].replace("├", "└", 1)

        data_source = "📊 Bot事件自统计 + Telegram实时人数"
        avg_views_per_post = (total_views / total_posts) if total_posts else 0

        html = f"""📢 <b>频道数据周报</b> · {week_ago} ~ {today}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道周数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 周总发帖：{total_posts}
└ 单帖均阅：{avg_views_per_post:.1f}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info("✅ 频道周报已发送 来源=Bot自统计")
