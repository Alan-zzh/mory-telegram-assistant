# 冷场破冰触发器（v5.19.0）
"""[TRAE SOLO CN] v5.19.0 群组冷场破冰。

触发条件：群组超过 N 分钟（默认 30）无人发言。
复用 message_snapshots 表（v5.15.3 已强制所有消息入库），不新建表。
防刷：broadcast_tracking 表 2 小时内同群不重复破冰。
默认关闭（COLD_GROUP_TRIGGER_ENABLED=false）。
"""

import logging
import time
from typing import List, Tuple

from modules.triggers.base import TriggerBase

logger = logging.getLogger(__name__)

# 冷场破冰话术池（mode=cold_breaker 时 AI 会基于此生成）
_COLD_BREAKER_SEED = "（群冷场了，发句清冷傲娇的破冰语，简短一句话，别太热情，留悬念）"


class ColdGroupTrigger(TriggerBase):
    """[TRAE SOLO CN] v5.19.0 冷场破冰触发器。"""

    job_id = "cold_group_breaker"
    enabled_config_key = "COLD_GROUP_TRIGGER_ENABLED"
    interval_minutes = 5  # 每 5 分钟巡检一次

    def should_fire(self, rm) -> bool:
        """检查是否有冷场群组（超过阈值时间无人发言）。"""
        threshold_min = rm.config.get("COLD_GROUP_THRESHOLD_MIN", 30)
        cooldown_min = rm.config.get("COLD_GROUP_COOLDOWN_MIN", 120)  # 2 小时冷却
        now = int(time.time())
        cutoff = now - threshold_min * 60
        cooldown_cutoff = now - cooldown_min * 60

        # 复用 message_snapshots 表查最近消息
        try:
            rows = rm.db.execute(
                "SELECT chat_id, MAX(ts) as last_ts FROM message_snapshots "
                "WHERE ts > ? GROUP BY chat_id",
                (cooldown_cutoff,)
            ).fetchall()
        except Exception as e:
            logger.debug(f"冷场检测查询失败: {e}")
            return False

        cold_chats = []
        for row in rows:
            chat_id, last_ts = row[0], row[1]
            if last_ts and last_ts < cutoff:
                # 排除冷却期内已破冰的群（查 broadcast_tracking）
                try:
                    recent = rm.db.execute(
                        "SELECT ts FROM broadcast_tracking WHERE chat_id=? AND category='cold_breaker' AND ts > ?",
                        (chat_id, cooldown_cutoff)
                    ).fetchone()
                    if recent:
                        continue  # 冷却期内已破冰，跳过
                except Exception:
                    pass
                cold_chats.append((chat_id, last_ts))

        if not cold_chats:
            return False
        # 缓存待破冰群组，execute 时取用
        self._pending_chats = cold_chats
        return True

    def execute(self, rm) -> None:
        """对每个冷场群发送破冰语。"""
        chats = getattr(self, "_pending_chats", [])
        if not chats:
            return
        max_per_run = rm.config.get("COLD_GROUP_MAX_PER_RUN", 3)  # 单次最多破冰 3 个群
        for chat_id, _last_ts in chats[:max_per_run]:
            try:
                # 调 AI 生成破冰语（走 llm_light 池，低成本）
                reply = rm.ai.ask(_COLD_BREAKER_SEED, mode="cold_breaker")
                if reply and isinstance(reply, str):
                    rm.bot.send_message(chat_id, reply)
                    # 记录到 broadcast_tracking 防短时重复
                    try:
                        rm.db.execute(
                            "INSERT OR REPLACE INTO broadcast_tracking (chat_id, category, msg_id, ts) VALUES (?, ?, ?, ?)",
                            (chat_id, "cold_breaker", 0, int(time.time()))
                        )
                        rm.db.commit()
                    except Exception as e:
                        logger.debug(f"冷场破冰记录失败 chat={chat_id}: {e}")
                    logger.info(f"❄️ 冷场破冰已发送 chat={chat_id}")
            except Exception as e:
                logger.warning(f"冷场破冰发送失败 chat={chat_id}: {e}")
