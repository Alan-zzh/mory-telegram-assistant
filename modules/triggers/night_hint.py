# 夜间高意向暗示触发器（v5.19.0）
"""[TRAE SOLO CN] v5.19.0 夜间高意向用户 1v1 暗示。

触发条件：
- 当前小时在夜间窗口（22-2 点）
- 用户 conversion_status='interested'
- persona_tags 含 vip_intent + night_owl
- 当前小时在用户 peak_hours 内
- 24 小时内未私聊过（查 reply_tracking 或新建 hint_log）
默认关闭（NIGHT_HINT_TRIGGER_ENABLED=false）。
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta

from modules.triggers.base import TriggerBase

logger = logging.getLogger(__name__)

# 【v5.31.2 修复】VPS 运行在 UTC，时段/日期相关逻辑必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))

# 夜间暗示话术种子
_NIGHT_HINT_SEED = "（深夜 1v1 私聊，针对高意向用户，清冷傲娇带点暧昧暗示，简短一句，别太露骨）"


class NightHintTrigger(TriggerBase):
    """[TRAE SOLO CN] v5.19.0 夜间高意向暗示触发器。"""

    job_id = "night_private_hint"
    enabled_config_key = "NIGHT_HINT_TRIGGER_ENABLED"
    interval_minutes = 30  # 每 30 分钟巡检一次（夜间窗口）

    def should_fire(self, rm) -> bool:
        """检查是否在夜间窗口 + 是否有候选用户。"""
        # 【v5.31.2 修复】VPS 运行在 UTC，夜间窗口判断必须用 CST
        hour = datetime.now(_CST).hour
        # 夜间窗口：22-2 点
        if hour < 22 and hour > 2:
            return False

        # 查 interested 状态 + 高意向画像用户
        # 【v5.31.2 修复】rm.db.execute/commit 未在 _REPO_METHOD_MAP 注册，
        # 会触发 __getattr__ CRITICAL 被静默吞掉，改用 rm.db.conn 直接操作
        try:
            rows = rm.db.conn.execute(
                """SELECT u.uid FROM users u
                   JOIN user_profiles p ON u.uid = p.user_id
                   WHERE u.conversion_status='interested'
                   AND p.persona_tags LIKE '%vip_intent%'
                   AND p.persona_tags LIKE '%night_owl%'
                   AND p.peak_hours LIKE ?""",
                (f'%{hour}%',)
            ).fetchall()
        except Exception as e:
            logger.warning(f"夜间暗示候选查询失败: {e}")
            return False

        candidates = []
        cooldown_hours = rm.config.get("NIGHT_HINT_COOLDOWN_HOURS", 24)
        cooldown_cutoff = int(time.time()) - cooldown_hours * 3600
        for row in rows:
            uid = row[0]
            # 排除冷却期内已暗示过的用户
            try:
                recent = rm.db.conn.execute(
                    "SELECT ts FROM broadcast_tracking WHERE chat_id=? AND category='night_hint' AND ts > ?",
                    (uid, cooldown_cutoff)
                ).fetchone()
                if recent:
                    continue
            except Exception as e:
                logger.warning(f"夜间暗示冷却检查失败 uid={uid}: {e}")
            candidates.append(uid)

        if not candidates:
            return False
        self._pending_users = candidates
        return True

    def execute(self, rm) -> None:
        """对候选用户发送夜间暗示（私聊）。"""
        users = getattr(self, "_pending_users", [])
        if not users:
            return
        max_per_run = rm.config.get("NIGHT_HINT_MAX_PER_RUN", 2)  # 单次最多 2 个用户
        for uid in users[:max_per_run]:
            try:
                # 获取用户画像，传给 AI 做个性化
                profile = rm.db.get_user_persona_profile(uid)
                reply = rm.ai.ask(_NIGHT_HINT_SEED, mode="night_hint", user_profile=profile, is_priv=True)
                if reply and isinstance(reply, str):
                    rm.bot.send_message(uid, reply)
                    # 记录冷却
                    try:
                        rm.db.conn.execute(
                            "INSERT OR REPLACE INTO broadcast_tracking (chat_id, category, msg_id, ts) VALUES (?, ?, ?, ?)",
                            (uid, "night_hint", 0, int(time.time()))
                        )
                        rm.db.conn.commit()
                    except Exception as e:
                        logger.warning(f"夜间暗示记录失败 uid={uid}: {e}")
                    logger.info(f"🌙 夜间暗示已发送 uid={uid}")
            except Exception as e:
                logger.warning(f"夜间暗示发送失败 uid={uid}: {e}")
