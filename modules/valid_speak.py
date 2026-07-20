"""有效发言模块
参考阿福后台：有效发言
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

VALID_SPEAK_CONFIG = config.get('VALID_SPEAK_CONFIG', {
    'enabled': False,
    'min_length': 3,
    'max_length': 1000,
    'blocked_patterns': [],
    'reward_points': 1,
})


class ValidSpeakModule:
    def __init__(self):
        self._db = None

    def check_valid(self, chat_id: int, user_id: int, text: str) -> Dict[str, Any]:
        if not VALID_SPEAK_CONFIG.get('enabled', False):
            return {'valid': True}
        length = len(text.strip())
        min_len = VALID_SPEAK_CONFIG.get('min_length', 3)
        max_len = VALID_SPEAK_CONFIG.get('max_length', 1000)
        if length < min_len:
            return {'valid': False, 'reason': 'too_short', 'min_length': min_len}
        if length > max_len:
            return {'valid': False, 'reason': 'too_long', 'max_length': max_len}
        blocked_patterns = VALID_SPEAK_CONFIG.get('blocked_patterns', [])
        for pattern in blocked_patterns:
            if pattern in text:
                return {'valid': False, 'reason': 'blocked_pattern', 'pattern': pattern}
        return {'valid': True, 'reason': 'ok'}

    def record_valid_speak(self, chat_id: int, user_id: int, text: str):
        if not VALID_SPEAK_CONFIG.get('enabled', False):
            return
        try:
            record = {
                'user_id': user_id,
                'text_length': len(text),
                'created_at': datetime.now().isoformat(),
            }
            records = self._load_records(chat_id)
            records.append(record)
            self._save_records(chat_id, records)
            logger.debug(f"[有效发言] 记录有效发言 chat={chat_id}, user={user_id}")
        except Exception as e:
            logger.error(f"[有效发言] 记录失败: {e}")

    def get_stats(self, chat_id: int, user_id: int = None, days: int = 7) -> Dict[str, Any]:
        if not VALID_SPEAK_CONFIG.get('enabled', False):
            return {}
        records = self._load_records(chat_id)
        cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()
        filtered = [r for r in records if r.get('created_at', '') > cutoff_time]
        if user_id:
            filtered = [r for r in filtered if r.get('user_id') == user_id]
        return {
            'total_valid_speaks': len(filtered),
            'period': f'最近{days}天',
        }

    def _load_records(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM valid_speak WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[有效发言] 加载记录失败: {e}")
        return []

    def _save_records(self, chat_id: int, records: List[Dict[str, Any]]):
        try:
            records_json = json.dumps(records, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO valid_speak (chat_id, data) VALUES (?, ?)',
                (chat_id, records_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[有效发言] 保存记录失败: {e}")

    async def process(self, update):
        return None


valid_speak_module = ValidSpeakModule()