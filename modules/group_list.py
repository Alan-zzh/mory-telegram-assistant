"""群组列表管理模块
参考阿福后台：群组列表
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

GROUP_LIST_CONFIG = config.get('GROUP_LIST_CONFIG', {
    'enabled': False,
})


class GroupListModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def get_groups(self, offset: int = 0, limit: int = 50,
                         search_query: str = '') -> Dict[str, Any]:
        if not GROUP_LIST_CONFIG.get('enabled', False):
            return {'groups': [], 'total': 0}
        try:
            all_groups = await self._compat.get_managed_groups()
            filtered = []
            for group in all_groups:
                title = group.title or ''
                if search_query and search_query.lower() not in title.lower():
                    continue
                filtered.append({
                    'chat_id': group.id,
                    'title': title,
                    'type': group.type,
                    'member_count': getattr(group, 'member_count', 0),
                    'username': getattr(group, 'username', ''),
                })
            total = len(filtered)
            paginated = filtered[offset:offset + limit]
            return {
                'groups': paginated,
                'total': total,
                'offset': offset,
                'limit': limit,
            }
        except Exception as e:
            logger.error(f"[群组列表] 获取群组失败: {e}")
            return {'groups': [], 'total': 0}

    async def get_group_detail(self, chat_id: int) -> Dict[str, Any]:
        if not GROUP_LIST_CONFIG.get('enabled', False):
            return {}
        try:
            group = await self._compat.get_chat(chat_id)
            return {
                'chat_id': group.id,
                'title': group.title or '',
                'type': group.type,
                'member_count': getattr(group, 'member_count', 0),
                'username': getattr(group, 'username', ''),
                'description': getattr(group, 'description', ''),
                'permissions': getattr(group, 'permissions', {}),
            }
        except Exception as e:
            logger.error(f"[群组列表] 获取群组详情失败: {e}")
            return {}

    def add_group_to_list(self, chat_id: int, title: str, group_type: str = 'group') -> bool:
        if not GROUP_LIST_CONFIG.get('enabled', False):
            return False
        try:
            entry = {
                'chat_id': chat_id,
                'title': title,
                'type': group_type,
                'added_at': datetime.now().isoformat(),
                'status': 'active',
            }
            # 修复 P0 数据丢失：固定 id=1 存储单条 JSON 数组
            cursor = self._db.conn.execute('SELECT data FROM group_registry WHERE id=1')
            row = cursor.fetchone()
            if row:
                groups = json.loads(row[0])
            else:
                groups = []
            existing = next((g for g in groups if g['chat_id'] == chat_id), None)
            if existing:
                existing.update(entry)
            else:
                groups.append(entry)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_registry (id, data) VALUES (1, ?)',
                (json.dumps(groups, ensure_ascii=False),)
            )
            self._db.conn.commit()
            logger.info(f"[群组列表] 添加群组: {chat_id} - {title}")
            return True
        except Exception as e:
            logger.error(f"[群组列表] 添加失败: {e}")
            return False

    def get_group_list(self) -> List[Dict[str, Any]]:
        try:
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM group_registry WHERE id=1')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[群组列表] 获取列表失败: {e}")
        return []

    async def leave_group(self, chat_id: int) -> bool:
        if not GROUP_LIST_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.leave_chat(chat_id)
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM group_registry WHERE id=1')
            row = cursor.fetchone()
            if row:
                groups = json.loads(row[0])
                groups = [g for g in groups if g['chat_id'] != chat_id]
                # 修复 P0：固定 id=1 写入
                self._db.conn.execute(
                    'INSERT OR REPLACE INTO group_registry (id, data) VALUES (1, ?)',
                    (json.dumps(groups, ensure_ascii=False),)
                )
                self._db.conn.commit()
            logger.info(f"[群组列表] 离开群组: {chat_id}")
            return True
        except Exception as e:
            logger.error(f"[群组列表] 离开失败: {e}")
            return False

    async def process(self, update):
        return None


group_list_module = GroupListModule()