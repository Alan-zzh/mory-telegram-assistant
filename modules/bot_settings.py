"""机器人设置模块
参考阿福后台：机器人设置
"""
import json
from datetime import datetime
from typing import Dict, Any

from core.settings import config
from core.database import db_manager
from core.telebot_compat import TelebotCompat
from utils.logger import get_logger

logger = get_logger(__name__)

BOT_SETTINGS_CONFIG = config.get('BOT_SETTINGS_CONFIG', {
    'enabled': False,
    'bot_name': '',
    'description': '',
    'language': 'zh',
    'privacy_mode': False,
})


class BotSettingsModule:
    def __init__(self):
        self._db = db_manager
        self._compat = TelebotCompat.get_instance()

    async def get_bot_settings(self) -> Dict[str, Any]:
        if not BOT_SETTINGS_CONFIG.get('enabled', False):
            return {}
        try:
            cursor = self._db.conn.execute('SELECT data FROM bot_settings')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return self._get_default_settings()
        except Exception as e:
            logger.error(f"[机器人设置] 获取设置失败: {e}")
            return self._get_default_settings()

    def _get_default_settings(self) -> Dict[str, Any]:
        return {
            'bot_name': BOT_SETTINGS_CONFIG.get('bot_name', 'Mory小助理'),
            'description': BOT_SETTINGS_CONFIG.get('description', ''),
            'language': BOT_SETTINGS_CONFIG.get('language', 'zh'),
            'privacy_mode': BOT_SETTINGS_CONFIG.get('privacy_mode', False),
            'auto_restart': False,
            'log_level': 'INFO',
        }

    async def update_bot_settings(self, settings: Dict[str, Any]) -> bool:
        if not BOT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            current = await self.get_bot_settings()
            current.update(settings)
            current['updated_at'] = datetime.now().isoformat()
            self._db.conn.execute(
                'INSERT OR REPLACE INTO bot_settings (data) VALUES (?)',
                (json.dumps(current, ensure_ascii=False),)
            )
            self._db.conn.commit()
            logger.info(f"[机器人设置] 更新设置")
            return True
        except Exception as e:
            logger.error(f"[机器人设置] 更新失败: {e}")
            return False

    async def set_bot_description(self, description: str) -> bool:
        if not BOT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.set_my_description(description)
            await self.update_bot_settings({'description': description})
            logger.info(f"[机器人设置] 设置描述")
            return True
        except Exception as e:
            logger.error(f"[机器人设置] 设置描述失败: {e}")
            return False

    async def set_bot_name(self, name: str) -> bool:
        if not BOT_SETTINGS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.set_my_name(name)
            await self.update_bot_settings({'bot_name': name})
            logger.info(f"[机器人设置] 设置名称: {name}")
            return True
        except Exception as e:
            logger.error(f"[机器人设置] 设置名称失败: {e}")
            return False

    async def process(self, update):
        return None


bot_settings_module = BotSettingsModule()