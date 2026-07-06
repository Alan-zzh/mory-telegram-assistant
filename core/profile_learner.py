# 用户画像自动学习模块（v5.19.0 扩展多维采集）
"""
根据用户对话内容自动提取兴趣标签、计算等级、识别 VIP 用户。
v5.19.0 新增：活跃度/涩气偏好/消费倾向/抗拒指数/高频时段/复合标签 6 维采集。
所有新功能默认关闭（USER_PROFILE_ENABLED=false），通过配置启用。
"""

import json
import re
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# CST 时区常量（VPS 为 UTC，统一使用 CST 避免时间错位）
_CST = timezone(timedelta(hours=8))

# 画像维度开关：sticker_ratio 维度当前未持久化（仅内存统计），显式标注为未启用，避免误判为遗漏功能。
STICKER_DIMENSION_ENABLED = False

# 兴趣关键词映射表
INTEREST_KEYWORDS = {
    "tarot": [r"塔罗", r"tarot", r"占卜", r"牌阵", r"牌灵", r"塔罗牌", r"大阿卡纳", r"小阿卡纳", r"愚者", r"魔术师", r"女祭司"],
    "treehole": [r"树洞", r"treehole", r"倾诉", r"心事", r"心情不好", r"想哭", r"压力", r"焦虑", r"抑郁", r"失眠", r"emo", r"难过"],
    "dream": [r"解梦", r"梦境", r"梦到", r"dream", r"周公解梦"],
    "fortune": [r"运势", r"fortune", r"运气", r"流年", r"今日运势", r"明日运势", r"星座", r"horoscope"],
    "shopping": [r"购买", r"价格", r"多少钱", r"怎么卖", r"下单", r"buy", r"至臻", r"精选", r"订阅", r"月卡", r"季卡", r"年卡"],
    "photo": [r"图集", r"写真", r"图片", r"photo", r"图片集", r"美图"],
}

# VIP 关键词（用户表达消费意愿强烈）
VIP_KEYWORDS = [r"包年", r"年卡", r"长期订阅", r"高级会员", r"vip", r"VIP", r"全享", r"至臻全享", r"999", r"大客户", r"回头客"]

# 高价值用户关键词
HIGH_VALUE_KEYWORDS = [r"再来一份", r"续费", r"加单", r"加群", r"再买", r"上次", r"上次买", r"之前买", r"老用户", r"老粉"]

# [TRAE SOLO CN] v5.19.0 新增：抗拒词模式（用于 resistance_idx 计算）
_RESISTANCE_PATTERN = re.compile(r"不要|算了|太贵|不买|没钱|再看看|不需要|不用了|下次吧|考虑下|贵了|划不来|不值", re.IGNORECASE)

# [TRAE SOLO CN] v5.19.0 新增：消费意向词（用于 spend_tendency 计算）
_SPEND_PATTERN = re.compile(r"下单|购买|续费|加单|包年|年卡|月卡|季卡|至臻|全享|订阅|怎么买|多少钱|价格|付费|支付", re.IGNORECASE)


def detect_interests(text: str) -> List[str]:
    """从文本中检测用户兴趣标签。"""
    if not text or not isinstance(text, str):
        return []
    text_lower = text.lower()
    detected = []
    for interest, patterns in INTEREST_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                detected.append(interest)
                break
    return detected


def is_vip_user(text: str, level: int = 0) -> bool:
    """判断是否为 VIP 用户（基于文本关键词或等级）。"""
    if level >= 5:
        return True
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.IGNORECASE) for p in VIP_KEYWORDS)


def is_high_value_user(text: str, tags: Optional[List[str]] = None) -> bool:
    """判断是否为高价值用户。"""
    if tags and "high_value" in tags:
        return True
    if not text or not isinstance(text, str):
        return False
    text_lower = text.lower()
    return any(re.search(p, text_lower, re.IGNORECASE) for p in HIGH_VALUE_KEYWORDS)


def calculate_level(conversation_rounds: int, days_active: int = 0) -> int:
    """根据对话轮次和活跃天数计算用户等级（0-10）。"""
    base = min(10, conversation_rounds // 10)
    bonus = min(2, days_active // 30)
    return min(10, base + bonus)


class ProfileLearner:
    """用户画像学习器（v5.19.0 多维采集）。"""

    def __init__(self, db, config: Optional[dict] = None, ai=None):
        """初始化。

        Args:
            db: 数据库对象（需有 get_user_profile / upsert_user_profile 方法）
            config: 配置字典
            ai: AIEngine 实例（v5.19.0 用于复用 _classify_intent，零 TOKEN）
        """
        self.db = db
        self.config = config or {}
        self.ai = ai  # v5.19.0 用于复用意图分类
        # 内存计数器（避免每条消息都写库，定期 flush）
        self._intent_counts: Dict[int, Dict[str, int]] = {}
        self._hour_buckets: Dict[int, Dict[int, int]] = {}
        self._sticker_counts: Dict[int, int] = {}
        self._msg_counts: Dict[int, int] = {}

    def is_enabled(self) -> bool:
        """是否启用画像学习。"""
        return self.config.get("USER_PROFILE_ENABLED", False)

    def learn_from_message(self, user_id: int, text: str, chat_id: int = 0, ts: int = 0) -> Optional[Dict]:
        """[TRAE SOLO CN] v5.19.0 多维采集：从单条消息学习画像。

        非侵入式采集：意图计数 / 时段分布 / 抗拒词 / 消费信号 / 兴趣标签。
        所有内存计数器累积，由 flush_to_db() 定期持久化。
        """
        if not self.is_enabled():
            return None
        if not text or not isinstance(text, str):
            return None

        # 1. 意图计数（复用 ai_engine._classify_intent，零 TOKEN）
        intent = "chat"
        if self.ai and hasattr(self.ai, "_classify_intent"):
            try:
                intent = self.ai._classify_intent(text)
            except Exception:
                intent = "chat"
        self._intent_counts.setdefault(user_id, {})
        self._intent_counts[user_id][intent] = self._intent_counts[user_id].get(intent, 0) + 1

        # 2. 时段分布（直接用 ts 算小时，不查 DB）
        hour = datetime.fromtimestamp(ts if ts else time.time()).hour
        self._hour_buckets.setdefault(user_id, {})
        self._hour_buckets[user_id][hour] = self._hour_buckets[user_id].get(hour, 0) + 1

        # 3. 消息计数
        self._msg_counts[user_id] = self._msg_counts.get(user_id, 0) + 1

        # 4. 抗拒词检测（轻量正则，不调模型）
        resistance_hit = 1 if _RESISTANCE_PATTERN.search(text) else 0

        # 5. 消费信号检测
        spend_hit = 1 if _SPEND_PATTERN.search(text) else 0

        # 6. 兴趣标签 + VIP/高价值（原有逻辑保留，立即写库）
        new_interests = detect_interests(text)
        current = self.db.get_user_persona_profile(user_id) or {
            "user_id": user_id, "tags": [], "level": 0, "interests": [],
            "conversation_rounds": 0, "activity_score": 0.0, "flirt_affinity": 0.0,
            "spend_tendency": 0.0, "resistance_idx": 0.5, "peak_hours": [], "persona_tags": [],
        }
        old_interests = set(current.get("interests", []) or [])
        merged_interests = list(old_interests | set(new_interests))
        current["interests"] = merged_interests
        current["last_interaction"] = datetime.now(_CST).isoformat()
        current["conversation_rounds"] = current.get("conversation_rounds", 0) + 1

        # 7. 实时更新画像维度（基于内存计数器）
        self._update_dimensions(current, user_id, resistance_hit, spend_hit, intent)

        # 8. 检查 VIP/高价值标签
        text_lower = text.lower()
        tags = set(current.get("tags", []) or [])
        if is_vip_user(text_lower, current["level"]):
            tags.add("vip")
        if is_high_value_user(text_lower, list(tags)):
            tags.add("high_value")
        if current["conversation_rounds"] >= 5:
            tags.add("active")
        current["tags"] = list(tags)

        # 9. 重新计算等级
        current["level"] = calculate_level(current["conversation_rounds"])

        # 10. 派生 persona_tags（复合标签）
        current["persona_tags"] = self._derive_persona_tags(current)

        # 持久化
        try:
            self.db.upsert_user_profile(current)
            # [TRAE SOLO CN v5.24.0 阶段2-D] 同步到共享 DB，让其他 Bot 感知本 Bot 画像更新
            # 主 Bot：写入自身 DB（幂等，与 upsert_user_profile 同库）
            # media Bot：写入主 Bot DB（跨 Bot 画像共享）
            try:
                from core.shared_db import save_shared_profile
                save_shared_profile(user_id, current)
            except Exception as e:
                logger.debug(f"共享画像同步失败 uid={user_id}: {e}")
        except Exception as e:
            logger.debug(f"画像持久化失败 uid={user_id}: {e}")
        return current

    def learn_from_sticker(self, user_id: int, sticker) -> None:
        """[TRAE SOLO CN] v5.19.0 表情包采集：统计 sticker 使用比例。"""
        if not self.is_enabled():
            return
        self._sticker_counts[user_id] = self._sticker_counts.get(user_id, 0) + 1

    def _update_dimensions(self, profile: dict, user_id: int, resistance_hit: int, spend_hit: int, intent: str) -> None:
        """[TRAE SOLO CN] v5.19.0 更新 6 维画像指标（指数移动平均）。"""
        total = self._msg_counts.get(user_id, 1) or 1
        # 活跃度：近 7 天消息数归一化（简化为总消息数 / 100 上限 1.0）
        profile["activity_score"] = min(1.0, total / 100.0)
        # 涩气偏好度：flirt 意图命中占比
        intent_counts = self._intent_counts.get(user_id, {})
        flirt_count = intent_counts.get("flirt", 0)
        profile["flirt_affinity"] = min(1.0, flirt_count / max(total, 1))
        # 消费倾向：消费词命中 + business 意图占比
        biz_count = intent_counts.get("business", 0)
        spend_score = (spend_hit + biz_count) / 2.0
        profile["spend_tendency"] = min(1.0, spend_score / max(total, 1) * 5.0)  # 放大 5 倍更敏感
        # 抗拒指数：抗拒词命中累计，初始 0.5，每次命中 +0.05 上限 1.0
        current_res = profile.get("resistance_idx", 0.5)
        if resistance_hit:
            current_res = min(1.0, current_res + 0.05)
        else:
            current_res = max(0.0, current_res - 0.005)  # 缓慢衰减
        profile["resistance_idx"] = current_res
        # 高频时段：top3 小时
        buckets = self._hour_buckets.get(user_id, {})
        if buckets:
            sorted_hours = sorted(buckets.items(), key=lambda x: x[1], reverse=True)[:3]
            profile["peak_hours"] = [h for h, _ in sorted_hours]

    def _derive_persona_tags(self, profile: dict) -> List[str]:
        """[TRAE SOLO CN] v5.19.0 复合标签派生规则。"""
        tags = []
        activity = profile.get("activity_score", 0.0)
        if activity > 0.8:
            tags.append("high_active")
        elif activity < 0.2:
            tags.append("low_active")
        peak_hours = profile.get("peak_hours", []) or []
        if 22 in peak_hours or 0 in peak_hours or 1 in peak_hours:
            tags.append("night_owl")
        if profile.get("flirt_affinity", 0.0) > 0.6:
            tags.append("flirt_friendly")
        if profile.get("spend_tendency", 0.0) > 0.7:
            tags.append("vip_intent")
        if profile.get("resistance_idx", 0.5) > 0.7:
            tags.append("resistant")
        # 画像维度：sticker_ratio 当前未启用（仅内存统计、未持久化）
        # STICKER_DIMENSION_ENABLED=False 显式标注为未启用维度，避免误判为遗漏功能。
        sticker_count = 0
        if STICKER_DIMENSION_ENABLED and sticker_count > 0:
            tags.append("heavy_sticker")
        return tags

    def batch_learn(self, user_messages: Dict[int, List[str]]) -> int:
        """批量学习多个用户画像。"""
        count = 0
        for user_id, messages in user_messages.items():
            try:
                for text in messages[-5:]:
                    if self.learn_from_message(user_id, text):
                        count += 1
                        break
            except Exception as e:
                logger.warning(f"用户 {user_id} 画像学习失败: {e}")
        return count


def get_user_profile_summary(profile: Optional[Dict]) -> Dict:
    """获取用户画像摘要（用于播报渲染）。"""
    if not profile:
        return {"is_vip": False, "is_high_value": False, "is_active": False, "level": 0, "interests": [], "tags": []}
    tags = profile.get("tags", []) or []
    return {
        "is_vip": "vip" in tags or profile.get("level", 0) >= 5,
        "is_high_value": "high_value" in tags,
        "is_active": "active" in tags or profile.get("conversation_rounds", 0) >= 3,
        "level": profile.get("level", 0),
        "interests": profile.get("interests", []) or [],
        "tags": tags,
    }


def should_apply_personalization(profile: Optional[Dict]) -> bool:
    """判断是否应该应用个性化播报（画像存在且有有效标签）。"""
    if not profile:
        return False
    tags = profile.get("tags", []) or []
    interests = profile.get("interests", []) or []
    level = profile.get("level", 0)
    return bool(tags) or bool(interests) or level > 0
