"""入群相关模块
参考阿福后台：入群相关
"""
import json
from datetime import datetime
from typing import Dict, Any

from core.logging_util import get_logger
from core.settings import get_config

try:
    config = get_config()
except Exception:
    config = {}
logger = get_logger(__name__)

JOIN_SETTINGS_CONFIG = config.get('JOIN_SETTINGS_CONFIG', {
    'enabled': False,
    'approval_required': False,
    'captcha_enabled': True,
    'captcha_type': 'button',
    'welcome_message': True,
    'welcome_template': '欢迎 {name} 加入本群！请遵守群规。',
    'auto_kick_non_member': False,
    'max_join_per_hour': 10,
})


class JoinSettingsModule:
    def __init__(self):
        self._db = None
        self._compat = None

    async def on_new_member(self, chat_id: int, user_id: int, user_name: str) -> Dict[str, Any]:
        if not JOIN_SETTINGS_CONFIG.get('enabled', False):
            return {'status': 'disabled'}
        try:
            await self._record_join(chat_id, user_id)
            if JOIN_SETTINGS_CONFIG.get('approval_required', False):
                await self._request_approval(chat_id, user_id, user_name)
                return {'status': 'pending_approval'}
            if JOIN_SETTINGS_CONFIG.get('captcha_enabled', True):
                await self._send_captcha(chat_id, user_id)
                return {'status': 'captcha_required'}
            if JOIN_SETTINGS_CONFIG.get('welcome_message', True):
                await self._send_welcome(chat_id, user_name)
            return {'status': 'approved'}
        except Exception as e:
            logger.error(f"[入群相关] 处理新成员失败: {e}")
            return {'status': 'failed', 'error': 'internal_error'}

    def _record_join(self, chat_id: int, user_id: int):
        try:
            entry = {
                'user_id': user_id,
                'joined_at': datetime.now().isoformat(),
                'status': 'approved',
            }
            cursor = self._db.conn.execute(
                'SELECT data FROM join_records WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                records = json.loads(row[0])
            else:
                records = []
            records.append(entry)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO join_records (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(records, ensure_ascii=False))
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[入群相关] 记录入群失败: {e}")

    async def _request_approval(self, chat_id: int, user_id: int, user_name: str):
        message = f"🔍 新成员等待审核\n用户名: {user_name}\n用户ID: {user_id}\n\n请管理员审核通过或拒绝。"
        admins = await self._compat.get_chat_administrators(chat_id)
        for admin in admins:
            try:
                await self._compat.send_message(admin.user.id, message)
            except Exception:
                pass

    async def _send_captcha(self, chat_id: int, user_id: int):
        captcha_type = JOIN_SETTINGS_CONFIG.get('captcha_type', 'button')
        if captcha_type == 'button':
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton('✅ 我不是机器人', callback_data=f'captcha_verify_{user_id}'))
            await self._compat.send_message(chat_id, '请验证您不是机器人:', reply_markup=markup)

    async def _send_welcome(self, chat_id: int, user_name: str):
        template = JOIN_SETTINGS_CONFIG.get('welcome_template', '欢迎 {name} 加入本群！')
        message = template.format(name=user_name)
        await self._compat.send_message(chat_id, message)

    def check_join_rate_limit(self, chat_id: int) -> bool:
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM join_records WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                records = json.loads(row[0])
                from datetime import datetime, timedelta
                one_hour_ago = datetime.now() - timedelta(hours=1)
                recent_joins = [r for r in records if datetime.fromisoformat(r['joined_at']) > one_hour_ago]
                max_join = JOIN_SETTINGS_CONFIG.get('max_join_per_hour', 10)
                return len(recent_joins) < max_join
        except Exception as e:
            logger.error(f"[入群相关] 检查入群频率失败: {e}")
        return True

    async def process(self, update):
        return None


join_settings_module = JoinSettingsModule()