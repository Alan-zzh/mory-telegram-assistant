"""群聊设置模块
参考阿福后台：群聊设置
"""
import json
from datetime import datetime
from typing import Dict, Any

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

CHAT_SETTINGS_CONFIG = config.get('CHAT_SETTINGS_CONFIG', {
    'enabled': False,
})


class ChatSettingsModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def get_chat_settings(self, chat_id: int) -> Dict[str, Any]:
        if not CHAT_SETTINGS_CONFIG.get('enabled', False):
            return {}
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM chat_settings WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return self._get_default_settings()
        except Exception as e:
            logger.error(f"[群聊设置] 获取设置失败: {e}")
            return self._get_default_settings()

    def _get_default_settings(self) -> Dict[str, Any]:
        return {
            'welcome_enabled': True,
            'goodbye_enabled': True,
            'rules_enabled': True,
            'slow_mode_enabled': False,
            'slow_mode_seconds': 30,
            'pin_enabled': True,
            'auto_delete_enabled': False,
            'auto_delete_minutes': 60,
            'media_filter_enabled': False,
            'link_filter_enabled': False,
            'command_only_admins': False,
        }

    async def update_chat_settings(self, chat_id: int, settings: Dict[str, Any]) -> bool:
        if not CHAT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            current = await self.get_chat_settings(chat_id)
            current.update(settings)
            current['updated_at'] = datetime.now().isoformat()
            self._db.conn.execute(
                'INSERT OR REPLACE INTO chat_settings (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(current, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[群聊设置] 更新设置 chat={chat_id}")
            return True
        except Exception as e:
            logger.error(f"[群聊设置] 更新失败: {e}")
            return False

    async def set_slow_mode(self, chat_id: int, seconds: int) -> bool:
        if not CHAT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.set_chat_slow_mode(chat_id, seconds)
            await self.update_chat_settings(chat_id, {
                'slow_mode_enabled': True,
                'slow_mode_seconds': seconds,
            })
            logger.info(f"[群聊设置] 设置慢速模式 chat={chat_id}, seconds={seconds}")
            return True
        except Exception as e:
            logger.error(f"[群聊设置] 设置慢速模式失败: {e}")
            return False

    async def set_chat_photo(self, chat_id: int, photo_path: str) -> bool:
        if not CHAT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            with open(photo_path, 'rb') as photo_file:
                await self._compat.set_chat_photo(chat_id, photo_file)
            logger.info(f"[群聊设置] 设置头像 chat={chat_id}")
            return True
        except Exception as e:
            logger.error(f"[群聊设置] 设置头像失败: {e}")
            return False

    async def process(self, update):
        return None


chat_settings_module = ChatSettingsModule()