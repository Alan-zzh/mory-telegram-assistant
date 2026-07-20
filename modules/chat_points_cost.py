"""聊天积分消耗模块
参考阿福后台：聊天积分消耗
"""
import json
from datetime import datetime
from typing import Dict, Any, List

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

CHAT_POINTS_COST_CONFIG = config.get('CHAT_POINTS_COST_CONFIG', {
    'enabled': False,
    'cost_per_message': 1,
    'min_points_required': 0,
    'daily_limit': 100,
    'free_messages_per_day': 10,
})


class ChatPointsCostModule:
    def __init__(self):
        self._db = None

    def check_and_deduct(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        if not CHAT_POINTS_COST_CONFIG.get('enabled', False):
            return {'allowed': True, 'message': '积分消耗未启用'}
        cost = CHAT_POINTS_COST_CONFIG.get('cost_per_message', 1)
        daily_limit = CHAT_POINTS_COST_CONFIG.get('daily_limit', 100)
        free_messages = CHAT_POINTS_COST_CONFIG.get('free_messages_per_day', 10)
        today = datetime.now().date().isoformat()
        today_usage = self._get_today_usage(chat_id, user_id)
        if today_usage < free_messages:
            self._record_usage(chat_id, user_id, 0)
            return {'allowed': True, 'message': '免费消息'}
        if today_usage >= daily_limit:
            return {'allowed': False, 'message': '今日消息已达上限'}
        current_points = self._get_user_points(user_id)
        if current_points < cost:
            return {'allowed': False, 'message': '积分不足'}
        self._deduct_points(user_id, cost)
        self._record_usage(chat_id, user_id, cost)
        logger.info(f"[聊天积分消耗] 消耗积分 chat={chat_id}, user={user_id}, cost={cost}")
        return {'allowed': True, 'message': f'消耗 {cost} 积分', 'cost': cost}

    def _get_user_points(self, user_id: int) -> int:
        try:
            cursor = self._db.conn.execute(
                'SELECT points FROM user_points WHERE user_id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"[聊天积分消耗] 获取积分失败: {e}")
            return 0

    def _deduct_points(self, user_id: int, amount: int):
        try:
            current = self._get_user_points(user_id)
            new_points = max(0, current - amount)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO user_points (user_id, points) VALUES (?, ?)',
                (user_id, new_points)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[聊天积分消耗] 扣减积分失败: {e}")

    def _get_today_usage(self, chat_id: int, user_id: int) -> int:
        today = datetime.now().date().isoformat()
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM chat_points_usage WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                usage_data = json.loads(row[0])
                key = f"{today}_{user_id}"
                return usage_data.get(key, 0)
        except Exception as e:
            logger.error(f"[聊天积分消耗] 获取今日使用失败: {e}")
        return 0

    def _record_usage(self, chat_id: int, user_id: int, cost: int):
        today = datetime.now().date().isoformat()
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM chat_points_usage WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                usage_data = json.loads(row[0])
            else:
                usage_data = {}
            key = f"{today}_{user_id}"
            usage_data[key] = usage_data.get(key, 0) + 1
            self._db.conn.execute(
                'INSERT OR REPLACE INTO chat_points_usage (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(usage_data))
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[聊天积分消耗] 记录使用失败: {e}")

    def get_user_stats(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        today = datetime.now().date().isoformat()
        today_usage = self._get_today_usage(chat_id, user_id)
        return {
            'today_messages': today_usage,
            'daily_limit': CHAT_POINTS_COST_CONFIG.get('daily_limit', 100),
            'free_messages': CHAT_POINTS_COST_CONFIG.get('free_messages_per_day', 10),
            'current_points': self._get_user_points(user_id),
            'cost_per_message': CHAT_POINTS_COST_CONFIG.get('cost_per_message', 1),
        }

    async def process(self, update):
        return None


chat_points_cost_module = ChatPointsCostModule()