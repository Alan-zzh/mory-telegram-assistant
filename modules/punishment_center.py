"""群管处罚中心模块
参考阿福后台：集中查看自动规则、刷屏治理、Guest Bot 和管理员命令产生的处罚记录
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

PUNISHMENT_CENTER_CONFIG = config.get('PUNISHMENT_CENTER_CONFIG', {
    'enabled': False,
})


class PunishmentCenterModule:
    def __init__(self):
        self._db = None

    def get_punishment_records(self, chat_id: int = None,
                               user_id: int = None,
                               action_type: str = None,
                               limit: int = 50) -> List[Dict[str, Any]]:
        if not PUNISHMENT_CENTER_CONFIG.get('enabled', False):
            return []
        try:
            query = 'SELECT data FROM punishment_records WHERE 1=1'
            params = []
            if chat_id:
                query += ' AND chat_id = ?'
                params.append(chat_id)
            if user_id:
                query += ' AND user_id = ?'
                params.append(user_id)
            if action_type:
                query += ' AND action_type = ?'
                params.append(action_type)
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            cursor = self._db.conn.execute(query, params)
            records = []
            for row in cursor.fetchall():
                records.append(json.loads(row[0]))
            return records
        except Exception as e:
            logger.error(f"[处罚中心] 查询失败: {e}")
            return []

    def add_punishment_record(self, chat_id: int, user_id: int,
                              username: str, nickname: str,
                              action_type: str, action: str,
                              reason: str = '', source: str = 'admin'):
        if not PUNISHMENT_CENTER_CONFIG.get('enabled', False):
            return
        try:
            record = {
                'chat_id': chat_id,
                'user_id': user_id,
                'username': username,
                'nickname': nickname,
                'action_type': action_type,
                'action': action,
                'reason': reason,
                'source': source,
                'created_at': datetime.now().isoformat(),
            }
            record_json = json.dumps(record, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT INTO punishment_records (chat_id, user_id, action_type, data) VALUES (?, ?, ?, ?)',
                (chat_id, user_id, action_type, record_json)
            )
            self._db.conn.commit()
            logger.info(f"[处罚中心] 添加记录: chat={chat_id}, user={user_id}, action={action}")
        except Exception as e:
            logger.error(f"[处罚中心] 添加记录失败: {e}")

    def get_punishment_stats(self, chat_id: int = None) -> Dict[str, Any]:
        if not PUNISHMENT_CENTER_CONFIG.get('enabled', False):
            return {}
        try:
            query = 'SELECT action_type, COUNT(*) FROM punishment_records'
            params = []
            if chat_id:
                query += ' WHERE chat_id = ?'
                params.append(chat_id)
            query += ' GROUP BY action_type'
            cursor = self._db.conn.execute(query, params)
            stats = {'by_type': {}, 'total': 0}
            for row in cursor.fetchall():
                stats['by_type'][row[0]] = row[1]
                stats['total'] += row[1]
            return stats
        except Exception as e:
            logger.error(f"[处罚中心] 统计失败: {e}")
            return {}

    def search_punishments(self, chat_id: int = None,
                           keyword: str = None,
                           limit: int = 50) -> List[Dict[str, Any]]:
        if not PUNISHMENT_CENTER_CONFIG.get('enabled', False):
            return []
        try:
            query = 'SELECT data FROM punishment_records WHERE 1=1'
            params = []
            if chat_id:
                query += ' AND chat_id = ?'
                params.append(chat_id)
            if keyword:
                query += ' AND (username LIKE ? OR nickname LIKE ? OR reason LIKE ?)'
                params.extend([f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'])
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            cursor = self._db.conn.execute(query, params)
            records = []
            for row in cursor.fetchall():
                records.append(json.loads(row[0]))
            return records
        except Exception as e:
            logger.error(f"[处罚中心] 搜索失败: {e}")
            return []

    async def process(self, update):
        return None


punishment_center_module = PunishmentCenterModule()
