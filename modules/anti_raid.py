# -*- coding: utf-8 -*-
"""反突袭保护模块

参考阿福后台：开启防突袭、触发人数、统计窗口、防御时间、冷却时间、
应急处理策略、新成员禁言时间、防突袭告警消息。

v5.35.1 修复：
- 4 类断链 import（core.settings/db_manager/TelebotCompat/utils.logger）
- 补模块级 def check_raid(bot, m, config, db) 适配函数，兼容现有 2 处调用方
  - core/message_dispatcher.py:868
  - core/handlers/member_handlers.py:56
- 保留 class AntiRaidModule 作为内部实现，单例改为延迟初始化
"""
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from core.logging_util import get_logger

logger = get_logger(__name__)

# 默认配置（模块级常量，避免依赖模块级 config import）
_DEFAULT_ANTI_RAID_CONFIG = {
    'enabled': False,
    'trigger_member_count': 10,
    'stats_window_seconds': 30,
    'defense_duration_seconds': 600,
    'cooldown_seconds': 300,
    'emergency_strategy': 'mute_new_members',
    'new_member_mute_duration_seconds': 3600,
    'alert_message': '🚨 检测到突袭！已自动启用保护模式',
}


def _get_anti_raid_config(config: Optional[dict]) -> dict:
    """从传入的 config 中提取 ANTI_RAID_CONFIG，回退到默认值"""
    if config is None:
        return dict(_DEFAULT_ANTI_RAID_CONFIG)
    user_cfg = config.get('ANTI_RAID_CONFIG', {}) or {}
    merged = dict(_DEFAULT_ANTI_RAID_CONFIG)
    merged.update(user_cfg)
    return merged


class AntiRaidModule:
    """反突袭模块（内部实现，外部调用方应使用模块级 check_raid 函数）"""

    def __init__(self, bot=None, config: Optional[dict] = None, db=None):
        self._bot = bot
        self._config = _get_anti_raid_config(config)
        self._db = db
        self._raid_active: Dict[int, bool] = {}
        self._last_raid_time: Dict[int, int] = {}

    def check_raid(self, chat_id: int, new_member_count: int = 1) -> bool:
        """同步版检测：统计窗口内入群人数是否超过阈值"""
        if not self._config.get('enabled', False):
            return False
        now = int(time.time())
        last_raid = self._last_raid_time.get(chat_id, 0)
        if (now - last_raid) < self._config.get('cooldown_seconds', 300):
            return False
        window = self._config.get('stats_window_seconds', 30)
        window_start = now - window
        count = self._count_recent_joins(chat_id, window_start) + new_member_count
        threshold = self._config.get('trigger_member_count', 10)
        if count < threshold:
            return False
        self._trigger_raid_protection(chat_id, count)
        return True

    def _trigger_raid_protection(self, chat_id: int, count: int):
        logger.warning(f"🚨 突袭检测触发! chat={chat_id} count={count}")
        self._raid_active[chat_id] = True
        self._last_raid_time[chat_id] = int(time.time())
        defense_duration = self._config.get('defense_duration_seconds', 600)
        unlock_time = datetime.now() + timedelta(seconds=defense_duration)
        strategy = self._config.get('emergency_strategy', 'mute_new_members')
        if strategy == 'mute_new_members':
            self._mute_new_members(chat_id)
        self._send_alert(chat_id, count)
        if self._db:
            try:
                self._db.set_system_state(f'raid_mode_{chat_id}', '1')
                self._db.set_system_state(
                    f'raid_unlock_ts_{chat_id}',
                    str(int(unlock_time.timestamp()))
                )
            except Exception as e:
                logger.error(f"[反突袭] 持久化状态失败: {e}")

    def _mute_new_members(self, chat_id: int):
        """禁言新成员（通过传入的 bot 实例直接调用 Telegram API）"""
        if not self._bot:
            logger.warning("[反突袭] bot 未注入，跳过禁言")
            return
        mute_duration = self._config.get('new_member_mute_duration_seconds', 3600)
        try:
            from telebot.types import ChatPermissions
            self._bot.restrict_chat_member(
                chat_id,
                None,  # None 表示后续应通过 chat_member_update 处理
                permissions=ChatPermissions(can_send_messages=False),
                until_date=datetime.now() + timedelta(seconds=mute_duration),
            )
            logger.info(f"[反突袭] 临时禁言新成员 chat={chat_id} duration={mute_duration}s")
        except Exception as e:
            logger.error(f"[反突袭] 禁言失败: {e}")

    def _send_alert(self, chat_id: int, count: int):
        """发送告警消息（通过传入的 bot 实例）"""
        if not self._bot:
            logger.warning("[反突袭] bot 未注入，跳过告警")
            return
        message = self._config.get('alert_message', '🚨 检测到突袭！已自动启用保护模式')
        try:
            self._bot.send_message(chat_id, message)
            logger.info(f"[反突袭] 发送告警 chat={chat_id}")
        except Exception as e:
            logger.error(f"[反突袭] 发送告警失败: {e}")

    def _count_recent_joins(self, chat_id: int, window_start: int) -> int:
        """统计窗口内入群人数（兼容 db 参数为空或无 conn 的情况）"""
        if not self._db:
            return 0
        try:
            conn = getattr(self._db, 'conn', None) or getattr(self._db, 'get_conn', lambda: None)()
            if conn is None:
                return 0
            cursor = conn.execute(
                'SELECT COUNT(*) FROM group_join_log WHERE chat_id=? AND ts>?',
                (chat_id, window_start)
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"[反突袭] 统计失败: {e}")
            return 0

    def is_raid_active(self, chat_id: int) -> bool:
        if chat_id not in self._raid_active or not self._raid_active[chat_id]:
            return False
        if not self._db:
            return True
        try:
            unlock_ts_str = self._db.get_system_state(f'raid_unlock_ts_{chat_id}')
            if unlock_ts_str:
                unlock_ts = int(unlock_ts_str)
                if int(time.time()) >= unlock_ts:
                    self._raid_active[chat_id] = False
                    self._db.set_system_state(f'raid_mode_{chat_id}', '0')
                    return False
        except (ValueError, TypeError) as e:
            logger.error(f"[反突袭] 时间戳解析失败: {e}")
        return True

    def deactivate_raid(self, chat_id: int):
        self._raid_active[chat_id] = False
        if self._db:
            try:
                self._db.set_system_state(f'raid_mode_{chat_id}', '0')
                self._db.set_system_state(f'raid_unlock_ts_{chat_id}', '0')
            except Exception as e:
                logger.error(f"[反突袭] 持久化失败: {e}")
        if self._bot:
            try:
                self._bot.send_message(chat_id, '✅ 突袭警报已解除')
                logger.info(f"[反突袭] 手动解除 chat={chat_id}")
            except Exception as e:
                logger.error(f"[反突袭] 发送解除消息失败: {e}")

    def get_status(self, chat_id: int) -> Dict[str, Any]:
        return {
            'enabled': self._config.get('enabled', False),
            'active': self.is_raid_active(chat_id),
            'trigger_member_count': self._config.get('trigger_member_count', 10),
            'stats_window_seconds': self._config.get('stats_window_seconds', 30),
            'defense_duration_seconds': self._config.get('defense_duration_seconds', 600),
            'cooldown_seconds': self._config.get('cooldown_seconds', 300),
            'emergency_strategy': self._config.get('emergency_strategy', 'mute_new_members'),
        }

    def process(self, update):
        return None


# 模块级单例（延迟初始化，需要外部传入 bot/config/db 才能完整工作）
_anti_raid_module_instance: Optional[AntiRaidModule] = None


def _get_module(bot=None, config=None, db=None) -> AntiRaidModule:
    """获取或重建单例（参数变化时重建）"""
    global _anti_raid_module_instance
    if _anti_raid_module_instance is None or bot or config or db:
        _anti_raid_module_instance = AntiRaidModule(bot=bot, config=config, db=db)
    return _anti_raid_module_instance


def check_raid(bot, m, config, db) -> bool:
    """模块级适配函数（兼容旧版调用签名）

    旧版调用方：
        from modules.anti_raid import check_raid
        check_raid(bot, m, config, db)

    新版实现：内部委托给 AntiRaidModule.check_raid，保持同步接口。
    若 config 中 ANTI_RAID_CONFIG.enabled=False，直接返回 False（不触发任何动作）。

    Args:
        bot: telebot.TeleBot 实例
        m: telebot.types.Message（含 new_chat_members）
        config: dict 配置
        db: core.database.DB 实例

    Returns:
        bool: True 表示触发了突袭保护，False 表示未触发
    """
    try:
        cfg = _get_anti_raid_config(config)
        if not cfg.get('enabled', False):
            return False
        chat_id = getattr(m, 'chat', None)
        chat_id = chat_id.id if chat_id else None
        if chat_id is None:
            return False
        new_member_count = len(getattr(m, 'new_chat_members', []) or [])
        module = AntiRaidModule(bot=bot, config=config, db=db)
        return module.check_raid(chat_id, new_member_count)
    except Exception as e:
        logger.error(f"[反突袭] check_raid 异常: {e}")
        return False


def get_status(chat_id: int, config: Optional[dict] = None, db=None) -> Dict[str, Any]:
    """模块级状态查询（兼容外部直接调用）"""
    module = AntiRaidModule(config=config, db=db)
    return module.get_status(chat_id)


def deactivate_raid(chat_id: int, bot=None, db=None):
    """模块级手动解除"""
    module = AntiRaidModule(bot=bot, db=db)
    return module.deactivate_raid(chat_id)
