"""超级阿福高级功能模块
参考阿福后台：Super Afool
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

SUPER_AFOOL_CONFIG = config.get('SUPER_AFOOL_CONFIG', {
    'enabled': False,
    'advanced_analytics': False,
    'auto_response_optimization': False,
    'custom_rules_engine': False,
    'priority_support': False,
    'api_access': False,
})


class SuperAfoolModule:
    def __init__(self):
        self._db = None

    def is_premium_enabled(self) -> bool:
        return SUPER_AFOOL_CONFIG.get('enabled', False)

    def get_premium_features(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'advanced_analytics',
                'display_name': '高级数据分析',
                'enabled': SUPER_AFOOL_CONFIG.get('advanced_analytics', False),
                'description': '更详细的群组数据分析和趋势预测',
            },
            {
                'name': 'auto_response_optimization',
                'display_name': '自动回复优化',
                'enabled': SUPER_AFOOL_CONFIG.get('auto_response_optimization', False),
                'description': '基于AI的自动回复内容优化',
            },
            {
                'name': 'custom_rules_engine',
                'display_name': '自定义规则引擎',
                'enabled': SUPER_AFOOL_CONFIG.get('custom_rules_engine', False),
                'description': '支持复杂条件的自定义规则配置',
            },
            {
                'name': 'priority_support',
                'display_name': '优先技术支持',
                'enabled': SUPER_AFOOL_CONFIG.get('priority_support', False),
                'description': '享受优先技术支持服务',
            },
            {
                'name': 'api_access',
                'display_name': 'API接口访问',
                'enabled': SUPER_AFOOL_CONFIG.get('api_access', False),
                'description': '开放API接口供外部系统调用',
            },
        ]

    def enable_feature(self, feature_name: str, enabled: bool) -> bool:
        if not SUPER_AFOOL_CONFIG.get('enabled', False):
            return False
        try:
            if feature_name in SUPER_AFOOL_CONFIG:
                SUPER_AFOOL_CONFIG[feature_name] = enabled
                logger.info(f"[超级阿福] {'启用' if enabled else '禁用'}功能: {feature_name}")
                return True
        except Exception as e:
            logger.error(f"[超级阿福] 修改功能状态失败: {e}")
        return False

    def get_usage_stats(self) -> Dict[str, Any]:
        try:
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM premium_usage WHERE id=1')
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.error(f"[超级阿福] 获取使用统计失败: {e}")
        return {}

    def record_usage(self, feature_name: str, usage_count: int = 1):
        try:
            # 修复 P0：固定 id=1 读取
            cursor = self._db.conn.execute('SELECT data FROM premium_usage WHERE id=1')
            row = cursor.fetchone()
            if row:
                stats = json.loads(row[0])
            else:
                stats = {}
            if feature_name not in stats:
                stats[feature_name] = {
                    'total_usage': 0,
                    'last_used': datetime.now().isoformat(),
                }
            stats[feature_name]['total_usage'] += usage_count
            stats[feature_name]['last_used'] = datetime.now().isoformat()
            # 修复 P0 数据丢失：固定 id=1 写入
            self._db.conn.execute(
                'INSERT OR REPLACE INTO premium_usage (id, data) VALUES (1, ?)',
                (json.dumps(stats, ensure_ascii=False),)
            )
            self._db.conn.commit()
        except Exception as e:
            logger.error(f"[超级阿福] 记录使用失败: {e}")

    async def process(self, update):
        return None


super_afool_module = SuperAfoolModule()