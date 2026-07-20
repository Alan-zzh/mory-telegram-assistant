"""群组命令模块
参考阿福后台：群组命令
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

GROUP_COMMANDS_CONFIG = config.get('GROUP_COMMANDS_CONFIG', {
    'enabled': False,
    'custom_commands': {},
})


class GroupCommandsModule:
    def __init__(self):
        self._db = None

    def get_commands(self, chat_id: int) -> List[Dict[str, Any]]:
        if not GROUP_COMMANDS_CONFIG.get('enabled', False):
            return []
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM group_commands WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return self._get_default_commands()
        except Exception as e:
            logger.error(f"[群组命令] 获取命令失败: {e}")
            return self._get_default_commands()

    def _get_default_commands(self) -> List[Dict[str, Any]]:
        return [
            {'command': 'help', 'description': '显示帮助信息', 'admin_only': False},
            {'command': 'settings', 'description': '打开设置面板', 'admin_only': True},
            {'command': 'stats', 'description': '查看群统计', 'admin_only': False},
            {'command': 'warn', 'description': '警告用户', 'admin_only': True},
            {'command': 'ban', 'description': '封禁用户', 'admin_only': True},
            {'command': 'mute', 'description': '禁言用户', 'admin_only': True},
            {'command': 'unban', 'description': '解封用户', 'admin_only': True},
            {'command': 'kick', 'description': '踢出用户', 'admin_only': True},
        ]

    def add_command(self, chat_id: int, command: str, description: str, admin_only: bool = False) -> bool:
        if not GROUP_COMMANDS_CONFIG.get('enabled', False):
            return False
        try:
            commands = self.get_commands(chat_id)
            commands.append({
                'command': command,
                'description': description,
                'admin_only': admin_only,
                'created_at': datetime.now().isoformat(),
            })
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_commands (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(commands, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[群组命令] 添加命令 chat={chat_id}, command={command}")
            return True
        except Exception as e:
            logger.error(f"[群组命令] 添加失败: {e}")
            return False

    def remove_command(self, chat_id: int, command: str) -> bool:
        if not GROUP_COMMANDS_CONFIG.get('enabled', False):
            return False
        try:
            commands = self.get_commands(chat_id)
            commands = [c for c in commands if c['command'] != command]
            self._db.conn.execute(
                'INSERT OR REPLACE INTO group_commands (chat_id, data) VALUES (?, ?)',
                (chat_id, json.dumps(commands, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[群组命令] 删除命令 chat={chat_id}, command={command}")
            return True
        except Exception as e:
            logger.error(f"[群组命令] 删除失败: {e}")
            return False

    def is_admin_only(self, chat_id: int, command: str) -> bool:
        commands = self.get_commands(chat_id)
        cmd = next((c for c in commands if c['command'] == command), None)
        return cmd.get('admin_only', False) if cmd else False

    async def process(self, update):
        return None


group_commands_module = GroupCommandsModule()