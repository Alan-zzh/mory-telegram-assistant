"""语言白名单模块
参考阿福后台：语言白名单
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

LANGUAGE_WHITELIST_CONFIG = config.get('LANGUAGE_WHITELIST_CONFIG', {
    'enabled': False,
    'whitelist': ['zh', 'en'],
    'delete_message': True,
    'delete_hint': '⚠️ 本群只允许使用中文和英文',
})


class LanguageWhitelistModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def check_message(self, chat_id: int, user_id: int, message_id: int, text: str) -> Dict[str, Any]:
        if not LANGUAGE_WHITELIST_CONFIG.get('enabled', False):
            return {'allowed': True}
        detected_lang = self._detect_language(text)
        allowed_langs = LANGUAGE_WHITELIST_CONFIG.get('whitelist', ['zh', 'en'])
        if detected_lang not in allowed_langs:
            if LANGUAGE_WHITELIST_CONFIG.get('delete_message', True):
                try:
                    await self._compat.delete_message(chat_id, message_id)
                except Exception as e:
                    # 删除失败必须留痕：Bot 被降权时白名单功能形同虚设且无迹可查
                    logger.error(f"[语言白名单] 删除违规消息失败（功能可能未生效）chat={chat_id} msg={message_id}: {e}")
            if LANGUAGE_WHITELIST_CONFIG.get('delete_hint'):
                await self._compat.send_message(chat_id, LANGUAGE_WHITELIST_CONFIG['delete_hint'])
            logger.info(f"[语言白名单] 删除非白名单语言消息 chat={chat_id}, user={user_id}, lang={detected_lang}")
            return {'allowed': False, 'detected_language': detected_lang}
        return {'allowed': True, 'detected_language': detected_lang}

    def _detect_language(self, text: str) -> str:
        import re
        chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        if chinese_chars > english_chars:
            return 'zh'
        elif english_chars > chinese_chars:
            return 'en'
        elif chinese_chars == 0 and english_chars == 0:
            return 'other'
        return 'zh'

    def set_whitelist(self, chat_id: int, languages: List[str]) -> bool:
        if not LANGUAGE_WHITELIST_CONFIG.get('enabled', False):
            return False
        try:
            self._db.conn.execute(
                'INSERT OR REPLACE INTO language_whitelist (chat_id, languages) VALUES (?, ?)',
                (chat_id, json.dumps(languages))
            )
            self._db.conn.commit()
            logger.info(f"[语言白名单] 设置白名单 chat={chat_id}, languages={languages}")
            return True
        except Exception as e:
            logger.error(f"[语言白名单] 设置失败: {e}")
            return False

    def get_whitelist(self, chat_id: int) -> List[str]:
        try:
            cursor = self._db.conn.execute(
                'SELECT languages FROM language_whitelist WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[语言白名单] 获取失败: {e}")
        return LANGUAGE_WHITELIST_CONFIG.get('whitelist', ['zh', 'en'])

    async def process(self, update):
        return None


language_whitelist_module = LanguageWhitelistModule()