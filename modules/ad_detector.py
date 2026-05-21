"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/ad_detector.py  ·  广告/垃圾消息检测引擎                     ║
║                                                                        ║
║  v4.5.36 新增：多层规则引擎，零 TOKEN 消耗                              ║
║                                                                        ║
║  功能：                                                                 ║
║  - 用户名特征检测（"看简介"变体等）                                      ║
║  - 消息内容多维评分（组合关键词+语义模式）                                ║
║  - 自然语言规则管理（增删改查）                                          ║
║  - 规则持久化到 config.json                                             ║
║                                                                        ║
══════════════════════════════════════════════════════════════════════════╝
"""

import re
import uuid
from datetime import datetime, timezone
from core.logging_util import get_logger

# 导入编码后的关键词模式
from modules.ad_patterns_encoded import (
    MONEY_PATTERNS, ADULT_PATTERNS, GRAY_PATTERNS,
    CRYPTO_PATTERNS, CRYPTO_NEUTRAL_PATTERNS, CONTACT_PATTERNS, RECRUIT_PATTERNS,
    LOW_BARRIER_PATTERNS, PROFILE_HINT_PATTERNS, USERNAME_PATTERNS
)

logger = get_logger("ad_detector")

# ──────────────────────────────────────────────────────
# 内置规则（硬编码，不可删除，只能禁用）
# ──────────────────────────────────────────────────────

BUILTIN_USERNAME_RULES = [
    {
        "id": "builtin_uname_look_profile",
        "name": "用户名含'看简介'变体",
        "type": "username",
        "patterns": USERNAME_PATTERNS,
        "action": "ban",
        "severity": "high",
        "builtin": True,
        "enabled": True,
    },
]

BUILTIN_KEYWORD_GROUPS = {
    "money_promise": {
        "label": "赚钱承诺",
        "weight": 3,
        "patterns": MONEY_PATTERNS,
    },
    "low_barrier": {
        "label": "低门槛",
        "weight": 1,
        "patterns": LOW_BARRIER_PATTERNS,
    },
    "contact_info": {
        "label": "联系方式/引流",
        "weight": 3,
        "patterns": CONTACT_PATTERNS,
    },
    "profile_hint": {
        "label": "引流暗示",
        "weight": 1,
        "patterns": PROFILE_HINT_PATTERNS,
    },
    "recruit": {
        "label": "招募/拉人",
        "weight": 2,
        "patterns": RECRUIT_PATTERNS,
    },
    "crypto_money": {
        "label": "加密货币/洗钱",
        "weight": 3,
        "patterns": CRYPTO_PATTERNS,
    },
    # [Trae] v4.11.2 新增：中性加密词汇，正常讨论可使用，权重降低避免误伤
    "crypto_neutral": {
        "label": "中性加密词汇",
        "weight": 1,
        "patterns": CRYPTO_NEUTRAL_PATTERNS,
    },
    "adult_content": {
        "label": "色情引流",
        "weight": 4,
        "patterns": ADULT_PATTERNS,
    },
    "gray_industry": {
        "label": "灰色产业",
        "weight": 4,
        "patterns": GRAY_PATTERNS,
    },
}

SCORE_THRESHOLD = 3  # [Trae] v4.11.2 调整：阈值3，正常中性加密讨论(score=2)不触发，广告(score>=6)仍拦截

# ──────────────────────────────────────────────────────
# 独立工具函数（供 group_mgr 等模块直接调用）
# ──────────────────────────────────────────────────────

def check_username_suspicious(username: str) -> tuple:
    """
    快速检测用户名是否可疑（用于新人入群时直接判断）
    只检测明确的引流文字，不检测Emoji/不可见字符（避免误判正常用户）
    返回: (is_suspicious: bool, reason: str)
    """
    if not username:
        return False, ""

    # 1. 检测文字形式的引流关键词
    for pat in USERNAME_PATTERNS:
        match = re.search(pat, username, re.IGNORECASE)
        if match:
            logger.info(f"[AD] 用户名命中引流规则: 用户={username[:30]}, 匹配={match.group()}, 规则={pat[:50]}")
            return True, f"用户名含引流文字"

    # 2. 检测Telegram用户名(@开头)是否为随机字母数字组合（小号特征）
    # 格式: @ + 8-12位随机小写字母+数字，如 @ytzrgwnqc6
    # 排除包含常见单词的模式（避免误判）
    if re.match(r'^@[a-z]{8,12}\d{1,4}$', username):
        # 进一步检查是否包含常见英文单词片段（避免误判正常用户名）
        common_words = ['user', 'test', 'admin', 'bot', 'group', 'chat', 'mory']
        lower_name = username.lower()
        if not any(word in lower_name for word in common_words):
            logger.info(f"[AD] 用户名疑似随机小号: {username[:30]}")
            return True, f"用户名疑似随机小号格式"

    return False, ""


# ──────────────────────────────────────────────────────
# AdDetector 核心类
# ──────────────────────────────────────────────────────

class AdDetector:
    """广告检测引擎（零 TOKEN 消耗）
    
    [Trae] v4.6.2 新增：延迟封禁机制
    - 用户首次发可疑消息 → 记录到 suspicious_users（不封禁）
    - 累计评分达到阈值 → 触发封禁 + 删除该用户所有历史消息
    """

    def __init__(self, config: dict):
        self.config = config
        self.custom_rules = []
        self.stats = {"total_detected": 0, "false_positives": 0}
        # [Trae] v4.6.2 新增：延迟封禁追踪
        # 格式: {user_id: {"score": int, "messages": [{"msg_id": int, "chat_id": int, "text": str, "score": int}], "first_seen": datetime}}
        self.suspicious_users = {}
        self.SUSPICIOUS_THRESHOLD = 3  # 累计评分阈值，达到后封禁
        self.SUSPICIOUS_WINDOW_MINUTES = 30  # 追踪窗口（分钟）
        self._load_rules(config)

    def _load_rules(self, config: dict):
        """从 config.json 加载自定义规则和统计"""
        ad_cfg = config.get("AD_RULES", {})
        if isinstance(ad_cfg, dict):
            self.custom_rules = ad_cfg.get("custom_rules", [])
            self.stats = ad_cfg.get("stats", self.stats)
        elif isinstance(ad_cfg, list):
            self.custom_rules = ad_cfg
        if not isinstance(self.custom_rules, list):
            self.custom_rules = []
        if not isinstance(self.stats, dict):
            self.stats = {"total_detected": 0, "false_positives": 0}

    def _get_all_username_rules(self) -> list:
        """合并内置+自定义的用户名规则"""
        rules = []
        ad_cfg = self.config.get("AD_RULES", {})
        builtin_enabled = True
        if isinstance(ad_cfg, dict):
            builtin_enabled = ad_cfg.get("builtin_enabled", True)
        if builtin_enabled:
            rules.extend(BUILTIN_USERNAME_RULES)
        rules.extend([r for r in self.custom_rules if r.get("type") == "username"])
        return rules

    def _get_all_score_rules(self) -> list:
        """获取评分规则配置"""
        ad_cfg = self.config.get("AD_RULES", {})
        threshold = SCORE_THRESHOLD
        if isinstance(ad_cfg, dict):
            custom_threshold = ad_cfg.get("score_threshold")
            if custom_threshold is not None:
                try:
                    threshold = int(custom_threshold)
                except (ValueError, TypeError):
                    pass
        return [{"id": "score_ad_combo", "threshold": threshold}]

    def _check_username(self, username: str) -> list:
        """检测用户名特征，返回命中的规则列表"""
        if not username:
            return []
        matched = []
        for rule in self._get_all_username_rules():
            if not rule.get("enabled", True):
                continue
            patterns = rule.get("patterns", [])
            for pat in patterns:
                try:
                    if re.search(pat, username, re.IGNORECASE):
                        matched.append(rule)
                        break
                except re.error:
                    pass
        return matched

    def _analyze_username_anomaly(self, username: str) -> tuple:
        """
        分析用户名异常特征
        检测可能使用Custom Emoji贴图的账户特征：
        - 简单中文名 + 后续广告行为（启发式检测）
        - 明确的引流文字（传统检测）
        返回: (is_suspicious: bool, reason: str, score: int)
        """
        if not username:
            return False, "", 0

        logger.debug(f"[AD] 用户名异常分析: {username[:30]}")
        score = 0
        reasons = []

        # 1. 检测文字形式的"看简介"变体（明确的广告引流特征）
        for pat in USERNAME_PATTERNS:
            if re.search(pat, username, re.IGNORECASE):
                score += 3
                reasons.append("含引流文字'看简介'变体")
                break

        # 2. 检测可能使用Custom Emoji的账户特征（启发式）
        # 特征：中文姓名 + 数字/特殊字符，或非常简单的常见姓名
        if len(username) <= 10 and re.match(r'^[\u4e00-\u9fa5]{2,4}[\d_]*$', username):
            # 简单中文名（如"钻石王老五"）可能是Custom Emoji用户
            score += 1
            reasons.append("简单中文名模式")

        is_suspicious = score >= 2  # 降低阈值以捕获组合特征
        reason = "；".join(reasons) if reasons else ""
        return is_suspicious, reason, score

    def _check_content_score(self, msg: str) -> tuple:
        """对消息内容评分，返回 (总分, 命中维度列表)"""
        if not msg or len(msg) < 3:
            logger.debug(f"[AD] 内容评分跳过: 消息过短 len={len(msg or '')}")
            return 0, []
        total = 0
        hit_dimensions = []
        for group_name, group_cfg in BUILTIN_KEYWORD_GROUPS.items():
            patterns = group_cfg.get("patterns", [])
            weight = group_cfg.get("weight", 1)
            label = group_cfg.get("label", group_name)
            for pat in patterns:
                try:
                    match = re.search(pat, msg, re.IGNORECASE)
                    if match:
                        # [Trae] v4.6.5 新增：单维度多次命中只计一次分
                        # 避免同一维度多个规则重复加分导致误判
                        total += weight
                        hit_dimensions.append(f"{label}(+{weight})")
                        logger.info(f"[AD] 内容命中: 维度={label}, 权重=+{weight}, 匹配={match.group()[:30]}, 规则={pat[:50]}")
                        break  # 每个维度只计一次最高分
                except re.error:
                    pass
        if total > 0:
            logger.info(f"[AD] 内容评分结果: 总分={total}, 命中维度={hit_dimensions}, 消息={msg[:80]}")
        return total, hit_dimensions

    def detect(self, username: str, msg: str) -> dict:
        """
        核心检测函数
        返回: {is_ad: bool, score: int, action: str, matched_rules: [str], reason: str}
        """
        msg_clean = (msg or "").strip()
        uname_clean = (username or "").strip()

        logger.info(f"[AD] 开始检测: 用户={uname_clean[:30]}, 消息={msg_clean[:80]}")

        uname_matches = self._check_username(uname_clean)
        content_score, hit_dims = self._check_content_score(msg_clean)
        # [Trae] v4.6.6 修复：用户显示名称本身也可能是广告（如"虚拟货币搬砖日挣1千U"）
        name_score, name_hit_dims = self._check_content_score(uname_clean)
        total_score = content_score + name_score
        score_rules = self._get_all_score_rules()
        threshold = score_rules[0]["threshold"] if score_rules else SCORE_THRESHOLD

        # 用户名异常分析（检测Custom Emoji贴图等）
        uname_anomaly, uname_anomaly_reason, uname_anomaly_score = self._analyze_username_anomaly(uname_clean)

        if uname_anomaly:
            logger.info(f"[AD] 用户名异常: 原因={uname_anomaly_reason}, 评分=+{uname_anomaly_score}")

        is_ad = False
        action = "delete"
        matched_rules = []
        reasons = []

        if uname_matches:
            for rule in uname_matches:
                matched_rules.append(rule.get("name", rule.get("id", "?")))
                reasons.append(f"用户名命中: {rule.get('name', '?')}")
                if rule.get("severity") == "high":
                    is_ad = True
                    action = "ban"
                    logger.info(f"[AD] 用户名命中规则: {rule.get('name', '?')}, 严重性=high, 动作=ban")

        # [Trae] v4.6.6 新增：名称中包含广告内容（如"虚拟货币搬砖日挣1千U 招团队合作"）
        if name_score > 0:
            matched_rules.append(f"名称广告评分={name_score}")
            reasons.append(f"名称含广告: {', '.join(name_hit_dims)}")
            logger.info(f"[AD] 名称含广告内容: 评分={name_score}, 命中={name_hit_dims}")

        # 用户名异常 + 广告内容 = 高置信度广告
        if uname_anomaly and total_score >= 2:
            is_ad = True
            action = "ban"
            matched_rules.append(f"用户名异常(+{uname_anomaly_score})")
            reasons.append(f"用户名异常: {uname_anomaly_reason}")
            logger.info(f"[AD] 用户名异常+内容评分组合命中: 异常={uname_anomaly_reason}, 总评分={total_score}")

        if total_score >= threshold:
            is_ad = True
            if action != "ban":
                action = "ban"
            matched_rules.append(f"总评分={total_score}(阈值{threshold})")
            if hit_dims:
                reasons.append(f"内容命中: {', '.join(hit_dims)}")
            # 避免与上方 name_score>0 分支重复添加名称命中原因
            if name_hit_dims and name_score <= 0:
                reasons.append(f"名称命中: {', '.join(name_hit_dims)}")
            logger.info(f"[AD] 总评分超阈值: 评分={total_score}, 阈值={threshold}, 动作=ban")

        if not is_ad and uname_matches and total_score > 0:
            is_ad = True
            action = "ban"
            reasons.append(f"用户名+内容组合命中 (评分={total_score})")
            logger.info(f"[AD] 用户名+内容组合命中: 评分={total_score}")

        # 单独用户名异常（无广告内容）→ 仅记录，不拦截（防误判）
        if not is_ad and uname_anomaly:
            matched_rules.append(f"用户名可疑(+{uname_anomaly_score})")
            logger.info(f"[AD] 用户名可疑但无广告内容，仅记录不拦截: {uname_anomaly_reason}")

        reason_str = "；".join(reasons) if reasons else "未命中规则"

        result = {
            "is_ad": is_ad,
            "score": total_score,  # [Trae] v4.6.6 修复：返回总评分（含名称评分），延迟封禁才能正确累计
            "action": action,
            "matched_rules": matched_rules,
            "reason": reason_str,
        }

        if is_ad:
            self.stats["total_detected"] = self.stats.get("total_detected", 0) + 1
            logger.warning(f"[AD] 🚫 判定为广告: 用户={uname_clean[:30]}, 评分={total_score}, 动作={action}, 原因={reason_str}")
        else:
            logger.debug(f"[AD] 检测通过: 用户={uname_clean[:30]}, 评分={content_score}")

        return result

    # ──────────────────────────────────────────────────────
    # [Trae] v4.6.2 新增：延迟封禁机制
    # ──────────────────────────────────────────────────────

    def track_suspicious_user(self, user_id: int, msg_id: int, chat_id: int, text: str, score: int) -> dict:
        """
        追踪可疑用户，累计评分
        返回: {"action": "none"|"watch"|"ban", "total_score": int, "messages": list}
        """
        now = datetime.now(timezone.utc)

        # 清理过期的追踪记录
        self._cleanup_old_tracking(now)

        user_key = str(user_id)
        if user_key not in self.suspicious_users:
            self.suspicious_users[user_key] = {
                "score": 0,
                "messages": [],
                "first_seen": now,
            }

        user_track = self.suspicious_users[user_key]
        user_track["score"] += score
        user_track["messages"].append({
            "msg_id": msg_id,
            "chat_id": chat_id,
            "text": text[:100],  # 只存前100字符
            "score": score,
            "time": now.isoformat(),
        })

        total_score = user_track["score"]
        msg_count = len(user_track["messages"])

        # 判断动作
        if total_score >= self.SUSPICIOUS_THRESHOLD:
            # 累计评分达到阈值 → 封禁
            logger.warning(f"[AD] 🚫 延迟封禁触发: uid={user_id}, 累计评分={total_score}, 消息数={msg_count}")
            return {
                "action": "ban",
                "total_score": total_score,
                "messages": list(user_track["messages"]),
                "reason": f"累计评分{total_score}达到阈值{self.SUSPICIOUS_THRESHOLD}"
            }
        elif score > 0:
            # 有评分但未达阈值 → 继续观察
            logger.info(f"[AD] 👁️ 可疑用户追踪: uid={user_id}, 本次评分={score}, 累计={total_score}, 消息数={msg_count}")
            return {
                "action": "watch",
                "total_score": total_score,
                "messages": list(user_track["messages"]),
                "reason": f"累计评分{total_score}，继续观察"
            }
        else:
            return {"action": "none", "total_score": total_score, "messages": []}

    def get_user_messages_to_delete(self, user_id: int) -> list:
        """
        [Trae] v4.6.3 新增：获取该用户所有被追踪的消息列表（用于封禁后批量删除）
        返回: [{"msg_id": int, "chat_id": int}, ...]
        """
        user_key = str(user_id)
        if user_key in self.suspicious_users:
            return [
                {"msg_id": m["msg_id"], "chat_id": m["chat_id"]}
                for m in self.suspicious_users[user_key]["messages"]
            ]
        return []

    def get_user_tracking(self, user_id: int) -> dict:
        """获取用户的追踪状态"""
        user_key = str(user_id)
        if user_key in self.suspicious_users:
            track = self.suspicious_users[user_key]
            return {
                "score": track["score"],
                "message_count": len(track["messages"]),
                "first_seen": track["first_seen"].isoformat(),
            }
        return {"score": 0, "message_count": 0, "first_seen": None}

    def clear_user_tracking(self, user_id: int):
        """清除用户的追踪记录（误封解禁后调用）"""
        user_key = str(user_id)
        if user_key in self.suspicious_users:
            del self.suspicious_users[user_key]
            logger.info(f"[AD] 已清除用户追踪记录: uid={user_id}")

    def _cleanup_old_tracking(self, now: datetime):
        """清理超过窗口期的追踪记录"""
        expired = []
        for user_key, track in self.suspicious_users.items():
            first_seen = track["first_seen"]
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            elapsed = (now - first_seen).total_seconds() / 60
            if elapsed > self.SUSPICIOUS_WINDOW_MINUTES:
                expired.append(user_key)
        for user_key in expired:
            del self.suspicious_users[user_key]
            logger.debug(f"[AD] 清理过期追踪记录: uid={user_key}")

    def add_custom_rule(self, rule: dict) -> tuple:
        """新增自定义规则，返回 (success, message)"""
        rule_id = rule.get("id") or f"custom_{uuid.uuid4().hex[:8]}"
        rule["id"] = rule_id
        rule["created_at"] = datetime.now(timezone.utc).isoformat()
        rule["builtin"] = False
        rule["enabled"] = rule.get("enabled", True)

        rule_type = rule.get("type", "")
        if rule_type not in ("keyword", "combo", "username", "pattern"):
            return False, f"不支持的规则类型: {rule_type}"

        conditions = rule.get("conditions", {})
        if rule_type in ("keyword", "combo") and not conditions.get("keywords"):
            return False, "关键词规则必须包含 keywords 字段"
        if rule_type == "username" and not conditions.get("patterns"):
            return False, "用户名规则必须包含 patterns 字段"
        if rule_type == "pattern" and not conditions.get("regex"):
            return False, "正则规则必须包含 regex 字段"

        if rule_type == "combo":
            conditions.setdefault("required_count", 2)

        self.custom_rules.append(rule)
        self._save_rules()
        logger.info(f"新增广告规则: {rule.get('name', rule_id)}")
        return True, f"规则已添加: {rule.get('name', rule_id)} (ID: {rule_id})"

    def remove_custom_rule(self, rule_id: str) -> tuple:
        """删除自定义规则，返回 (success, message)"""
        for rule in self.custom_rules:
            if rule.get("id") == rule_id and not rule.get("builtin"):
                self.custom_rules.remove(rule)
                self._save_rules()
                logger.info(f"删除广告规则: {rule_id}")
                return True, f"规则已删除: {rule_id}"
        return False, f"未找到可删除的规则: {rule_id}（内置规则不可删除）"

    def toggle_rule(self, rule_id: str, enabled: bool) -> tuple:
        """开关规则，返回 (success, message)"""
        all_rules = list(BUILTIN_USERNAME_RULES) + self.custom_rules
        for rule in all_rules:
            if rule.get("id") == rule_id:
                rule["enabled"] = enabled
                if not rule.get("builtin"):
                    self._save_rules()
                action = "开启" if enabled else "关闭"
                logger.info(f"{action}广告规则: {rule_id}")
                return True, f"规则已{action}: {rule_id}"
        return False, f"未找到规则: {rule_id}"

    def list_rules(self) -> list:
        """列出所有规则"""
        result = []
        ad_cfg = self.config.get("AD_RULES", {})
        builtin_enabled = True
        if isinstance(ad_cfg, dict):
            builtin_enabled = ad_cfg.get("builtin_enabled", True)
        if builtin_enabled:
            for rule in BUILTIN_USERNAME_RULES:
                result.append({
                    "id": rule["id"],
                    "name": rule.get("name", "?"),
                    "type": rule["type"],
                    "action": rule.get("action", "delete"),
                    "enabled": rule.get("enabled", True),
                    "builtin": True,
                })
        for rule in self.custom_rules:
            result.append({
                "id": rule.get("id", "?"),
                "name": rule.get("name", "?"),
                "type": rule.get("type", "?"),
                "action": rule.get("action", "delete"),
                "enabled": rule.get("enabled", True),
                "builtin": rule.get("builtin", False),
            })
        return result

    def get_stats(self) -> dict:
        """获取统计信息"""
        score_rules = self._get_all_score_rules()
        threshold = score_rules[0]["threshold"] if score_rules else SCORE_THRESHOLD
        return {
            "total_detected": self.stats.get("total_detected", 0),
            "false_positives": self.stats.get("false_positives", 0),
            "score_threshold": threshold,
            "custom_rules_count": len(self.custom_rules),
            "builtin_rules_count": len(BUILTIN_USERNAME_RULES),
        }

    def test_text(self, username: str, msg: str) -> str:
        """测试文本的检测效果，返回人类可读的结果"""
        result = self.detect(username, msg)
        lines = [
            f"检测结果: {'🚫 广告' if result['is_ad'] else '✅ 正常'}",
            f"内容评分: {result['score']}",
            f"处理动作: {result['action']}",
            f"原因: {result['reason']}",
        ]
        if result["matched_rules"]:
            lines.append(f"命中规则: {', '.join(result['matched_rules'])}")
        return "\n".join(lines)

    def _save_rules(self):
        """保存自定义规则到 config"""
        ad_cfg = self.config.get("AD_RULES", {})
        if not isinstance(ad_cfg, dict):
            ad_cfg = {"builtin_enabled": True, "custom_rules": [], "stats": {}}
        ad_cfg.setdefault("builtin_enabled", True)
        ad_cfg["custom_rules"] = self.custom_rules
        ad_cfg["stats"] = self.stats
        ad_cfg["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.config["AD_RULES"] = ad_cfg
