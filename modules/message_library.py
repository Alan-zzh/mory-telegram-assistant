"""消息库模块
参考阿福后台：管理和复用常用消息模板，支持分类、搜索、快速发送
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

MESSAGE_LIBRARY_CONFIG = config.get('MESSAGE_LIBRARY_CONFIG', {
    'enabled': False,
    'default_category': 'default',
})


class MessageLibraryModule:
    def __init__(self):
        self._db = None
        self._compat = None
        self._messages: Dict[str, Dict[str, Any]] = {}

    def add_message(self, title: str, content: str, category: str = 'default') -> bool:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return False
        try:
            message = {
                'title': title,
                'content': content,
                'category': category,
                'created_at': datetime.now().isoformat(),
                'used_count': 0,
            }
            self._messages[title] = message
            self._save_message(message)
            logger.info(f"[消息库] 添加消息: {title}")
            return True
        except Exception as e:
            logger.error(f"[消息库] 添加失败: {e}")
            return False

    def update_message(self, title: str, content: str = None, category: str = None) -> bool:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return False
        if title not in self._messages:
            self._load_message(title)
        if title not in self._messages:
            return False
        try:
            message = self._messages[title]
            if content:
                message['content'] = content
            if category:
                message['category'] = category
            message['updated_at'] = datetime.now().isoformat()
            self._save_message(message)
            logger.info(f"[消息库] 更新消息: {title}")
            return True
        except Exception as e:
            logger.error(f"[消息库] 更新失败: {e}")
            return False

    def get_messages(self, category: str = None, keyword: str = None) -> List[Dict[str, Any]]:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return []
        try:
            return self._query_messages(category, keyword)
        except Exception as e:
            logger.error(f"[消息库] 查询失败: {e}")
            return []

    def get_message(self, title: str) -> Optional[str]:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return None
        if title not in self._messages:
            self._load_message(title)
        try:
            result = self._query_messages(title=title)
            return result[0].get('content') if result else None
        except Exception as e:
            logger.error(f"[消息库] 查询失败: {e}")
            return None

    def get_categories(self) -> List[str]:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return []
        try:
            cursor = self._db.conn.execute(
                'SELECT DISTINCT category FROM message_library'
            )
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[消息库] 获取分类失败: {e}")
            return []

    async def send_from_library(self, chat_id: int, title: str) -> bool:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return False
        content = self.get_message(title)
        if not content:
            return False
        try:
            await self._compat.send_message(chat_id, content)
            self._increment_used_count(title)
            logger.info(f"[消息库] 发送消息 {title} 到 chat={chat_id}")
            return True
        except Exception as e:
            logger.error(f"[消息库] 发送失败: {e}")
            return False

    async def send_by_category(self, chat_id: int, category: str) -> bool:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return False
        messages = self.get_messages(category=category)
        if not messages:
            return False
        try:
            for msg in messages:
                await self._compat.send_message(chat_id, msg.get('content', ''))
                self._increment_used_count(msg.get('title', ''))
            logger.info(f"[消息库] 发送分类 {category} 到 chat={chat_id}")
            return True
        except Exception as e:
            logger.error(f"[消息库] 发送分类失败: {e}")
            return False

    def delete_message(self, title: str) -> bool:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return False
        try:
            self._delete_message(title)
            self._messages.pop(title, None)
            logger.info(f"[消息库] 删除消息: {title}")
            return True
        except Exception as e:
            logger.error(f"[消息库] 删除失败: {e}")
            return False

    def get_message_stats(self) -> Dict[str, Any]:
        if not MESSAGE_LIBRARY_CONFIG.get('enabled', False):
            return {}
        try:
            cursor = self._db.conn.execute(
                'SELECT COUNT(*), SUM(used_count) FROM message_library'
            )
            row = cursor.fetchone()
            return {
                'total_messages': row[0] if row else 0,
                'total_used': row[1] if row and row[1] else 0,
            }
        except Exception as e:
            logger.error(f"[消息库] 统计失败: {e}")
            return {}

    def _save_message(self, message: Dict[str, Any]):
        try:
            message_json = json.dumps(message, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO message_library (title, category, data) VALUES (?, ?, ?)',
                (message['title'], message['category'], message_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[消息库] 保存失败: {e}")

    def _load_message(self, title: str):
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM message_library WHERE title = ?',
                (title,)
            )
            row = cursor.fetchone()
            if row:
                self._messages[title] = json.loads(row[0])
        except Exception as e:
            logger.error(f"[消息库] 加载失败: {e}")

    def _query_messages(self, category: str = None, keyword: str = None, title: str = None) -> List[Dict[str, Any]]:
        try:
            query = 'SELECT data FROM message_library'
            params = []
            conditions = []
            if title:
                conditions.append('title = ?')
                params.append(title)
            if category:
                conditions.append('category = ?')
                params.append(category)
            if keyword:
                conditions.append('(title LIKE ? OR content LIKE ?)')
                params.extend([f'%{keyword}%', f'%{keyword}%'])
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
            query += ' ORDER BY created_at DESC'
            cursor = self._db.conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))
            return results
        except Exception as e:
            logger.error(f"[消息库] 查询失败: {e}")
            return []

    def _delete_message(self, title: str):
        try:
            self._db.conn.execute(
                'DELETE FROM message_library WHERE title = ?',
                (title,)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[消息库] 删除失败: {e}")

    def _increment_used_count(self, title: str):
        try:
            if title in self._messages:
                self._messages[title]['used_count'] = self._messages[title].get('used_count', 0) + 1
            self._db.conn.execute(
                'UPDATE message_library SET used_count = used_count + 1 WHERE title = ?',
                (title,)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[消息库] 更新使用次数失败: {e}")

    async def process(self, update):
        return None


message_library_module = MessageLibraryModule()