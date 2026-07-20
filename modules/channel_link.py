"""关联频道管理模块
参考阿福后台：关联频道管理、消息转发设置
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

CHANNEL_LINK_CONFIG = config.get('CHANNEL_LINK_CONFIG', {
    'enabled': False,
})


class ChannelLinkModule:
    def __init__(self):
        self._db = None
        self._compat = None

    def add_link(self, chat_id: int, channel_id: int,
                 auto_forward: bool = True,
                 forward_to_channel: bool = False) -> bool:
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return False
        try:
            link_info = {
                'channel_id': channel_id,
                'auto_forward': auto_forward,
                'forward_to_channel': forward_to_channel,
                'created_at': datetime.now().isoformat(),
                'enabled': True,
            }
            self._save_link(chat_id, link_info)
            logger.info(f"[关联频道] 添加关联 chat={chat_id}, channel={channel_id}")
            return True
        except Exception as e:
            logger.error(f"[关联频道] 添加失败: {e}")
            return False

    def remove_link(self, chat_id: int, channel_id: int) -> bool:
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return False
        try:
            self._delete_link(chat_id, channel_id)
            logger.info(f"[关联频道] 移除关联 chat={chat_id}, channel={channel_id}")
            return True
        except Exception as e:
            logger.error(f"[关联频道] 移除失败: {e}")
            return False

    def get_links(self, chat_id: int) -> List[Dict[str, Any]]:
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return []
        return self._load_links(chat_id)

    def toggle_auto_forward(self, chat_id: int, channel_id: int, enabled: bool) -> bool:
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return False
        try:
            links = self._load_links(chat_id)
            for link in links:
                if link.get('channel_id') == channel_id:
                    link['auto_forward'] = enabled
                    self._save_links(chat_id, links)
                    logger.info(f"[关联频道] {'开启' if enabled else '关闭'}自动转发 chat={chat_id}, channel={channel_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[关联频道] 切换自动转发失败: {e}")
            return False

    async def forward_to_channel(self, chat_id: int, message_text: str):
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return
        links = self.get_links(chat_id)
        for link in links:
            if link.get('auto_forward', False) and link.get('enabled', False):
                try:
                    await self._compat.send_message(link['channel_id'], message_text)
                    logger.info(f"[关联频道] 转发消息 chat={chat_id} -> channel={link['channel_id']}")
                except Exception as e:
                    logger.error(f"[关联频道] 转发失败: {e}")

    async def broadcast_from_channel(self, channel_id: int, message_text: str):
        if not CHANNEL_LINK_CONFIG.get('enabled', False):
            return
        try:
            cursor = self._db.conn.execute(
                'SELECT chat_id, data FROM channel_link'
            )
            for row in cursor.fetchall():
                chat_id, data_json = row
                links = json.loads(data_json)
                for link in links:
                    if link.get('channel_id') == channel_id and link.get('forward_to_channel', False):
                        await self._compat.send_message(chat_id, message_text)
                        logger.info(f"[关联频道] 广播消息 channel={channel_id} -> chat={chat_id}")
        except Exception as e:
            logger.error(f"[关联频道] 广播失败: {e}")

    def _load_links(self, chat_id: int) -> List[Dict[str, Any]]:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM channel_link WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[关联频道] 加载失败: {e}")
        return []

    def _save_link(self, chat_id: int, link_info: Dict[str, Any]):
        links = self._load_links(chat_id)
        links.append(link_info)
        self._save_links(chat_id, links)

    def _save_links(self, chat_id: int, links: List[Dict[str, Any]]):
        try:
            links_json = json.dumps(links, ensure_ascii=False)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO channel_link (chat_id, data) VALUES (?, ?)',
                (chat_id, links_json)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[关联频道] 保存失败: {e}")

    def _delete_link(self, chat_id: int, channel_id: int):
        links = self._load_links(chat_id)
        links = [l for l in links if l.get('channel_id') != channel_id]
        self._save_links(chat_id, links)

    async def process(self, update):
        return None


channel_link_module = ChannelLinkModule()