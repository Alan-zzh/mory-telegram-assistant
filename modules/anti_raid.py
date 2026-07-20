"""反突袭保护模块
参考阿福后台：开启防突袭、触发人数、统计窗口、防御时间、冷却时间、应急处理策略、新成员禁言时间、防突袭告警消息
"""
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from core.settings import config
from core.database import db_manager
from core.telebot_compat import TelebotCompat
from utils.logger import get_logger

logger = get_logger(__name__)

ANTI_RAID_CONFIG = config.get('ANTI_RAID_CONFIG', {
    'enabled': False,
    'trigger_member_count': 10,
    'stats_window_seconds': 30,
    'defense_duration_seconds': 600,
    'cooldown_seconds': 300,
    'emergency_strategy': 'mute_new_members',
    'new_member_mute_duration_seconds': 3600,
    'alert_message': '🚨 检测到突袭！已自动启用保护模式',
})


class AntiRaidModule:
    def __init__(self):
        self._db = None
        self._compat = None
        self._raid_active: Dict[int, bool] = {}
        self._last_raid_time: Dict[int, int] = {}

    async def check_raid(self, chat_id: int, new_member_count: int = 1) -> bool:
        if not ANTI_RAID_CONFIG.get('enabled', False):
            return False
        now = int(time.time())
        last_raid = self._last_raid_time.get(chat_id, 0)
        if (now - last_raid) < ANTI_RAID_CONFIG.get('cooldown_seconds', 300):
            return False
        window = ANTI_RAID_CONFIG.get('stats_window_seconds', 30)
        window_start = now - window
        count = self._count_recent_joins(chat_id, window_start) + new_member_count
        threshold = ANTI_RAID_CONFIG.get('trigger_member_count', 10)
        if count < threshold:
            return False
        await self._trigger_raid_protection(chat_id, count)
        return True

    async def _trigger_raid_protection(self, chat_id: int, count: int):
        logger.warning(f"🚨 突袭检测触发! chat={chat_id} count={count}")
        self._raid_active[chat_id] = True
        self._last_raid_time[chat_id] = int(time.time())
        defense_duration = ANTI_RAID_CONFIG.get('defense_duration_seconds', 600)
        unlock_time = datetime.now() + timedelta(seconds=defense_duration)
        strategy = ANTI_RAID_CONFIG.get('emergency_strategy', 'mute_new_members')
        if strategy == 'mute_new_members':
            await self._mute_new_members(chat_id)
        await self._send_alert(chat_id, count)
        self._db.set_system_state(f'raid_mode_{chat_id}', '1')
        self._db.set_system_state(f'raid_unlock_ts_{chat_id}', str(int(unlock_time.timestamp())))

    async def _mute_new_members(self, chat_id: int):
        mute_duration = ANTI_RAID_CONFIG.get('new_member_mute_duration_seconds', 3600)
        try:
            await self._compat.restrict_chat_members(chat_id, None, until_date=datetime.now() + timedelta(seconds=mute_duration))
            logger.info(f"[反突袭] 临时禁言新成员 chat={chat_id} duration={mute_duration}s")
        except Exception as e:
            logger.error(f"[反突袭] 禁言失败: {e}")

    async def _send_alert(self, chat_id: int, count: int):
        message = ANTI_RAID_CONFIG.get('alert_message', '🚨 检测到突袭！已自动启用保护模式')
        try:
            await self._compat.send_message(chat_id, message)
            logger.info(f"[反突袭] 发送告警 chat={chat_id}")
        except Exception as e:
            logger.error(f"[反突袭] 发送告警失败: {e}")

    def _count_recent_joins(self, chat_id: int, window_start: int) -> int:
        try:
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM group_join_log WHERE chat_id=? AND ts>?',
                (chat_id, window_start)
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"[反突袭] 统计失败: {e}")
            return 0

    def is_raid_active(self, chat_id: int) -> bool:
        if chat_id not in self._raid_active or not self._raid_active[chat_id]:
            return False
        unlock_ts_str = self._db.get_system_state(f'raid_unlock_ts_{chat_id}')
        if unlock_ts_str:
            try:
                unlock_ts = int(unlock_ts_str)
                if int(time.time()) >= unlock_ts:
                    self._raid_active[chat_id] = False
                    self._db.set_system_state(f'raid_mode_{chat_id}', '0')
                    return False
            except (ValueError, TypeError) as e:
                logger.error(f"[反突袭] 时间戳解析失败: {e}")
        return True

    async def deactivate_raid(self, chat_id: int):
        self._raid_active[chat_id] = False
        self._db.set_system_state(f'raid_mode_{chat_id}', '0')
        self._db.set_system_state(f'raid_unlock_ts_{chat_id}', '0')
        try:
            await self._compat.send_message(chat_id, '✅ 突袭警报已解除')
            logger.info(f"[反突袭] 手动解除 chat={chat_id}")
        except Exception as e:
            logger.error(f"[反突袭] 发送解除消息失败: {e}")

    async def get_status(self, chat_id: int) -> Dict[str, Any]:
        return {
            'enabled': ANTI_RAID_CONFIG.get('enabled', False),
            'active': self.is_raid_active(chat_id),
            'trigger_member_count': ANTI_RAID_CONFIG.get('trigger_member_count', 10),
            'stats_window_seconds': ANTI_RAID_CONFIG.get('stats_window_seconds', 30),
            'defense_duration_seconds': ANTI_RAID_CONFIG.get('defense_duration_seconds', 600),
            'cooldown_seconds': ANTI_RAID_CONFIG.get('cooldown_seconds', 300),
            'emergency_strategy': ANTI_RAID_CONFIG.get('emergency_strategy', 'mute_new_members'),
        }

    async def process(self, update):
        return None


anti_raid_module = AntiRaidModule()