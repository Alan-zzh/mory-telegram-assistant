"""强制关注频道模块
参考阿福后台：强制关注频道
"""
import json
from typing import Dict, Any, List

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

FORCE_CHANNEL_CONFIG = config.get('FORCE_CHANNEL_CONFIG', {
    'enabled': False,
    'channels': [],
    'kick_delay_seconds': 300,
    'warning_message': '⚠️ 请先关注 @channel_name 频道才能发言',
})


class ForceChannelModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def check_member(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        if not FORCE_CHANNEL_CONFIG.get('enabled', False):
            return {'allowed': True}
        channels = FORCE_CHANNEL_CONFIG.get('channels', [])
        for channel_id in channels:
            if not await self._is_member_of_channel(channel_id, user_id):
                return {'allowed': False, 'channel_id': channel_id}
        return {'allowed': True}

    async def _is_member_of_channel(self, channel_id: int, user_id: int) -> bool:
        try:
            member = await self._compat.get_chat_member(channel_id, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception:
            return False

    async def send_warning(self, chat_id: int, user_id: int, channel_id: int):
        if not FORCE_CHANNEL_CONFIG.get('enabled', False):
            return
        message = FORCE_CHANNEL_CONFIG.get('warning_message', '')
        channel_info = await self._compat.get_chat(channel_id)
        channel_name = getattr(channel_info, 'username', str(channel_id))
        message = message.replace('@channel_name', f'@{channel_name}')
        try:
            await self._compat.send_message(chat_id, message)
        except Exception as e:
            logger.error(f"[强制关注频道] 发送警告失败: {e}")

    async def kick_non_member(self, chat_id: int, user_id: int):
        if not FORCE_CHANNEL_CONFIG.get('enabled', False):
            return
        try:
            await self._compat.ban_chat_member(chat_id, user_id)
            logger.info(f"[强制关注频道] 踢出未关注用户 chat={chat_id}, user={user_id}")
        except Exception as e:
            logger.error(f"[强制关注频道] 踢出失败: {e}")

    def add_channel(self, chat_id: int, channel_id: int) -> bool:
        if not FORCE_CHANNEL_CONFIG.get('enabled', False):
            return False
        try:
            channels = self._get_channels(chat_id)
            if channel_id not in channels:
                channels.append(channel_id)
                self._save_channels(chat_id, channels)
                logger.info(f"[强制关注频道] 添加频道 chat={chat_id}, channel={channel_id}")
            return True
        except Exception as e:
            logger.error(f"[强制关注频道] 添加频道失败: {e}")
            return False

    def remove_channel(self, chat_id: int, channel_id: int) -> bool:
        if not FORCE_CHANNEL_CONFIG.get('enabled', False):
            return False
        try:
            channels = self._get_channels(chat_id)
            if channel_id in channels:
                channels.remove(channel_id)
                self._save_channels(chat_id, channels)
                logger.info(f"[强制关注频道] 移除频道 chat={chat_id}, channel={channel_id}")
            return True
        except Exception as e:
            logger.error(f"[强制关注频道] 移除频道失败: {e}")
            return False

    def _get_channels(self, chat_id: int) -> List[int]:
        try:
            cursor = self._db.conn.execute(
                'SELECT channels FROM force_channel WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[强制关注频道] 获取频道失败: {e}")
        return FORCE_CHANNEL_CONFIG.get('channels', [])

    def _save_channels(self, chat_id: int, channels: List[int]):
        try:
            channels_json = json.dumps(channels)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO force_channel (chat_id, channels) VALUES (?, ?)',
                (chat_id, channels_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[强制关注频道] 保存频道失败: {e}")

    async def process(self, update):
        return None


force_channel_module = ForceChannelModule()
