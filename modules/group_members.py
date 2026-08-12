"""群组成员管理模块
参考阿福后台：群组成员
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

GROUP_MEMBERS_CONFIG = config.get('GROUP_MEMBERS_CONFIG', {
    'enabled': False,
})


class GroupMembersModule:
    """Provide group member lookup and moderation actions."""
    def __init__(self):
        """Initialize module state and runtime adapters."""
        self._db = None
        self._compat = None

    async def get_members(self, chat_id: int, offset: int = 0, limit: int = 50,
                          search_query: str = '') -> Dict[str, Any]:
        """Return members matching optional filters."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return {'members': [], 'total': 0}
        try:
            all_members = await self._compat.get_chat_members(chat_id)
            filtered = []
            for member in all_members:
                user = member.user
                name = user.first_name or ''
                username = user.username or ''
                if search_query:
                    if search_query.lower() not in name.lower() and \
                       search_query.lower() not in username.lower():
                        continue
                filtered.append({
                    'user_id': user.id,
                    'first_name': name,
                    'last_name': user.last_name or '',
                    'username': username,
                    'status': member.status,
                    'is_bot': user.is_bot,
                })
            total = len(filtered)
            paginated = filtered[offset:offset + limit]
            return {
                'members': paginated,
                'total': total,
                'offset': offset,
                'limit': limit,
            }
        except Exception as e:
            logger.error(f"[群组成员] 获取成员失败: {e}")
            return {'members': [], 'total': 0}

    async def get_member_stats(self, chat_id: int) -> Dict[str, Any]:
        """Summarize member counts for a chat."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return {}
        try:
            all_members = await self._compat.get_chat_members(chat_id)
            bots = 0
            admins = 0
            members = 0
            for member in all_members:
                if member.user.is_bot:
                    bots += 1
                elif member.status in ['administrator', 'creator']:
                    admins += 1
                else:
                    members += 1
            return {
                'total': len(all_members),
                'bots': bots,
                'admins': admins,
                'members': members,
            }
        except Exception as e:
            logger.error(f"[群组成员] 获取统计失败: {e}")
            return {}

    async def kick_member(self, chat_id: int, user_id: int, reason: str = '') -> bool:
        """Kick a member from a chat."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.ban_chat_member(chat_id, user_id)
            await self._compat.unban_chat_member(chat_id, user_id)
            self._record_action(chat_id, user_id, 'kick', reason)
            logger.info(f"[群组成员] 踢出成员 chat={chat_id}, user={user_id}")
            return True
        except Exception as e:
            logger.error(f"[群组成员] 踢出失败: {e}")
            return False

    async def ban_member(self, chat_id: int, user_id: int, reason: str = '',
                         until_date: datetime = None) -> bool:
        """Ban a member from a chat."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.ban_chat_member(chat_id, user_id, until_date=until_date)
            self._record_action(chat_id, user_id, 'ban', reason)
            logger.info(f"[群组成员] 封禁成员 chat={chat_id}, user={user_id}")
            return True
        except Exception as e:
            logger.error(f"[群组成员] 封禁失败: {e}")
            return False

    async def unban_member(self, chat_id: int, user_id: int) -> bool:
        """Unban a member from a chat."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.unban_chat_member(chat_id, user_id)
            self._record_action(chat_id, user_id, 'unban', '')
            logger.info(f"[群组成员] 解封成员 chat={chat_id}, user={user_id}")
            return True
        except Exception as e:
            logger.error(f"[群组成员] 解封失败: {e}")
            return False

    async def mute_member(self, chat_id: int, user_id: int, duration_seconds: int) -> bool:
        """Mute a member for a configured duration."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return False
        try:
            from datetime import datetime, timedelta
            until_date = datetime.now() + timedelta(seconds=duration_seconds)
            await self._compat.restrict_chat_member(chat_id, user_id, until_date=until_date)
            self._record_action(chat_id, user_id, 'mute', f'duration={duration_seconds}')
            logger.info(f"[群组成员] 禁言成员 chat={chat_id}, user={user_id}, duration={duration_seconds}s")
            return True
        except Exception as e:
            logger.error(f"[群组成员] 禁言失败: {e}")
            return False

    async def unmute_member(self, chat_id: int, user_id: int) -> bool:
        """Remove a member's mute."""
        if not GROUP_MEMBERS_CONFIG.get('enabled', False):
            return False
        try:
            await self._compat.restrict_chat_member(chat_id, user_id)
            self._record_action(chat_id, user_id, 'unmute', '')
            logger.info(f"[群组成员] 解除禁言 chat={chat_id}, user={user_id}")
            return True
        except Exception as e:
            logger.error(f"[群组成员] 解除禁言失败: {e}")
            return False

    def _record_action(self, chat_id: int, user_id: int, action: str, reason: str):
        """Persist a moderation action."""
        try:
            action_record = {
                'user_id': user_id,
                'action': action,
                'reason': reason,
                'created_at': datetime.now().isoformat(),
            }
            cursor = self._db.conn.execute(
                'SELECT data FROM member_actions WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                actions = json.loads(row[0])
            else:
                actions = []
            actions.append(action_record)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO member_actions (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(actions, ensure_ascii=False))
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[群组成员] 记录操作失败: {e}")

    async def process(self, update):
        """Handle an update for this module."""
        return None


group_members_module = GroupMembersModule()
