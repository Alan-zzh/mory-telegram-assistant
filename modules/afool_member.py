"""阿福会员模块
参考阿福后台：阿福会员
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

AFOOL_MEMBER_CONFIG = config.get('AFOOL_MEMBER_CONFIG', {
    'enabled': False,
    'vip_enabled': False,
    'premium_enabled': False,
})


class AfoolMemberModule:
    def __init__(self):
        self._db = None

    def get_member_info(self, user_id: int) -> Dict[str, Any]:
        if not AFOOL_MEMBER_CONFIG.get('enabled', False):
            return {'level': 'free'}
        try:
            cursor = self._db.conn.execute(
                'SELECT data FROM member_info WHERE user_id = ?',
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return self._create_default_member(user_id)
        except Exception as e:
            logger.error(f"[阿福会员] 获取会员信息失败: {e}")
            return {'level': 'free'}

    def _create_default_member(self, user_id: int) -> Dict[str, Any]:
        default = {
            'user_id': user_id,
            'level': 'free',
            'points': 0,
            'exp': 0,
            'join_date': datetime.now().isoformat(),
            'last_active': datetime.now().isoformat(),
            'benefits': [],
        }
        try:
            self._db.conn.execute(
                'INSERT OR REPLACE INTO member_info (user_id, data) VALUES (?, ?)',
                (user_id, json.dumps(default, ensure_ascii=False))
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[阿福会员] 创建默认会员失败: {e}")
        return default

    def upgrade_member(self, user_id: int, level: str) -> bool:
        if not AFOOL_MEMBER_CONFIG.get('enabled', False):
            return False
        try:
            member = self.get_member_info(user_id)
            member['level'] = level
            member['upgrade_date'] = datetime.now().isoformat()
            member['benefits'] = self._get_level_benefits(level)
            self._db.conn.execute(
                'INSERT OR REPLACE INTO member_info (user_id, data) VALUES (?, ?)',
                (user_id, json.dumps(member, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[阿福会员] 升级会员 user={user_id}, level={level}")
            return True
        except Exception as e:
            logger.error(f"[阿福会员] 升级失败: {e}")
            return False

    def _get_level_benefits(self, level: str) -> List[str]:
        benefits = {
            'free': ['基础群管功能', '基础广告检测'],
            'vip': ['高级广告检测', '自定义规则', '优先支持', '高级统计'],
            'premium': ['全部功能', 'API访问', '专属客服', '自定义开发'],
        }
        return benefits.get(level, benefits['free'])

    def add_points(self, user_id: int, points: int) -> bool:
        if not AFOOL_MEMBER_CONFIG.get('enabled', False):
            return False
        try:
            member = self.get_member_info(user_id)
            member['points'] += points
            member['last_active'] = datetime.now().isoformat()
            self._db.conn.execute(
                'INSERT OR REPLACE INTO member_info (user_id, data) VALUES (?, ?)',
                (user_id, json.dumps(member, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[阿福会员] 添加积分 user={user_id}, points={points}")
            return True
        except Exception as e:
            logger.error(f"[阿福会员] 添加积分失败: {e}")
            return False

    def add_exp(self, user_id: int, exp: int) -> bool:
        if not AFOOL_MEMBER_CONFIG.get('enabled', False):
            return False
        try:
            member = self.get_member_info(user_id)
            member['exp'] += exp
            member['last_active'] = datetime.now().isoformat()
            member['level'] = self._calculate_level(member['exp'])
            self._db.conn.execute(
                'INSERT OR REPLACE INTO member_info (user_id, data) VALUES (?, ?)',
                (user_id, json.dumps(member, ensure_ascii=False))
            )
            self._db.conn.commit()
            logger.info(f"[阿福会员] 添加经验 user={user_id}, exp={exp}")
            return True
        except Exception as e:
            logger.error(f"[阿福会员] 添加经验失败: {e}")
            return False

    def _calculate_level(self, exp: int) -> str:
        if exp >= 10000:
            return 'premium'
        elif exp >= 5000:
            return 'vip'
        return 'free'

    async def process(self, update):
        return None


afool_member_module = AfoolMemberModule()