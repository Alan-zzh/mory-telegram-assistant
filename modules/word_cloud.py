"""词云模块
参考阿福后台：词云配置
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

WORD_CLOUD_CONFIG = config.get('WORD_CLOUD_CONFIG', {
    'enabled': False,
    'command': '获取词云',
    'auto_delete_seconds': 30,
    'background_color': '#ffffff',
    'word_colors': ['#333333', '#666666', '#999999'],
    'hourly_limit': 1,
})


class WordCloudModule:
    def __init__(self):
        self._db = None
        self._compat = None
        self._last_trigger: Dict[int, datetime] = {}

    async def generate_word_cloud(self, chat_id: int) -> Dict[str, Any]:
        if not WORD_CLOUD_CONFIG.get('enabled', False):
            return {}
        if not self._can_trigger(chat_id):
            return {'status': 'rate_limit'}
        try:
            messages = self._get_recent_messages(chat_id)
            word_counts = self._count_words(messages)
            word_cloud_data = {
                'words': word_counts,
                'background_color': WORD_CLOUD_CONFIG.get('background_color'),
                'word_colors': WORD_CLOUD_CONFIG.get('word_colors'),
                'generated_at': datetime.now().isoformat(),
            }
            self._save_word_cloud(chat_id, word_cloud_data)
            self._last_trigger[chat_id] = datetime.now()
            logger.info(f"[词云] 生成词云 chat={chat_id}, word_count={len(word_counts)}")
            return {'status': 'success', 'word_cloud': word_cloud_data}
        except Exception as e:
            logger.error(f"[词云] 生成失败: {e}")
            return {'status': 'error', 'error': 'internal_error'}

    def _can_trigger(self, chat_id: int) -> bool:
        last_time = self._last_trigger.get(chat_id)
        if last_time:
            diff = (datetime.now() - last_time).total_seconds()
            if diff < 3600:
                return False
        return True

    def _get_recent_messages(self, chat_id: int, limit: int = 1000) -> List[str]:
        try:
            cursor = self._db.conn.execute(
                'SELECT text FROM message_logs WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?',
                (chat_id, limit)
            )
            return [row[0] for row in cursor.fetchall() if row[0]]
        except Exception as e:
            logger.error(f"[词云] 获取消息失败: {e}")
            return []

    def _count_words(self, messages: List[str]) -> Dict[str, int]:
        import re
        word_counts = {}
        for msg in messages:
            words = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', msg)
            for word in words:
                if len(word) >= 2:
                    word_counts[word] = word_counts.get(word, 0) + 1
        return dict(sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:50])

    def _save_word_cloud(self, chat_id: int, word_cloud_data: Dict[str, Any]):
        try:
            data_json = json.dumps(word_cloud_data, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO word_cloud (chat_id, data) VALUES (?, ?)',
                (chat_id, data_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[词云] 保存失败: {e}")

    def get_last_word_cloud(self, chat_id: int) -> Dict[str, Any]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM word_cloud WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[词云] 获取失败: {e}")
        return {}

    async def process(self, update):
        return None


word_cloud_module = WordCloudModule()