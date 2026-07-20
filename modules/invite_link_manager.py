"""邀请链接管理模块
参考阿福后台：管理群组邀请链接
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

INVITE_LINK_CONFIG = config.get('INVITE_LINK_CONFIG', {
    'enabled': False,
})


class InviteLinkManagerModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def create_invite_link(self, chat_id: int, name: str = '',
                                 expire_date: int = None,
                                 member_limit: int = None,
                                 creates_join_request: bool = False) -> Dict[str, Any]:
        if not INVITE_LINK_CONFIG.get('enabled', False):
            return {}
        try:
            expire_date_obj = datetime.now() + timedelta(seconds=expire_date) if expire_date else None
            result = await self._compat.create_chat_invite_link(
                chat_id,
                name=name,
                expire_date=expire_date_obj,
                member_limit=member_limit,
                creates_join_request=creates_join_request,
            )
            link_info = {
                'invite_link': result.invite_link,
                'name': name,
                'expire_date': expire_date,
                'member_limit': member_limit,
                'creates_join_request': creates_join_request,
                'created_at': datetime.now().isoformat(),
                'uses': 0,
            }
            self._save_link(chat_id, link_info)
            logger.info(f"[邀请链接] 创建链接 chat={chat_id}, name={name}")
            return link_info
        except Exception as e:
            logger.error(f"[邀请链接] 创建失败: {e}")
            return {}

    async def revoke_invite_link(self, chat_id: int, invite_link: str) -> bool:
        if not INVITE_LINK_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.revoke_chat_invite_link(chat_id, invite_link)
            self._delete_link(chat_id, invite_link)
            logger.info(f"[邀请链接] 撤销链接 chat={chat_id}")
            return True
        except Exception as e:
            logger.error(f"[邀请链接] 撤销失败: {e}")
            return False

    def get_invite_links(self, chat_id: int) -> List[Dict[str, Any]]:
        if not INVITE_LINK_CONFIG.get('enabled', False):
            return []
        return self._load_links(chat_id)

    def get_link_by_name(self, chat_id: int, name: str) -> Dict[str, Any]:
        links = self.get_invite_links(chat_id)
        return next((l for l in links if l.get('name') == name), {})

    def track_link_use(self, chat_id: int, invite_link: str):
        if not INVITE_LINK_CONFIG.get('enabled', False):
            return
        try:
            links = self._load_links(chat_id)
            for link in links:
                if link.get('invite_link') == invite_link:
                    link['uses'] = link.get('uses', 0) + 1
                    self._save_links(chat_id, links)
                    break
        except Exception as e:
            logger.error(f"[邀请链接] 追踪使用失败: {e}")

    def get_link_stats(self, chat_id: int) -> Dict[str, Any]:
        if not INVITE_LINK_CONFIG.get('enabled', False):
            return {}
        links = self.get_invite_links(chat_id)
        total_uses = sum(l.get('uses', 0) for l in links)
        return {
            'total_links': len(links),
            'total_uses': total_uses,
            'links': links,
        }

    def _load_links(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM invite_links WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[邀请链接] 加载失败: {e}")
        return []

    def _save_link(self, chat_id: int, link_info: Dict[str, Any]):
        links = self._load_links(chat_id)
        links.append(link_info)
        self._save_links(chat_id, links)

    def _save_links(self, chat_id: int, links: List[Dict[str, Any]]):
        try:
            links_json = json.dumps(links, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO invite_links (chat_id, data) VALUES (?, ?)',
                (chat_id, links_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[邀请链接] 保存失败: {e}")

    def _delete_link(self, chat_id: int, invite_link: str):
        links = self._load_links(chat_id)
        links = [l for l in links if l.get('invite_link') != invite_link]
        self._save_links(chat_id, links)

    async def process(self, update):
        return None


invite_link_manager_module = InviteLinkManagerModule()