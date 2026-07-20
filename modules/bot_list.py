"""机器人列表管理模块
参考阿福后台：机器人列表
"""
import json
from datetime import datetime
from typing import Dict, Any, List

from core.settings import config
from core.database import db_manager
from core.telebot_compat import TelebotCompat
from utils.logger import get_logger

logger = get_logger(__name__)

BOT_LIST_CONFIG = config.get('BOT_LIST_CONFIG', {
    'enabled': False,
})


class BotListModule:
    def __init__(self):
        self._db = db_manager
        self._compat = TelebotCompat.get_instance()

    async def get_bot_info(self) -> Dict[str, Any]:
        if not BOT_LIST_CONFIG.get('enabled', False):
            return {}
        try:
            me = await self._compat.get_me()
            return {
                'id': me.id,
                'first_name': me.first_name,
                'username': me.username,
                'is_bot': me.is_bot,
                'description': me.description or '',
            }
        except Exception as e:
            logger.error(f"[机器人列表] 获取机器人信息失败: {e}")
            return {}

    def register_bot(self, bot_info: Dict[str, Any]) -> bool:
        if not BOT_LIST_CONFIG.get('enabled', False):
            return False
        try:
            entry = {
                'bot_id': bot_info.get('id'),
                'first_name': bot_info.get('first_name', ''),
                'username': bot_info.get('username', ''),
                'description': bot_info.get('description', ''),
                'registered_at': datetime.now().isoformat(),
                'status': 'active',
            }
            cursor = self._db.conn.execute(
                'SELECT data FROM bot_registry'
            )
            row = cursor.fetchone()
            if row:
                bots = json.loads(row[0])
            else:
                bots = []
            bots.append(entry)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO bot_registry (data) VALUES (?)',
                (json.dumps(bots, ensure_ascii=False),)
            )
            self._db.conn.commit()
            logger.info(f"[机器人列表] 注册机器人: {bot_info.get('username')}")
            return True
        except Exception as e:
            logger.error(f"[机器人列表] 注册失败: {e}")
            return False

    def get_bot_list(self) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute('SELECT data FROM bot_registry')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[机器人列表] 获取列表失败: {e}")
        return []

    def update_bot_status(self, bot_id: int, status: str) -> bool:
        if not BOT_LIST_CONFIG.get('enabled', False):
            return False
        try:
            cursor = self._db.conn.execute('SELECT data FROM bot_registry')
            row = cursor.fetchone()
            if row:
                bots = json.loads(row[0])
                for bot in bots:
                    if bot.get('bot_id') == bot_id:
                        bot['status'] = status
                        bot['updated_at'] = datetime.now().isoformat()
                        break
                self._db.conn.execute(
                    'INSERT OR REPLACE INTO bot_registry (data) VALUES (?)',
                    (json.dumps(bots, ensure_ascii=False),)
                )
                self._db.conn.commit()
                logger.info(f"[机器人列表] 更新状态 bot={bot_id}, status={status}")
                return True
        except Exception as e:
            logger.error(f"[机器人列表] 更新状态失败: {e}")
        return False

    async def process(self, update):
        return None


bot_list_module = BotListModule()