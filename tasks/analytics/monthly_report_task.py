"""
tasks/analytics/monthly_report_task.py - 每月数据报告任务

每月 1 日 9:30 向管理员私聊发送群+频道数据月报。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from core.logging_util import get_logger
from core.task_transaction import TaskTransactionManager
from tasks.base_task import BaseTask, TaskContext
from tasks.support.common import TaskAbort, retry_task

logger = get_logger("tasks.analytics.monthly_report")

_CST = timezone(timedelta(hours=8))


class MonthlyReportTask(BaseTask):
    """每月数据报告任务（每月 1 日 9:30 私聊发送）。"""

    @property
    def task_id(self) -> str:
        return "monthly_report"

    def schedule(self) -> List[Dict[str, Any]]:
        return [{
            "job_id": "monthly_report",
            "trigger": "cron",
            "day": 1,
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
            with TaskTransactionManager("monthly_report", ctx.rm.db, min_interval_sec=86400 * 28) as tx:
                if not tx.claimed:
                    return
                admin_id = ctx.rm.config.get("ADMIN_ID", 0)
                if not admin_id:
                    raise TaskAbort("ADMIN_ID为0")

                now = datetime.now(_CST)
                today = now.strftime("%Y-%m-%d")
                month_start = now.replace(day=1).strftime("%Y-%m-%d")
                if now.month == 1:
                    prev_month_start = now.replace(year=now.year - 1, month=12, day=1).strftime("%Y-%m-%d")
                else:
                    prev_month_start = now.replace(month=now.month - 1, day=1).strftime("%Y-%m-%d")

                self._send_monthly_group_report(ctx, admin_id, today, month_start, prev_month_start)
                self._send_monthly_channel_report(ctx, admin_id, today, month_start, prev_month_start)

                logger.info("✅ 每月数据报告已发送（群+频道）")
        except TaskAbort as exc:
            if exc.expected:
                return
            raise
        except Exception as e:
            logger.error(f"每月数据报告失败：{e}")
            retry_task(ctx.rm, lambda rm: MonthlyReportTask(rm).run(), "monthly_report")
            raise

    def _send_monthly_group_report(self, ctx: TaskContext, admin_id: int, today: str, month_start: str, prev_month_start: str):
        """群数据月报：原始数据优先，再补充趋势分析，不做主观裁判。"""
        rm = ctx.rm
        gid = rm.config.get("GROUP_ID", 0)
        this_month = rm.db.get_weekly_group_stats(month_start, today, chat_id=gid)
        last_month = rm.db.get_weekly_group_stats(prev_month_start, month_start, chat_id=gid)

        total_members = 0
        if gid:
            try:
                with rm.locked('bot'):
                    total_members = rm.bot.get_chat_member_count(gid)
            except Exception:
                total_members = rm.db.get_group_total_members_latest(gid)

        def pct(cur, prev):
            if prev == 0:
                return "🆕" if cur > 0 else "➖"
            diff = ((cur - prev) / prev) * 100
            if diff > 0:
                return f"📈+{diff:.0f}%"
            if diff < 0:
                return f"📉{diff:.0f}%"
            return "➖0%"

        def trend(cur, prev):
            if cur > prev:
                return "📈"
            if cur < prev:
                return "📉"
            return "➖"

        activity_rate = (this_month.get("active_users", 0) / max(total_members, 1)) * 100
        row = rm.db.conn.execute(
            "SELECT COALESCE(SUM(count),0) FROM speech_daily WHERE date>=? AND date<=? AND chat_id=?",
            (month_start, today, gid),
        ).fetchone()
        speech_total = row[0] if row else 0
        avg_msgs_per_active = (speech_total / max(this_month.get("active_users", 0), 1)) if this_month.get("active_users", 0) else 0
        if this_month["joined"] > 0:
            leave_join_ratio = f"{(this_month['left'] / this_month['joined']) * 100:.0f}%"
        elif this_month["left"] > 0:
            leave_join_ratio = f"无新增 / 离群{this_month['left']}"
        else:
            leave_join_ratio = "本月无入离群"

        data_source = "📊 自统计（事件追踪+校准）"
        month_display = month_start[:7]

        html = f"""🏠 <b>群数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>本月群动态</b>
├ 入群：{this_month['joined']} {trend(this_month['joined'], last_month['joined'])}
├ 离群：{this_month['left']} {trend(this_month['left'], last_month['left'])}
├ 净增：{this_month['net']:+d} {trend(this_month['net'], last_month['net'])}
├ 当前成员：{total_members}
└ 群内发言：{speech_total}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
├ 月活跃覆盖：{activity_rate:.1f}%
├ 人均发言：{avg_msgs_per_active:.1f}条
└ 离群/入群比：{leave_join_ratio}

━━━━━━━━━━━━━━━━━━

📈 <b>月环比</b>
├ 入群变化：{pct(this_month['joined'], last_month['joined'])}
├ 离群变化：{pct(this_month['left'], last_month['left'])}
└ 净增变化：{pct(this_month['net'], last_month['net'])}

━━━━━━━━━━━━━━━━━━

📉 <b>上月同期</b>
├ 入群{last_month['joined']}/离群{last_month['left']}/净增{last_month['net']:+d}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info("✅ 群月报已发送")

    def _send_monthly_channel_report(self, ctx: TaskContext, admin_id: int, today: str, month_start: str, prev_month_start: str):
        """频道数据月报：先给真实统计，再补充触达和转发趋势。"""
        rm = ctx.rm
        channel_ids = rm.config.get("CHANNEL_IDS", [])
        if not channel_ids:
            return

        token = rm.config.get("TOKEN", "")
        channel_lines = []
        stats_lines = []
        ops_lines = []
        any_api = False
        month_display = month_start[:7]
        total_posts = 0
        total_views = 0

        for ch in channel_ids:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)

            ch_count = 0
            try:
                with rm.locked('bot'):
                    ch_count = rm.bot.get_chat_member_count(cid)
            except Exception as e:
                logger.debug(f"频道月报获取失败: {cname} err={e}")
                ch_count = rm.db.get_group_total_members_latest(cid)

            member_changes = rm.db.get_channel_monthly_member_changes(cid, month_display)
            joined = member_changes["joined"]
            left = member_changes["left"]
            net = joined - left

            channel_lines.append(f"├ {cname}：{ch_count}人 月+{net:+d} (+{joined}/-{left})")

            month_start_ts = int(datetime.strptime(month_start, "%Y-%m-%d").replace(tzinfo=_CST).timestamp())
            now_ts = int(datetime.now(_CST).timestamp())

            api_ch = None
            if token:
                try:
                    api_ch = None
                    if api_ch:
                        any_api = True
                except Exception as e:
                    logger.debug(f"获取频道API数据失败: {e}")

            posts = 0
            views = 0
            forwards = 0

            if api_ch:
                posts = api_ch.get("messages_today", 0)
                views = api_ch.get("views_today", 0)
                forwards = api_ch.get("forwards_today", 0)
                stats_lines.append(f"├ {cname}：发帖{posts} 浏览{views} 转发{forwards}")
            else:
                db_stats = rm.db.get_channel_posts_in_range(cid, month_start_ts, now_ts)
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

        data_source = "📡 Telegram官方统计" if any_api else "📊 自统计"
        avg_views_per_post = (total_views / total_posts) if total_posts else 0

        html = f"""📢 <b>频道数据月报</b> · {month_display}

━━━━━━━━━━━━━━━━━━

📌 <b>数据来源</b>
└ {data_source}

━━━━━━━━━━━━━━━━━━

📊 <b>各频道月数据</b>
{chr(10).join(channel_lines)}

━━━━━━━━━━━━━━━━━━

📈 <b>发帖/浏览统计</b>
{chr(10).join(stats_lines)}

━━━━━━━━━━━━━━━━━━

🔎 <b>数据分析</b>
{chr(10).join(ops_lines)}
├ 月总发帖：{total_posts}
└ 单帖均阅：{avg_views_per_post:.1f}

━━━━━━━━━━━━━━━━━━
<i>Mory小助理</i>"""

        with rm.locked('bot'):
            rm.bot.send_message(admin_id, html, parse_mode="HTML")
        logger.info(f"✅ 频道月报已发送 API={'是' if any_api else '否'}")
