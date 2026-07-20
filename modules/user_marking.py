"""用户标记模块
参考阿福后台：标记用户类型、标记管理、标记查询
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

USER_MARKING_CONFIG = config.get('USER_MARKING_CONFIG', {
    'enabled': False,
    'mark_types': ['广告', '骚扰', '优质', 'VIP', '黑名单', '白名单'],
})


class UserMarkingModule:
    def __init__(self):
        self._db = None
        self._marks: Dict[int, Dict[str, Any]] = {}

    def add_mark(self, user_id: int, mark_type: str, reason: str = '',
                 expires_at: str = None) -> bool:
        if not USER_MARKING_CONFIG.get('enabled', False):
            return False
        if mark_type not in USER_MARKING_CONFIG.get('mark_types', []):
            return False
        try:
            mark = {
                'mark_type': mark_type,
                'reason': reason,
                'created_at': datetime.now().isoformat(),
                'expires_at': expires_at,
                'active': True,
            }
            if user_id not in self._marks:
                self._marks[user_id] = []
            self._marks[user_id].append(mark)
            self._save_marks(user_id, self._marks[user_id])
            logger.info(f"[用户标记] 添加标记 user={user_id}, type={mark_type}")
            return True
        except Exception as e:
            logger.error(f"[用户标记] 添加标记失败: {e}")
            return False

    def remove_mark(self, user_id: int, mark_type: str) -> bool:
        if not USER_MARKING_CONFIG.get('enabled', False):
            return False
        try:
            marks = self._load_marks(user_id)
            marks = [m for m in marks if m.get('mark_type') != mark_type]
            self._save_marks(user_id, marks)
            self._marks[user_id] = marks
            logger.info(f"[用户标记] 移除标记 user={user_id}, type={mark_type}")
            return True
        except Exception as e:
            logger.error(f"[用户标记] 移除标记失败: {e}")
            return False

    def get_user_marks(self, user_id: int) -> List[Dict[str, Any]]:
        if not USER_MARKING_CONFIG.get('enabled', False):
            return []
        return self._load_marks(user_id)

    def has_mark(self, user_id: int, mark_type: str) -> bool:
        marks = self.get_user_marks(user_id)
        for mark in marks:
            if mark.get('mark_type') == mark_type and mark.get('active', True):
                expires_at = mark.get('expires_at')
                if expires_at:
                    if datetime.fromisoformat(expires_at) > datetime.now():
                        return True
                else:
                    return True
        return False

    def get_users_by_mark(self, mark_type: str) -> List[int]:
        if not USER_MARKING_CONFIG.get('enabled', False):
            return []
        try:
            cursor = self._db.conn.execute(
                'SELECT user_id, data FROM user_marks'
            )
            result = []
            for row in cursor.fetchall():
                user_id, data_json = row
                marks = json.loads(data_json)
                for mark in marks:
                    if mark.get('mark_type') == mark_type and mark.get('active', True):
                        expires_at = mark.get('expires_at')
                        if not expires_at or datetime.fromisoformat(expires_at) > datetime.now():
                            result.append(user_id)
                            break
            return result
        except Exception as e:
            logger.error(f"[用户标记] 查询标记失败: {e}")
            return []

    def get_mark_stats(self) -> Dict[str, Any]:
        if not USER_MARKING_CONFIG.get('enabled', False):
            return {}
        try:
            stats = {}
            for mark_type in USER_MARKING_CONFIG.get('mark_types', []):
                stats[mark_type] = len(self.get_users_by_mark(mark_type))
            return stats
        except Exception as e:
            logger.error(f"[用户标记] 统计失败: {e}")
            return {}

    def _load_marks(self, user_id: int) -> List[Dict[str, Any]]:
        if user_id in self._marks:
            return self._marks[user_id]
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM user_marks WHERE user_id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                marks = json.loads(row[0])
                self._marks[user_id] = marks
                return marks
        except Exception as e:
            logger.error(f"[用户标记] 加载标记失败: {e}")
        return []

    def _save_marks(self, user_id: int, marks: List[Dict[str, Any]]):
        try:
            marks_json = json.dumps(marks, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO user_marks (user_id, data) VALUES (?, ?)',
                (user_id, marks_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[用户标记] 保存标记失败: {e}")

    async def process(self, update):
        return None


user_marking_module = UserMarkingModule()