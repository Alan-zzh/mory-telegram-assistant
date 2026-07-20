"""新成员观察期模块
参考阿福后台：新成员观察期
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

NEW_MEMBER_PROBATION_CONFIG = config.get('NEW_MEMBER_PROBATION_CONFIG', {
    'enabled': False,
    'probation_minutes': 5,
    'auto_mute': True,
    'welcome_message': True,
    'notification': True,
})


class NewMemberProbationModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def on_new_member(self, chat_id: int, user_id: int, user_name: str) -> Dict[str, Any]:
        if not NEW_MEMBER_PROBATION_CONFIG.get('enabled', False):
            return {'status': 'disabled'}
        try:
            probation_end = datetime.now() + timedelta(minutes=NEW_MEMBER_PROBATION_CONFIG.get('probation_minutes', 5))
            self._add_probation(chat_id, user_id, probation_end)
            if NEW_MEMBER_PROBATION_CONFIG.get('auto_mute', True):
                await self._compat.restrict_chat_member(chat_id, user_id, until_date=probation_end)
            if NEW_MEMBER_PROBATION_CONFIG.get('welcome_message', True):
                await self._send_welcome(chat_id, user_name)
            logger.info(f"[新成员观察期] 添加观察期 chat={chat_id}, user={user_id}, end={probation_end}")
            return {
                'status': 'added',
                'user_id': user_id,
                'probation_end': probation_end.isoformat(),
            }
        except Exception as e:
            logger.error(f"[新成员观察期] 添加失败: {e}")
            return {'status': 'failed', 'error': 'internal_error'}

    def _add_probation(self, chat_id: int, user_id: int, probation_end: datetime):
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM probation_members WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                members = json.loads(row[0])
            else:
                members = []
            members.append({
                'user_id': user_id,
                'probation_end': probation_end.isoformat(),
                'added_at': datetime.now().isoformat(),
            })
            self._db.conn.execute(
                'INSERT OR REPLACE INTO probation_members (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(members, ensure_ascii=False))
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[新成员观察期] 记录失败: {e}")

    async def _send_welcome(self, chat_id: int, user_name: str):
        minutes = NEW_MEMBER_PROBATION_CONFIG.get('probation_minutes', 5)
        message = f"欢迎 {user_name} 加入本群！\n\n⏳ 您将进入 {minutes} 分钟观察期，请耐心等待。\n\n在此期间您将无法发送消息，请遵守群规。"
        await self._compat.send_message(chat_id, message)

    async def check_probation(self, chat_id: int, user_id: int) -> Dict[str, Any]:
        if not NEW_MEMBER_PROBATION_CONFIG.get('enabled', False):
            return {'in_probation': False}
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM probation_members WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if not row:
                return {'in_probation': False}
            members = json.loads(row[0])
            for member in members:
                if member['user_id'] == user_id:
                    probation_end = datetime.fromisoformat(member['probation_end'])
                    if datetime.now() < probation_end:
                        remaining = probation_end - datetime.now()
                        return {
                            'in_probation': True,
                            'remaining_seconds': int(remaining.total_seconds()),
                        }
                    else:
                        await self._end_probation(chat_id, user_id)
                        return {'in_probation': False}
            return {'in_probation': False}
        except Exception as e:
            logger.error(f"[新成员观察期] 检查失败: {e}")
            return {'in_probation': False}

    async def _end_probation(self, chat_id: int, user_id: int):
        try:
            await self._compat.restrict_chat_member(chat_id, user_id)
            cursor = self._db.conn.execute(
                'SELECT data FROM probation_members WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                members = json.loads(row[0])
                members = [m for m in members if m['user_id'] != user_id]
                self._db.conn.execute(
                    'INSERT OR REPLACE INTO probation_members (chat_id, data) VALUES (?, ?)',
                    (chat_id, json.dumps(members, ensure_ascii=False))
                )
                self._db.conn.commit()
            if NEW_MEMBER_PROBATION_CONFIG.get('notification', True):
                await self._compat.send_message(chat_id, f"🎉 观察期结束，欢迎正常发言！")
            logger.info(f"[新成员观察期] 结束观察期 chat={chat_id}, user={user_id}")
        except Exception as e:
            logger.error(f"[新成员观察期] 结束失败: {e}")

    async def process(self, update):
        return None


new_member_probation_module = NewMemberProbationModule()