# 刷屏介入触发器（v5.19.0）
"""[TRAE SOLO CN] v5.19.0 群内多用户刷屏时高冷介入。

触发方式：事件驱动（不轮询），由 antiflood 检测到群级刷屏后调用 on_flood_detected。
触发条件：5 分钟内 >20 条消息且来自 ≥3 用户。
动作：发一句高冷平息语，树立人设。
默认关闭（FLOOD_MEDiate_TRIGGER_ENABLED=false）。
"""

import logging
import time
from collections import defaultdict

from modules.triggers.base import TriggerBase

logger = logging.getLogger(__name__)

# 高冷平息话术种子
_FLOOD_MEDiate_SEED = "（群内多用户刷屏，发句高冷平息语，简短一句，树立清冷人设，别太凶）"


class FloodMediateTrigger(TriggerBase):
    """[TRAE SOLO CN] v5.19.0 刷屏介入触发器（事件驱动）。"""

    job_id = "flood_mediate"
    enabled_config_key = "FLOOD_MEDiate_TRIGGER_ENABLED"
    trigger_type = "event"  # 事件驱动，不注册到 APScheduler

    def __init__(self):
        super().__init__()
        self._last_mediate_ts: dict = {}  # chat_id -> last ts，防短时重复

    def on_flood_detected(self, rm, chat_id: int, flood_users: list) -> None:
        """事件入口：由 antiflood 调用。

        Args:
            rm: ResourceManager
            chat_id: 刷屏群组 ID
            flood_users: 刷屏用户 ID 列表
        """
        if not rm.config.get(self.enabled_config_key, False):
            return
        # 防短时重复：同群 5 分钟内不重复介入
        now = int(time.time())
        last = self._last_mediate_ts.get(chat_id, 0)
        if now - last < 300:
            return
        self._last_mediate_ts[chat_id] = now
        try:
            reply = rm.ai.ask(_FLOOD_MEDiate_SEED, mode="flood_mediate")
            if reply and isinstance(reply, str):
                rm.bot.send_message(chat_id, reply)
                logger.info(f"🛑 刷屏介入已发送 chat={chat_id} users={len(flood_users)}")
        except Exception as e:
            logger.warning(f"刷屏介入发送失败 chat={chat_id}: {e}")


# 全局单例（供 antiflood 调用）
_instance = FloodMediateTrigger()


def trigger_flood_mediate(rm, chat_id: int, flood_users: list) -> None:
    """供 antiflood 调用的事件入口。"""
    _instance.on_flood_detected(rm, chat_id, flood_users)
