"""统计报表模块
参考阿福后台：消息统计、用户统计、活跃度统计
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

STATS_REPORT_CONFIG = config.get('STATS_REPORT_CONFIG', {
    'enabled': False,
})


class StatsReportModule:
    def __init__(self):
        self._db = None

    def get_message_stats(self, chat_id: int, days: int = 7) -> Dict[str, Any]:
        if not STATS_REPORT_CONFIG.get('enabled', False):
            return {}
        try:
            cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM message_logs WHERE chat_id = ? AND created_at > ?',
                (chat_id, cutoff_time)
            )
            row = cursor.fetchone()
            total_messages = row[0] if row else 0
            cursor = self._db.conn.execute(
                'SELECT COUNT(DISTINCT user_id) FROM message_logs WHERE chat_id = ? AND created_at > ?',
                (chat_id, cutoff_time)
            )
            row = cursor.fetchone()
            active_users = row[0] if row else 0
            return {
                'period': f'最近{days}天',
                'total_messages': total_messages,
                'active_users': active_users,
                'avg_messages_per_user': (total_messages / active_users) if active_users > 0 else 0,
            }
        except Exception as e:
            logger.error(f"[统计报表] 获取消息统计失败: {e}")
            return {}

    def get_user_stats(self, chat_id: int) -> Dict[str, Any]:
        if not STATS_REPORT_CONFIG.get('enabled', False):
            return {}
        try:
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM group_members WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            total_members = row[0] if row else 0
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM group_members WHERE chat_id = ? AND status = "active"',
                (chat_id,)
            )
            row = cursor.fetchone()
            active_members = row[0] if row else 0
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM group_members WHERE chat_id = ? AND joined_at > ?',
                (chat_id, (datetime.now() - timedelta(days=7)).isoformat())
            )
            row = cursor.fetchone()
            new_members = row[0] if row else 0
            return {
                'total_members': total_members,
                'active_members': active_members,
                'new_members_7days': new_members,
                'active_rate': (active_members / total_members * 100) if total_members > 0 else 0,
            }
        except Exception as e:
            logger.error(f"[统计报表] 获取用户统计失败: {e}")
            return {}

    def get_activity_stats(self, chat_id: int, hours: int = 24) -> Dict[str, Any]:
        if not STATS_REPORT_CONFIG.get('enabled', False):
            return {}
        try:
            cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM message_logs WHERE chat_id = ? AND created_at > ?',
                (chat_id, cutoff_time)
            )
            row = cursor.fetchone()
            recent_messages = row[0] if row else 0
            cursor = self._db.conn.execute(
                'SELECT COUNT(DISTINCT user_id) FROM message_logs WHERE chat_id = ? AND created_at > ?',
                (chat_id, cutoff_time)
            )
            row = cursor.fetchone()
            recent_users = row[0] if row else 0
            hourly_data = []
            for h in range(hours):
                start = (datetime.now() - timedelta(hours=hours - h)).isoformat()
                end = (datetime.now() - timedelta(hours=hours - h - 1)).isoformat()
                cursor = self._db.conn.execute(
                    'SELECT COUNT(*) FROM message_logs WHERE chat_id = ? AND created_at >= ? AND created_at < ?',
                    (chat_id, start, end)
                )
                row = cursor.fetchone()
                count = row[0] if row else 0
                hourly_data.append({'hour': h, 'count': count})
            return {
                'period': f'最近{hours}小时',
                'total_messages': recent_messages,
                'active_users': recent_users,
                'hourly_activity': hourly_data,
                'peak_hour': max(hourly_data, key=lambda x: x['count']) if hourly_data else {'hour': 0, 'count': 0},
            }
        except Exception as e:
            logger.error(f"[统计报表] 获取活跃度统计失败: {e}")
            return {}

    def get_daily_report(self, chat_id: int) -> Dict[str, Any]:
        if not STATS_REPORT_CONFIG.get('enabled', False):
            return {}
        return {
            'date': datetime.now().isoformat(),
            'message_stats': self.get_message_stats(chat_id, 1),
            'user_stats': self.get_user_stats(chat_id),
            'activity_stats': self.get_activity_stats(chat_id, 24),
        }

    async def process(self, update):
        return None


stats_report_module = StatsReportModule()