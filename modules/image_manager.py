"""图片管理模块
参考阿福后台：管理群组图片，支持收藏、审核、清理
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

IMAGE_MANAGER_CONFIG = config.get('IMAGE_MANAGER_CONFIG', {
    'enabled': False,
    'max_images_per_user': 100,
    'auto_clean_days': 30,
    'auto_clean_enabled': True,
})


class ImageManagerModule:
    def __init__(self):
        self._db = None

    def record_image(self, chat_id: int, message_id: int,
                     user_id: int, file_id: str, file_unique_id: str):
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return
        try:
            record = {
                'chat_id': chat_id,
                'message_id': message_id,
                'user_id': user_id,
                'file_id': file_id,
                'file_unique_id': file_unique_id,
                'is_favorite': False,
                'is_approved': None,
                # 修复 P2：upload_time 表字段是 INTEGER，原存 ISO 字符串导致排序和清理失效
                'upload_time': int(datetime.now().timestamp()),
            }
            self._save_image(record)
            logger.debug(f"[图片管理] 记录图片 chat={chat_id}, user={user_id}")
        except Exception as e:
            logger.error(f"[图片管理] 记录失败: {e}")

    def favorite_image(self, chat_id: int, message_id: int, favorite: bool = True) -> bool:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return False
        try:
            self._update_favorite(chat_id, message_id, favorite)
            logger.info(f"[图片管理] {'收藏' if favorite else '取消收藏'} chat={chat_id}, msg={message_id}")
            return True
        except Exception as e:
            logger.error(f"[图片管理] 收藏失败: {e}")
            return False

    def approve_image(self, chat_id: int, message_id: int, approved: bool = True) -> bool:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return False
        try:
            self._update_approval(chat_id, message_id, approved)
            logger.info(f"[图片管理] {'审核通过' if approved else '审核拒绝'} chat={chat_id}, msg={message_id}")
            return True
        except Exception as e:
            logger.error(f"[图片管理] 审核失败: {e}")
            return False

    def get_favorites(self, chat_id: int) -> List[Dict[str, Any]]:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return []
        try:
            return self._query_favorites(chat_id)
        except Exception as e:
            logger.error(f"[图片管理] 查询失败: {e}")
            return []

    def get_pending_images(self, chat_id: int) -> List[Dict[str, Any]]:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return []
        try:
            return self._query_pending(chat_id)
        except Exception as e:
            logger.error(f"[图片管理] 查询待审核失败: {e}")
            return []

    def get_image_stats(self, chat_id: int) -> Dict[str, Any]:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return {}
        try:
            cursor = self._db.conn.execute(
                'SELECT COUNT(*), SUM(CASE WHEN is_favorite = 1 THEN 1 ELSE 0 END), '
                'SUM(CASE WHEN is_approved = 1 THEN 1 ELSE 0 END), '
                'SUM(CASE WHEN is_approved IS NULL THEN 1 ELSE 0 END) '
                'FROM image_records WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'total': row[0],
                    'favorites': row[1] or 0,
                    'approved': row[2] or 0,
                    'pending': row[3] or 0,
                }
            return {}
        except Exception as e:
            logger.error(f"[图片管理] 统计失败: {e}")
            return {}

    def clean_old_images(self, chat_id: int = None):
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return
        if not IMAGE_MANAGER_CONFIG.get('auto_clean_enabled', True):
            return
        days = IMAGE_MANAGER_CONFIG.get('auto_clean_days', 30)
        try:
            count = self._delete_old_images(days, chat_id)
            logger.info(f"[图片管理] 清理 {days} 天前的图片，共 {count} 张")
        except Exception as e:
            logger.error(f"[图片管理] 清理失败: {e}")

    def delete_image(self, chat_id: int, message_id: int) -> bool:
        if not IMAGE_MANAGER_CONFIG.get('enabled', False):
            return False
        try:
            cursor = self._db.conn.execute(
                'DELETE FROM image_records WHERE chat_id = ? AND message_id = ?',
                (chat_id, message_id)
            )
            self._db.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"[图片管理] 删除失败: {e}")
            return False

    def _save_image(self, record: Dict[str, Any]):
        try:
            record_json = json.dumps(record, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO image_records (chat_id, message_id, user_id, file_id, file_unique_id, data) VALUES (?, ?, ?, ?, ?, ?)',
                (record['chat_id'], record['message_id'], record['user_id'], record['file_id'], record['file_unique_id'], record_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[图片管理] 保存失败: {e}")

    def _update_favorite(self, chat_id: int, message_id: int, favorite: bool):
        try:
            self._db.conn.execute(
                'UPDATE image_records SET is_favorite = ? WHERE chat_id = ? AND message_id = ?',
                (1 if favorite else 0, chat_id, message_id)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[图片管理] 更新收藏失败: {e}")
            raise

    def _update_approval(self, chat_id: int, message_id: int, approved: bool):
        try:
            self._db.conn.execute(
                'UPDATE image_records SET is_approved = ? WHERE chat_id = ? AND message_id = ?',
                (1 if approved else 0, chat_id, message_id)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[图片管理] 更新审核失败: {e}")
            raise

    def _query_favorites(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM image_records WHERE chat_id = ? AND is_favorite = 1 ORDER BY upload_time DESC',
                (chat_id,)
            )
            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))
            return results
        except Exception as e:
            logger.error(f"[图片管理] 查询收藏失败: {e}")
            return []

    def _query_pending(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM image_records WHERE chat_id = ? AND is_approved IS NULL ORDER BY upload_time DESC',
                (chat_id,)
            )
            results = []
            for row in cursor.fetchall():
                results.append(json.loads(row[0]))
            return results
        except Exception as e:
            logger.error(f"[图片管理] 查询待审核失败: {e}")
            return []

    def _delete_old_images(self, days: int, chat_id: int) -> int:
        try:
            # 修复 P2：upload_time 是 INTEGER（Unix 时间戳），不能用 ISO 字符串比较
            cutoff_time = int((datetime.now() - timedelta(days=days)).timestamp())
            if chat_id:
                cursor = self._db.conn.execute(
                    'DELETE FROM image_records WHERE chat_id = ? AND upload_time < ?',
                    (chat_id, cutoff_time)
                )
            else:
                cursor = self._db.conn.execute(
                    'DELETE FROM image_records WHERE upload_time < ?',
                    (cutoff_time,)
                )
            self._db.conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"[图片管理] 删除旧图片失败: {e}")
            return 0

    async def process(self, update):
        return None


image_manager_module = ImageManagerModule()