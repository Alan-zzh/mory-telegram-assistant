"""随机掉落模块
参考阿福后台：聊天中随机掉落奖励/道具/积分
"""
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

RANDOM_DROP_CONFIG = config.get('RANDOM_DROP_CONFIG', {
    'enabled': False,
    'drop_probability': 0.05,
    'min_interval_minutes': 5,
    'max_drops_per_day': 10,
    'drop_items': [
        {'name': '金币', 'type': 'points', 'amount': 10, 'message': '🎉 恭喜！你获得了 10 金币！'},
        {'name': '经验', 'type': 'exp', 'amount': 5, 'message': '🎁 恭喜！你获得了 5 经验！'},
        {'name': '道具', 'type': 'item', 'amount': 1, 'message': '✨ 恭喜！你获得了神秘道具！'},
    ],
    'chat_drop_enabled': False,
    'chat_drop_probability': 0.02,
    'chat_drop_min_messages': 20,
})


class RandomDropModule:
    def __init__(self):
        self._db = None
        self._compat = None
        self._user_drops: Dict[int, List[datetime]] = {}
        self._chat_messages: Dict[int, int] = {}

    async def check_drop(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        if not RANDOM_DROP_CONFIG.get('enabled', False):
            return None
        if random.random() > RANDOM_DROP_CONFIG.get('drop_probability', 0.05):
            return None
        now = datetime.now()
        user_drops = self._user_drops.get(user_id, [])
        user_drops = [d for d in user_drops if now - d < timedelta(days=1)]
        if len(user_drops) >= RANDOM_DROP_CONFIG.get('max_drops_per_day', 10):
            return None
        if user_drops and (now - user_drops[-1]) < timedelta(minutes=RANDOM_DROP_CONFIG.get('min_interval_minutes', 5)):
            return None
        items = RANDOM_DROP_CONFIG.get('drop_items', [])
        if not items:
            return None
        drop_item = random.choice(items)
        user_drops.append(now)
        self._user_drops[user_id] = user_drops
        try:
            text = drop_item.get('message', '🎉 恭喜！你获得了神秘奖励！')
            await self._compat.send_message(chat_id, text)
            self._apply_drop_reward(user_id, drop_item)
            logger.info(f"[随机掉落] 用户 {user_id} 获得: {drop_item.get('name', 'unknown')}")
            return drop_item
        except Exception as e:
            logger.error(f"[随机掉落] 发送失败: {e}")
            return None

    async def check_chat_drop(self, chat_id: int) -> Optional[Dict[str, Any]]:
        if not RANDOM_DROP_CONFIG.get('chat_drop_enabled', False):
            return None
        self._chat_messages[chat_id] = self._chat_messages.get(chat_id, 0) + 1
        if self._chat_messages[chat_id] % RANDOM_DROP_CONFIG.get('chat_drop_min_messages', 20) != 0:
            return None
        if random.random() > RANDOM_DROP_CONFIG.get('chat_drop_probability', 0.02):
            return None
        items = RANDOM_DROP_CONFIG.get('drop_items', [])
        if not items:
            return None
        drop_item = random.choice(items)
        try:
            text = f"🎊 群聊掉落！{drop_item.get('message', '神秘奖励')}"
            await self._compat.send_message(chat_id, text)
            logger.info(f"[群聊掉落] chat={chat_id} 掉落: {drop_item.get('name', 'unknown')}")
            return drop_item
        except Exception as e:
            logger.error(f"[群聊掉落] 发送失败: {e}")
            return None

    def get_user_drop_stats(self, user_id: int) -> Dict[str, Any]:
        if not RANDOM_DROP_CONFIG.get('enabled', False):
            return {}
        now = datetime.now()
        user_drops = self._user_drops.get(user_id, [])
        today_drops = [d for d in user_drops if d.date() == now.date()]
        return {
            'total_drops': len(user_drops),
            'today_drops': len(today_drops),
        }

    def reset_daily_drops(self):
        now = datetime.now()
        for user_id in list(self._user_drops.keys()):
            self._user_drops[user_id] = [d for d in self._user_drops[user_id] if now - d < timedelta(days=1)]

    def _apply_drop_reward(self, user_id: int, item: Dict[str, Any]):
        item_type = item.get('type', '')
        amount = item.get('amount', 0)
        if item_type == 'points':
            self._add_points(user_id, amount)
        elif item_type == 'exp':
            self._add_exp(user_id, amount)
        elif item_type == 'item':
            self._add_item(user_id, item.get('name', 'unknown'))

    def _add_points(self, user_id: int, amount: int):
        try:
            self._db.conn.execute(
                'INSERT OR REPLACE INTO user_points (user_id, points) VALUES (?, COALESCE((SELECT points FROM user_points WHERE user_id = ?), 0) + ?)',
                (user_id, user_id, amount)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[随机掉落] 添加积分失败: {e}")

    def _add_exp(self, user_id: int, amount: int):
        try:
            self._db.conn.execute(
                'INSERT OR REPLACE INTO user_exp (user_id, exp) VALUES (?, COALESCE((SELECT exp FROM user_exp WHERE user_id = ?), 0) + ?)',
                (user_id, user_id, amount)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[随机掉落] 添加经验失败: {e}")

    def _add_item(self, user_id: int, item_name: str):
        try:
            self._db.conn.execute(
                'INSERT INTO user_items (user_id, item_name, obtained_at) VALUES (?, ?, ?)',
                (user_id, item_name, datetime.now().isoformat())
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[随机掉落] 添加道具失败: {e}")

    async def process(self, update):
        return None


random_drop_module = RandomDropModule()