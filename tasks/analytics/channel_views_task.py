"""
tasks/analytics/channel_views_task.py - 频道/群成员数统计与浏览量刷新

包含两个子任务：
  - channel_views: 每小时的 :25 更新群/频道成员数并校准群统计
  - refresh_channel_views: 每小时的 :40 刷新频道最近 10 条帖子浏览量
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

from core.helpers import can_delete_message
from core.logging_util import get_logger
from tasks.base_task import BaseTask, TaskContext

logger = get_logger("tasks.analytics.channel_views")

_CST = timezone(timedelta(hours=8))


class ChannelViewsTask(BaseTask):
    """频道/群成员数统计 + 频道帖子浏览量刷新。"""

    @property
    def task_id(self) -> str:
        return "channel_views"

    def schedule(self) -> List[Dict[str, Any]]:
        return [
            {
                "job_id": "channel_views",
                "trigger": "cron",
                "minute": 25,
                "params": {"action": "channel_views"},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 300,
                },
            },
            {
                "job_id": "refresh_channel_views",
                "trigger": "cron",
                "hour": "*/1",
                "minute": 40,
                "params": {"action": "refresh_channel_views"},
                "options": {
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": 3600,
                },
            },
        ]

    def execute(self, ctx: TaskContext) -> None:
        action = ctx.params.get("action", "channel_views")
        if action == "refresh_channel_views":
            self._refresh_channel_post_views(ctx)
        else:
            self._job_channel_views(ctx)

    def _job_channel_views(self, ctx: TaskContext):
        """频道/群成员数统计 + 校准 + 频道内容同步。"""
        rm = ctx.rm
        try:
            gid = rm.config.get("GROUP_ID", 0)

            if gid:
                try:
                    with rm.locked('bot'):
                        member_count = rm.bot.get_chat_member_count(gid)
                    rm.db.update_group_total_members(member_count, gid)
                    rm.db.calibrate_group_stats(gid, member_count)
                    logger.info(f"👥 群成员数更新: {member_count}")
                except Exception as e:
                    logger.debug(f"群成员数获取失败: {e}")

            channel_ids = rm.config.get("CHANNEL_IDS", [])
            if channel_ids:
                self._update_channel_member_counts(ctx, channel_ids)

            logger.info("✅ 成员数统计任务完成")
        except Exception as e:
            logger.error(f"成员数统计失败：{e}")

    def _update_channel_member_counts(self, ctx: TaskContext, channel_ids: list):
        """获取多频道成员数并写入数据库 + 记录快照。"""
        rm = ctx.rm
        snapshot_date = datetime.now(_CST).strftime("%Y-%m-%d-%H")
        for ch in channel_ids:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
            try:
                with rm.locked('bot'):
                    count = rm.bot.get_chat_member_count(cid)
                rm.db.update_group_total_members(count, cid)
                rm.db.record_channel_member_snapshot(cid, count, snapshot_date)
                logger.info(f"📊 频道成员数: {cname}={count}")
            except Exception as e:
                logger.debug(f"频道成员数获取失败: {cname} err={e}")

    def _refresh_channel_post_views(self, ctx: TaskContext):
        """定时刷新频道帖子浏览量：每小时对每个频道最近 10 条帖子获取最新 views。"""
        rm = ctx.rm
        channel_ids = rm.config.get("CHANNEL_IDS", [])
        admin_id = rm.config.get("ADMIN_ID", 0)
        if not channel_ids or not admin_id:
            return

        for ch in channel_ids:
            cid = ch.get("id", 0) if isinstance(ch, dict) else ch
            cname = ch.get("name", str(cid)) if isinstance(ch, dict) else str(cid)
            try:
                recent_posts = rm.db.get_channel_recent_posts(cid, limit=10)
                if not recent_posts:
                    continue
                for post in recent_posts:
                    msg_id = post["message_id"]
                    try:
                        with rm.locked('bot'):
                            fwd = rm.bot.forward_message(admin_id, cid, msg_id)
                            new_views = getattr(fwd, 'views', 0) or 0
                            new_forwards = getattr(fwd, 'forward_count', 0) or 0
                            if can_delete_message(rm.config):
                                try:
                                    rm.bot.delete_message(admin_id, fwd.message_id)
                                except Exception as e:
                                    logger.debug(f"删除转发消息失败: {e}")
                        if new_views > 0:
                            rm.db.update_channel_post_views(cid, msg_id, new_views, new_forwards)
                        time.sleep(1)
                    except Exception as e:
                        err_str = str(e)
                        if "429" in err_str or "Too Many Requests" in err_str:
                            logger.warning(f"⚠️ 频道浏览量刷新遇429限流，停止: {cname}")
                            return
                        logger.debug(f"频道帖子刷新失败: {cname} msg={msg_id} err={e}")
                logger.info(f"📺 频道浏览量刷新完成: {cname} {len(recent_posts)}条")
            except Exception as e:
                logger.debug(f"频道浏览量刷新异常: {cname} err={e}")
