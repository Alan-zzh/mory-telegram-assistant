"""群安全中心模块
参考阿福后台：集中查看安全状态、机器人权限、规则健康、近期风险和下一步处理入口
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

GROUP_SAFETY_CENTER_CONFIG = config.get('GROUP_SAFETY_CENTER_CONFIG', {
    'enabled': False,
})


class GroupSafetyCenterModule:
    def __init__(self):
        self._db = None

    def get_safety_status(self, chat_id: int) -> Dict[str, Any]:
        if not GROUP_SAFETY_CENTER_CONFIG.get('enabled', False):
            return {}
        return {
            'security_level': self._get_security_level(chat_id),
            'bot_permissions': self._get_bot_permissions(chat_id),
            'rules_health': self._get_rules_health(chat_id),
            'recent_risks': self._get_recent_risks(chat_id),
            'next_actions': self._get_next_actions(chat_id),
        }

    def _get_security_level(self, chat_id: int) -> str:
        try:
            recent_alerts = self._count_recent_alerts(chat_id)
            if recent_alerts >= 10:
                return '高风险'
            elif recent_alerts >= 5:
                return '中风险'
            elif recent_alerts >= 1:
                return '低风险'
            return '安全'
        except Exception:
            return '未知'

    def _get_bot_permissions(self, chat_id: int) -> Dict[str, bool]:
        try:
            cursor = self._db.conn.execute(
                'SELECT key, value FROM group_configs WHERE chat_id = ? AND key LIKE "perm_%"',
                (chat_id,)
            )
            permissions = {}
            for row in cursor.fetchall():
                permissions[row[0]] = json.loads(row[1]) if row[1] else False
            return permissions
        except Exception:
            return {}

    def _get_rules_health(self, chat_id: int) -> Dict[str, Any]:
        try:
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM auto_rules WHERE chat_id = ? AND enabled = 1',
                (chat_id,)
            )
            row = cursor.fetchone()
            active_rules = row[0] if row else 0
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM auto_rules WHERE chat_id = ?',
                (chat_id,)
            )
            row = cursor.fetchone()
            total_rules = row[0] if row else 0
            return {
                'active_rules': active_rules,
                'total_rules': total_rules,
                'health_score': (active_rules / total_rules * 100) if total_rules > 0 else 0,
            }
        except Exception:
            return {'active_rules': 0, 'total_rules': 0, 'health_score': 0}

    def _get_recent_risks(self, chat_id: int, days: int = 7) -> List[Dict[str, Any]]:
        try:
            # 修复字段名错误：security_events 表字段是 ts（INTEGER），不是 created_at
            cutoff_time = int((datetime.now() - timedelta(days=days)).timestamp())
            cursor = self._db.conn.execute(
                'SELECT data FROM security_events WHERE chat_id = ? AND ts > ? ORDER BY ts DESC LIMIT 10',
                (chat_id, cutoff_time)
            )
            risks = []
            for row in cursor.fetchall():
                risks.append(json.loads(row[0]))
            return risks
        except Exception:
            return []

    def _get_next_actions(self, chat_id: int) -> List[str]:
        # 修复无限递归：不调用 get_safety_status（它又会调用 _get_next_actions），
        # 而是直接调用内部计算方法
        actions = []
        security_level = self._get_security_level(chat_id)
        rules_health = self._get_rules_health(chat_id)
        bot_permissions = self._get_bot_permissions(chat_id)
        if security_level == '高风险':
            actions.append('检查并清理广告用户')
            actions.append('加强入群验证')
        if rules_health.get('health_score', 0) < 50:
            actions.append('优化自动规则配置')
        if not bot_permissions.get('perm_delete_messages', False):
            actions.append('授予机器人删除消息权限')
        return actions

    def _count_recent_alerts(self, chat_id: int, hours: int = 24) -> int:
        try:
            # 修复字段名错误：security_events 表字段是 ts（INTEGER），不是 created_at
            cutoff_time = int((datetime.now() - timedelta(hours=hours)).timestamp())
            cursor = self._db.conn.execute(
                'SELECT COUNT(*) FROM security_events WHERE chat_id = ? AND ts > ?',
                (chat_id, cutoff_time)
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    async def process(self, update):
        return None


group_safety_center_module = GroupSafetyCenterModule()