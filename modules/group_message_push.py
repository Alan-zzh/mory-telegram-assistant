"""主动消息推送模块
参考阿福后台：向当前群组发送消息，支持富文本、图片、按钮和键盘
"""
from typing import Dict, Any, List, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

GROUP_MESSAGE_PUSH_CONFIG = config.get('GROUP_MESSAGE_PUSH_CONFIG', {
    'enabled': False,
})


class GroupMessagePushModule:
    def __init__(self):
        self._compat = None

    async def push_message(self, chat_id: int, text: str,
                           image_file_id: str = None,
                           buttons: List[Dict[str, Any]] = None,
                           keyboard: List[List[str]] = None,
                           parse_mode: str = 'HTML') -> Optional[str]:
        if not GROUP_MESSAGE_PUSH_CONFIG.get('enabled', False):
            return None
        try:
            if image_file_id:
                await self._compat.send_photo(chat_id, image_file_id, caption=text, parse_mode=parse_mode)
            else:
                await self._compat.send_message(chat_id, text, parse_mode=parse_mode)
            if buttons:
                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                inline_buttons = [
                    [InlineKeyboardButton(b.get('text', ''), url=b.get('url', ''), callback_data=b.get('callback', ''))]
                    for b in buttons
                ]
                await self._compat.send_message(chat_id, ' ', reply_markup=InlineKeyboardMarkup(inline_buttons))
            if keyboard:
                from telebot.types import ReplyKeyboardMarkup
                await self._compat.send_message(chat_id, ' ', reply_markup=ReplyKeyboardMarkup(keyboard))
            logger.info(f"[主动消息] 发送到 chat={chat_id}")
            return 'success'
        except Exception as e:
            logger.error(f"[主动消息] 发送失败 chat={chat_id}: {e}")
            return None

    async def push_broadcast(self, chat_ids: List[int], text: str,
                             image_file_id: str = None,
                             buttons: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not GROUP_MESSAGE_PUSH_CONFIG.get('enabled', False):
            return {'success': 0, 'failed': 0, 'results': []}
        success = 0
        failed = 0
        results = []
        for chat_id in chat_ids:
            result = await self.push_message(chat_id, text, image_file_id, buttons)
            if result == 'success':
                success += 1
            else:
                failed += 1
            results.append({'chat_id': chat_id, 'result': result})
        return {'success': success, 'failed': failed, 'results': results}

    async def push_to_all_groups(self, text: str,
                                 image_file_id: str = None,
                                 buttons: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not GROUP_MESSAGE_PUSH_CONFIG.get('enabled', False):
            return {'success': 0, 'failed': 0, 'results': []}
        try:
            from core.database import DB
            import os
            _db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mory.db')
            _db = DB(_db_path)
            cursor = _db.conn.execute('SELECT chat_id FROM groups')
            chat_ids = [row[0] for row in cursor.fetchall()]
            return await self.push_broadcast(chat_ids, text, image_file_id, buttons)
        except Exception as e:
            logger.error(f"[主动消息] 获取群组列表失败: {e}")
            return {'success': 0, 'failed': 0, 'results': []}

    async def process(self, update):
        return None


group_message_push_module = GroupMessagePushModule()