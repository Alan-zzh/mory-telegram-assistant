"""内容档案模块
参考阿福后台：内容档案功能，记录和管理群组内容
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

CONTENT_ARCHIVE_CONFIG = config.get('CONTENT_ARCHIVE_CONFIG', {
    'enabled': False,
    'archive_types': ['text', 'image', 'file', 'link'],
    'max_days': 30,
    'auto_clean_enabled': True,
    'clean_interval_hours': 24,
})


class ContentArchiveModule:
    def __init__(self):
        self._db = None
        self._last_clean: Dict[int, datetime] = {}

    def archive_message(self, chat_id: int, message_id: int,
                       content_type: str, content: str,
                       user_id: int, username: str = ''):
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return
        if content_type not in CONTENT_ARCHIVE_CONFIG.get('archive_types', []):
            return
        try:
            record = {
                'chat_id': chat_id,
                'message_id': message_id,
                'content_type': content_type,
                'content': content[:5000],
                'user_id': user_id,
                'username': username,
                'created_at': datetime.now().isoformat(),
            }
            self._save_archive(record)
            logger.debug(f"[内容档案] 归档 chat={chat_id}, type={content_type}")
        except Exception as e:
            logger.error(f"[内容档案] 归档失败: {e}")

    def get_archive(self, chat_id: int, content_type: str = None,
                    limit: int = 50) -> List[Dict[str, Any]]:
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return []
        try:
            return self._query_archive(chat_id, content_type, limit)
        except Exception as e:
            logger.error(f"[内容档案] 查询失败: {e}")
            return []

    def get_archive_stats(self, chat_id: int) -> Dict[str, Any]:
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return {}
        try:
            stats = {
                'total': 0,
                'by_type': {},
                'by_user': {},
            }
            cursor = self._db.conn.execute(
                'SELECT content_type, user_id, COUNT(*) FROM content_archive WHERE chat_id = ? GROUP BY content_type, user_id',
                (chat_id,)
            )
            for row in cursor.fetchall():
                content_type, user_id, count = row
                stats['total'] += count
                stats['by_type'][content_type] = stats['by_type'].get(content_type, 0) + count
                stats['by_user'][user_id] = stats['by_user'].get(user_id, 0) + count
            return stats
        except Exception as e:
            logger.error(f"[内容档案] 统计失败: {e}")
            return {}

    def search_archive(self, chat_id: int, keyword: str,
                       content_type: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return []
        try:
            query = 'SELECT data FROM content_archive WHERE chat_id = ? AND content LIKE ?'
            params = [chat_id, f'%{keyword}%']
            if content_type:
                query += ' AND content_type = ?'
                params.append(content_type)
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            cursor = self._db.conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))
            return results
        except Exception as e:
            logger.error(f"[内容档案] 搜索失败: {e}")
            return []

    def delete_archive(self, chat_id: int, message_id: int) -> bool:
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return False
        try:
            cursor = self._db.conn.execute(
                'DELETE FROM content_archive WHERE chat_id = ? AND message_id = ?',
                (chat_id, message_id)
            )
            self._db.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"[内容档案] 删除失败: {e}")
            return False

    def clean_old_archives(self, chat_id: int = None):
        if not CONTENT_ARCHIVE_CONFIG.get('enabled', False):
            return
        if not CONTENT_ARCHIVE_CONFIG.get('auto_clean_enabled', True):
            return
        max_days = CONTENT_ARCHIVE_CONFIG.get('max_days', 30)
        try:
            self._delete_old_archives(max_days, chat_id)
            logger.info(f"[内容档案] 清理 {max_days} 天前的数据")
        except Exception as e:
            logger.error(f"[内容档案] 清理失败: {e}")

    def _save_archive(self, record: Dict[str, Any]):
        try:
            record_json = json.dumps(record, ensure_ascii=False)
            # 修复 P2：原 INSERT 缺 created_at（INTEGER），导致 ORDER BY 和清理失效
            created_at = int(datetime.now().timestamp())
            self._db.conn.execute(
                'INSERT OR REPLACE INTO content_archive (chat_id, message_id, content_type, data, created_at) VALUES (?, ?, ?, ?, ?)',
                (record['chat_id'], record['message_id'], record['content_type'], record_json, created_at)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[内容档案] 保存失败: {e}")

    def _query_archive(self, chat_id: int, content_type: str, limit: int) -> List[Dict[str, Any]]:
        try:
            query = 'SELECT data FROM content_archive WHERE chat_id = ?'
            params = [chat_id]
            if content_type:
                query += ' AND content_type = ?'
                params.append(content_type)
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            cursor = self._db.conn.execute(query, params)
            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))
            return results
        except Exception as e:
            logger.error(f"[内容档案] 查询失败: {e}")
            return []

    def _delete_old_archives(self, max_days: int, chat_id: int = None):
        try:
            # 修复 P2：created_at 是 INTEGER（Unix 时间戳），不能用 ISO 字符串比较
            cutoff_time = int((datetime.now() - timedelta(days=max_days)).timestamp())
            if chat_id:
                self._db.conn.execute(
                    'DELETE FROM content_archive WHERE chat_id = ? AND created_at < ?',
                    (chat_id, cutoff_time)
                )
            else:
                self._db.conn.execute(
                    'DELETE FROM content_archive WHERE created_at < ?',
                    (cutoff_time,)
                )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[内容档案] 清理失败: {e}")

    async def process(self, update):
        return None


content_archive_module = ContentArchiveModule()