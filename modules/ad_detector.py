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
import json
import uuid
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from core.helpers import can_delete_message
from core.logging_util import get_logger
from core.database import _db_lock
from core.http_client import get_http_client, HTTPRequestError

# 导入编码后的关键词模式
from modules.ad_patterns_encoded import (
    MONEY_PATTERNS, ADULT_PATTERNS, GRAY_PATTERNS,
    CRYPTO_PATTERNS, CRYPTO_NEUTRAL_PATTERNS, CONTACT_PATTERNS, RECRUIT_PATTERNS,
    LOW_BARRIER_PATTERNS, PROFILE_HINT_PATTERNS, USERNAME_PATTERNS, BIO_PATTERNS
)
# [Puzan-OS v5.32] 营销话术正则库
from modules.ad_marketing_patterns import (
    MARKETING_TEMPLATE_PATTERNS, MARKETING_CONTACT_PATTERNS,
    MARKETING_URGENCY_PATTERNS, MARKETING_PROJECT_PATTERNS,
)

logger = get_logger("ad_detector")

# ──────────────────────────────────────────────────────
# 内置规则（硬编码，不可删除，只能禁用）
# ──────────────────────────────────────────────────────

BUILTIN_USERNAME_RULES = [
    {
        "id": "builtin_uname_look_profile",
        "name": "用户名含明确引流变体",
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
        "weight": 3,
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
    # [Puzan-OS v5.32] 营销话术分组（4 个子维度）
    "marketing_template": {
        "label": "营销话术模板",
        "weight": 2,
        "patterns": MARKETING_TEMPLATE_PATTERNS,
    },
    "marketing_contact": {
        "label": "引流联系方式",
        "weight": 3,
        "patterns": MARKETING_CONTACT_PATTERNS,
    },
    "marketing_urgency": {
        "label": "紧迫诱导话术",
        "weight": 2,
        "patterns": MARKETING_URGENCY_PATTERNS,
    },
    "marketing_project": {
        "label": "项目平台诱导",
        "weight": 3,
        "patterns": MARKETING_PROJECT_PATTERNS,
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

    def __init__(self, config: dict, db=None):
        self.config = config
        self.db = db
        self.custom_rules = []
        self.stats = {"total_detected": 0, "false_positives": 0}
        # [Trae] v4.6.2 新增：延迟封禁追踪
        # 格式: {user_id: {"score": int, "messages": [{"msg_id": int, "chat_id": int, "text": str, "score": int}], "first_seen": datetime}}
        self.suspicious_users = {}
        self.SUSPICIOUS_THRESHOLD = 3  # 累计评分阈值，达到后封禁
        self.SUSPICIOUS_WINDOW_MINUTES = 30  # 追踪窗口（分钟）
        self._load_rules(config)
        self._cas_cache = {}
        self._spb_cache = {}
        # 【v5.31.x 优化】按 user_id 缓存但原无上限：活跃群长期运行会无界增长。
        # 加容量上限，超出时淘汰最旧条目（dict 保序，next(iter) 即最旧）。
        self._AD_CACHE_MAX = 2000
        self._load_tracking_from_db()

    @staticmethod
    def _clean_zero_width(text: str) -> tuple:
        """
        [TRAE SOLO CN] 清理零宽字符（Zero-Width Characters）

        广告发送者使用零宽字符拆散中文关键词，绕过正则检测。
        例如：只\u200d搞\u200cU无\u2060套\u200d路 → 只搞U无套路

        Args:
            text: 原始文本

        Returns:
            tuple: (清理后的文本, 零宽字符数量)
        """
        if not text:
            return text, 0
        # 零宽字符范围
        zero_width_chars = (
            '\u200b\u200c\u200d\u200e\u200f'  # U+200B~U+200F
            '\u2028\u2029\u202a\u202b\u202c\u202d\u202e\u202f'  # U+2028~U+202F
            '\u2060\u2061\u2062\u2063\u2064\u2065\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f'  # U+2060~U+206F
            '\ufeff'  # U+FEFF (BOM)
            '\u00ad'  # U+00AD (soft hyphen)
            '\u180e'  # U+180E (Mongolian vowel separator)
            '\ufe00\ufe01\ufe02\ufe03\ufe04\ufe05\ufe06\ufe07\ufe08\ufe09\ufe0a\ufe0b\ufe0c\ufe0d\ufe0e\ufe0f'  # variation selectors
        )
        # 统计零宽字符数量
        zwc_count = sum(1 for c in text if c in zero_width_chars)
        # 清理零宽字符（保留正常空格、标点、换行）
        cleaned = ''.join(c for c in text if c not in zero_width_chars)
        return cleaned, zwc_count

    @staticmethod
    def _normalize_ad_evasion(text: str) -> str:
        """
        [TRAE SOLO CN] v5.13.1 新增：反广告规避文本规范化

        广告发送者会使用变体字/全角数字绕过检测，例如：
        - 唰箪秒結𝟺𝟶𝟶 → 刷单秒钻400
        - 𝟶𝟷𝟸𝟹 → 0123（全角数学粗体数字）
        - ０１２３ → 0123（fullwidth 数字）
        - 結/鑽 → 钻（繁体变体）
        - 箪 → 单（形近字）

        Returns:
            规范化后的文本
        """
        if not text:
            return text

        # 1. Unicode 兼容规范化：统一全角/花体字母、数字和标点。
        # NFKC 不做语义替换，只把视觉等价字符收敛为普通字符，正常中文不会被改写。
        text = unicodedata.normalize("NFKC", text)

        # 2. 兼容旧数学数字范围（NFKC 已覆盖绝大多数，保留显式兜底）
        result = []
        for c in text:
            code = ord(c)
            # fullwidth digits 0-9: U+FF10~U+FF19
            if 0xff10 <= code <= 0xff19:
                result.append(chr(code - 0xff10 + ord('0')))
            # Mathematical bold digits 0-9: U+1D7CE~U+1D7D7
            elif 0x1d7ce <= code <= 0x1d7d7:
                result.append(chr(code - 0x1d7ce + ord('0')))
            # Mathematical double-struck digits 0-9: U+1D7D8~U+1D7E1
            elif 0x1d7d8 <= code <= 0x1d7e1:
                result.append(chr(code - 0x1d7d8 + ord('0')))
            # Mathematical sans-serif digits 0-9: U+1D7E2~U+1D7EB
            elif 0x1d7e2 <= code <= 0x1d7eb:
                result.append(chr(code - 0x1d7e2 + ord('0')))
            # Mathematical monospace digits 0-9: U+1D7F6~U+1D7FF
            elif 0x1d7f6 <= code <= 0x1d7ff:
                result.append(chr(code - 0x1d7f6 + ord('0')))
            else:
                result.append(c)
        text = ''.join(result)

        # 3. 数字串中的 O/o 规避：只规范化紧邻“+”的混写数字，不全局替换英文单词。
        # 例：9Oo+ / 4oO+ → 900+ / 400+；型号 O90、普通英文保持不变。
        text = re.sub(
            r"(?<![A-Za-z0-9_])(?=[0-9Oo]*[0-9])(?=[0-9Oo]*[Oo])[0-9Oo]+(?=\s*\+)",
            lambda match: match.group(0).replace("O", "0").replace("o", "0"),
            text,
        )

        # 4. 日/月收益数字中的 I/l/| 与 O/o 规避。
        # 仅接受“时间收益锚点 + 纯数字形近串 + 金额结尾”，不把 BOSS、SOLO 等英文当数字。
        daily_number_pattern = re.compile(
            r"(?P<prefix>(?:(?:\u4e00|1)[\u5929\u65e5]|\u6bcf[\u5929\u65e5]|"
            r"[\u65e5\u6708](?:\u5165|\u8d5a|\u6323)?))"
            r"(?P<space>\s*)"
            r"(?P<number>(?:[0-9][0-9OoIl|]*|[Il|][0Oo]{2,}))"
            r"(?=\s*(?:\+|[\u5143\u5757UuKkWw]))"
        )

        def _replace_daily_number(match):
            number = match.group("number").translate(
                str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})
            )
            return f"{match.group('prefix')}{match.group('space')}{number}"

        text = daily_number_pattern.sub(_replace_daily_number, text)

        # 5. 形近字 / 繁体变体 映射到简体
        variant_map = {
            '唰': '刷',  # 唰 -> 刷（刷单变体）
            '箪': '单',  # 箪 -> 单
            '結': '钻',  # 結 -> 钻（繁体）
            '鑽': '钻',  # 鑽 -> 钻（繁体）
            '賺': '赚',  # 賺 -> 赚（繁体）
            '錢': '钱',  # 錢 -> 钱（繁体）
            '個': '个',  # 個 -> 个（繁体）
            '東': '东',  # 東 -> 东（繁体）
            '們': '们',  # 們 -> 们（繁体）
            '為': '为',  # 為 -> 为（繁体）
            '無': '无',  # 無 -> 无（繁体）
            '經': '经',  # 經 -> 经（繁体）
            '營': '营',  # 營 -> 营（繁体）
            '帶': '带',  # 帶 -> 带（繁体）
            '師': '师',  # 師 -> 师（繁体）
            '專': '专',  # 專 -> 专（繁体）
            '業': '业',  # 業 -> 业（繁体）
            '貨': '货',  # 貨 -> 货（繁体）
            '線': '线',  # 線 -> 线（在線→在线）
            '絡': '络',  # 絡 -> 络（聯絡→联络）
            '聯': '联',  # 聯 -> 联（聯絡→联络）
            '飛': '飞',  # 飛 -> 飞（啟飛→启飞）
            '啟': '启',  # 啟 -> 启（啟飛→启飞）
            '帶': '带',  # 帶 -> 带（帶你→带你）
            # [Puzan-OS] v5.31.5 新增：支付宝谐音变体
            '吱': '支',  # 吱 -> 支（有吱付宝=有支付宝）
            '伏': '付',  # 伏 -> 付（吱伏宝=支付宝）
            '寶': '宝',  # 寶 -> 宝（繁体）
        }
        for variant, normal in variant_map.items():
            text = text.replace(variant, normal)

        return text

    def _check_cas(self, user_id: int) -> tuple:
        """[TRAE SOLO CN] v5.8.0 新增：查询CAS(Combot Anti-Spam)黑名单"""
        now = time.time()
        if user_id in self._cas_cache:
            cached_result, cached_time = self._cas_cache[user_id]
            if now - cached_time < 3600:
                return cached_result
        try:
            # 使用统一HTTP客户端
            client = get_http_client()
            url = f"https://api.cas.chat/check?user_id={user_id}"
            data = client.get(url, timeout=3)
            if data.get("ok"):
                messages = data.get("result", {}).get("messages", [])
                reason = messages[0] if messages else "CAS黑名单"
                result = (True, reason)
            else:
                result = (False, "")
        except HTTPRequestError:
            # 查询失败，返回默认值
            result = (False, "")
        except Exception:
            result = (False, "")
        self._cas_cache[user_id] = (result, now)
        if len(self._cas_cache) > self._AD_CACHE_MAX:
            self._cas_cache.pop(next(iter(self._cas_cache)))
        return result

    def _check_spb(self, user_id: int) -> tuple:
        """[TRAE SOLO CN] v5.8.0 新增：查询SPB(SpamProtection)垃圾评分"""
        now = time.time()
        if user_id in self._spb_cache:
            cached_result, cached_time = self._spb_cache[user_id]
            if now - cached_time < 3600:
                return cached_result
        try:
            # 使用统一HTTP客户端
            client = get_http_client()
            url = f"https://api.intellivoid.net/spamprotection/v1/lookup?query={user_id}"
            data = client.get(url, timeout=3)
            spam_prediction = data.get("spam_prediction", {})
            spam_probability = float(spam_prediction.get("spam_probability", 0.0))
            is_spam = bool(spam_prediction.get("is_spam", False))
            result = (spam_probability, is_spam)
        except HTTPRequestError:
            # 查询失败，返回默认值
            result = (0.0, False)
        except Exception:
            result = (0.0, False)
        self._spb_cache[user_id] = (result, now)
        if len(self._spb_cache) > self._AD_CACHE_MAX:
            self._spb_cache.pop(next(iter(self._spb_cache)))
        return result

    def _check_metadata(self, msg: str, message_meta: dict, bio_score: int, username_anomaly_score: int) -> tuple:
        """[TRAE SOLO CN] v5.8.0 新增：消息元数据检测"""
        score = 0
        reasons = []
        url_pattern = r'https?://'
        url_count = len(re.findall(url_pattern, msg))
        if url_count > 2:
            score += 1
            reasons.append("短链接过多(>2)")
        shortener_domains = ['bit.ly', 'tinyurl.com', 't.co', 'ow.ly', 'is.gd', 'buff.ly', 'goo.gl', 'shorturl.at', 't.ly']
        for domain in shortener_domains:
            if domain in msg:
                score += 1
                reasons.append(f"含短链接域名({domain})")
                break
        if message_meta.get("is_forwarded") and (username_anomaly_score >= 1 or bio_score >= 3):
            score += 1
            reasons.append("转发消息+用户名/Bio可疑")
        if message_meta.get("has_photo") and not msg.strip() and (username_anomaly_score >= 1 or bio_score >= 3):
            score += 1
            reasons.append("纯图片消息+用户名/Bio可疑")
        if message_meta.get("is_new_user") and re.search(url_pattern, msg):
            score += 1
            reasons.append("新用户+含链接")
        return score, reasons

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

    def _init_tracking_table(self):
        if not self.db:
            return
        try:
            with _db_lock:
                self.db.conn.execute("""CREATE TABLE IF NOT EXISTS ad_suspicious_users (
                    user_id INTEGER PRIMARY KEY,
                    score INTEGER DEFAULT 0,
                    first_seen TEXT,
                    messages TEXT DEFAULT '[]',
                    updated_at INTEGER
                )""")
                self.db.conn.commit()
        except Exception as e:
            logger.warning(f"创建ad_suspicious_users表失败: {e}")

    def _save_tracking_to_db(self, user_id):
        if not self.db:
            return
        user_key = str(user_id)
        if user_key not in self.suspicious_users:
            return
        track = self.suspicious_users[user_key]
        try:
            messages_json = json.dumps([
                {
                    "msg_id": m["msg_id"],
                    "chat_id": m["chat_id"],
                    "text": m.get("text", ""),
                    "score": m.get("score", 0),
                    "is_ad": m.get("is_ad", False) is True,
                    "time": m.get("time", ""),
                }
                for m in track["messages"]
            ], ensure_ascii=False)
            first_seen_str = track["first_seen"].isoformat() if isinstance(track["first_seen"], datetime) else str(track["first_seen"])
            with _db_lock:
                self.db.conn.execute(
                    "INSERT OR REPLACE INTO ad_suspicious_users (user_id, score, first_seen, messages, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (int(user_key), track["score"], first_seen_str, messages_json, int(datetime.now(timezone.utc).timestamp()))
                )
                self.db.conn.commit()
        except Exception as e:
            logger.warning(f"保存追踪数据到数据库失败 uid={user_id}: {e}")

    def _load_tracking_from_db(self):
        if not self.db:
            return
        self._init_tracking_table()
        try:
            now = datetime.now(timezone.utc)
            cutoff = now.timestamp() - (self.SUSPICIOUS_WINDOW_MINUTES * 60)
            with _db_lock:
                rows = self.db.conn.execute(
                    "SELECT user_id, score, first_seen, messages, updated_at FROM ad_suspicious_users WHERE updated_at > ?",
                    (cutoff,)
                ).fetchall()
            for row in rows:
                user_id, score, first_seen_str, messages_json, updated_at = row
                try:
                    first_seen = datetime.fromisoformat(first_seen_str)
                    if first_seen.tzinfo is None:
                        first_seen = first_seen.replace(tzinfo=timezone.utc)
                    messages = json.loads(messages_json) if messages_json else []
                    self.suspicious_users[str(user_id)] = {
                        "score": score,
                        "messages": messages,
                        "first_seen": first_seen,
                    }
                except Exception as e:
                    logger.warning(f"加载追踪数据失败 uid={user_id}: {e}")
            if self.suspicious_users:
                logger.info(f"[AD] 从数据库加载 {len(self.suspicious_users)} 条追踪记录")
        except Exception as e:
            logger.warning(f"加载追踪数据失败: {e}")

    def _delete_tracking_from_db(self, user_id):
        if not self.db:
            return
        try:
            with _db_lock:
                self.db.conn.execute("DELETE FROM ad_suspicious_users WHERE user_id = ?", (int(user_id),))
                self.db.conn.commit()
        except Exception as e:
            logger.warning(f"删除追踪数据失败 uid={user_id}: {e}")

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
        # 【TRAE SOLO CN v5.18.3审计修复】仅当纯中文名+长数字(≥4位)时才加分，排除正常中文名
        if len(username) <= 10 and re.match(r'^[\u4e00-\u9fa5]{2,4}\d{4,}$', username):
            # 中文名+长数字（如"张三1234"）可能是Custom Emoji广告用户
            score += 1
            reasons.append("中文名+长数字模式")

        # [TRAE SOLO CN] v5.7.5 新增：短随机用户名检测（广告小号特征，如 gc8181、ab12）
        # 【TRAE SOLO CN v5.18.3审计修复】增加常见英文单词白名单，避免误伤 tom12/jay01 等正常用户名
        _common_en_names = {"tom", "jay", "amy", "bob", "lee", "kim", "sam", "ben", "joe",
                            "max", "tim", "rob", "dan", "ken", "jim", "ron", "lex", "zed",
                            "sky", "ice", "fox", "owl", "cat", "dog", "sun", "ray", "roy"}
        username_only = re.sub(r'[@\s]', '', username)
        if (re.match(r'^[a-z]{1,4}\d{2,4}$', username_only, re.IGNORECASE)
                and username_only.lower() not in _common_en_names):
            return True, "短随机用户名（广告小号特征）", 2

        is_suspicious = score >= 2  # 降低阈值以捕获组合特征
        reason = "；".join(reasons) if reasons else ""
        return is_suspicious, reason, score

    def _check_content_score(self, msg: str) -> tuple:
        """对消息内容评分，返回 (总分, 命中维度列表)"""
        if not msg:
            return 0, []
        msg_len = len(msg)
        # [TRAE SOLO CN] 修复：2字符消息只对高权重维度（色情/灰色）检测，避免漏检短词色情引流
        # 3字符以上正常检测所有维度
        if msg_len < 2:
            logger.debug(f"[AD] 内容评分跳过: 消息过短 len={msg_len}")
            return 0, []
        total = 0
        hit_dimensions = []
        for group_name, group_cfg in BUILTIN_KEYWORD_GROUPS.items():
            patterns = group_cfg.get("patterns", [])
            weight = group_cfg.get("weight", 1)
            label = group_cfg.get("label", group_name)
            # 2字符消息只检测高权重维度（色情引流、灰色产业），避免正常短词误伤
            if msg_len == 2 and weight < 4:
                continue
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

    def _check_pinyin_ad(self, msg: str) -> int:
        """【v5.23.0 P2-5】拼音级广告检测

        将消息转为无声调拼音，检测谐音广告词。
        防止广告发送者用谐音字绕过中文关键词检测，如：
        - "shua dan" (刷单) → 原文可能是"唰箪"/"耍丹"等谐音
        - "zhuan qian" (赚钱) → 原文可能是"赚浅"/"砖前"等
        - "si xin" (私信) → 原文可能是"思心"/"丝信"等

        Returns:
            int: 加分（0=未命中，2=命中一个，4=命中多个）
        """
        if not msg or len(msg) < 2:
            return 0
        try:
            from core.pinyin_util import text_to_pinyin_silent
            pinyin_text = text_to_pinyin_silent(msg).lower()
            if not pinyin_text:
                return 0

            # 谐音广告词拼音模式（无声调）
            pinyin_ad_patterns = [
                # 刷单/刷量类
                'shua dan', 'shua liang', 'shua ping',
                # 赚钱/日赚类
                'zhuan qian', 'ri zhuan', 'ri zhuan',
                # 私信/联系类
                'si xin', 'si liao', 'lian xi wo',
                # 加微信/加QQ类
                'jia wei xin', 'jia v xin', 'jia qq',
                # 兼职/代理类
                'jian zhi', 'dai li',
                # 约炮/色情类
                'yue pao', 'yue ma', 'bao yue',
                # 赌博类
                'du bo', 'du qian',
                # 信用卡/贷款类
                'xin yong ka', 'dai kuan', 'tao xian',
            ]

            hits = 0
            for pat in pinyin_ad_patterns:
                if pat in pinyin_text:
                    hits += 1
                    logger.info(f"[AD] 拼音命中: 模式={pat}, 原文={msg[:40]}")

            # 命中1个加2分，命中2+个加4分
            if hits >= 2:
                return 4
            elif hits == 1:
                return 2
            return 0
        except ImportError:
            # pinyin_util 未安装，跳过
            return 0
        except Exception as e:
            logger.debug(f"[AD] 拼音检测异常: {e}")
            return 0

    @staticmethod
    def extract_message_ad_text(message, base_text: str = "") -> str:
        """从消息对象中提取可用于广告检测的文本。

        补充来源：
        - caption（图片/视频/媒体组配文）
        - link preview / web_page（标题、描述、站点名、URL）
        - sticker（emoji、set_name）
        """
        if message is None:
            return str(base_text or "").strip()
        parts = [str(base_text or "").strip()]

        caption = getattr(message, "caption", None)
        if caption:
            parts.append(str(caption).strip())

        web_page = getattr(message, "web_page", None)
        if web_page is None:
            # 部分 SDK 版本使用 link_preview 字段
            web_page = getattr(message, "link_preview", None)
        if web_page:
            for field in ("title", "description", "site_name", "url"):
                value = getattr(web_page, field, None)
                if value:
                    parts.append(str(value).strip())

        sticker = getattr(message, "sticker", None)
        if sticker:
            for field in ("emoji", "set_name"):
                value = getattr(sticker, field, None)
                if value:
                    parts.append(str(value).strip())

        return "\n".join(p for p in parts if p)

    def detect(self, username: str, msg: str, user_id: int = None, bot=None, bio: str = None, message_meta: dict = None, chat_id=None, message=None) -> dict:
        """
        核心检测函数

        Args:
            username: 用户显示名称（first_name + last_name）
            msg: 消息内容
            user_id: 用户ID（可选，用于获取更详细的用户信息）
            bot: TeleBot实例（可选，用于获取用户完整信息）
            bio: 用户资料简介/bio（可选，Telegram Bot API get_chat获取）
            message: Telegram Message 对象（可选，用于提取 caption / link preview / sticker 等文本）

        返回: {is_ad: bool, score: int, action: str, matched_rules: [str], reason: str, ad_text: str}
        """
        msg_raw = self.extract_message_ad_text(message, (msg or "")).strip()
        uname_raw = (username or "").strip()
        bio_raw = (bio or "").strip()

        # [TRAE SOLO CN] 清理零宽字符，防止广告发送者拆散关键词绕过检测
        msg_clean, msg_zwc = self._clean_zero_width(msg_raw)
        uname_clean, uname_zwc = self._clean_zero_width(uname_raw)
        total_zwc = msg_zwc + uname_zwc
        total_chars = max(1, len(msg_raw) + len(uname_raw))
        zwc_ratio = total_zwc / total_chars

        if total_zwc > 0:
            logger.info(f"[AD] 检测到零宽字符: 数量={total_zwc}, 占比={zwc_ratio:.1%}, 原始={msg_raw[:60]}")

        # [TRAE SOLO CN] v5.13.1 反广告规避规范化：全角数字/形近字/繁体 → 简体
        msg_clean = self._normalize_ad_evasion(msg_clean)
        uname_clean = self._normalize_ad_evasion(uname_clean)
        bio_raw_norm = self._normalize_ad_evasion(bio_raw)
        if bio_raw_norm != bio_raw:
            logger.info(f"[AD] Bio经规范化: 原={bio_raw[:60]} → 新={bio_raw_norm[:60]}")

        # [v5.23.0 P2-5] 拼音级广告检测：将文本转拼音后检测谐音广告词
        msg_pinyin_leak = self._check_pinyin_ad(msg_clean)
        if msg_pinyin_leak > 0:
            logger.info(f"[AD] 拼音检测命中: +{msg_pinyin_leak}分, 消息={msg_clean[:60]}")

        # [Trae] v5.3.1 优化：通过bot获取用户完整显示名称
        # [Trae CN] 修复：chat_id 为 None 时跳过 get_chat_member 调用，避免无效请求
        if bot and user_id and not uname_clean and chat_id is not None:
            try:
                chat_member = bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                if chat_member and chat_member.user:
                    uname_clean = chat_member.user.full_name or ""
            except Exception as e:
                logger.debug(f"操作异常: {e}")
        logger.info(f"[AD] 开始检测: 用户={uname_clean[:30]}, 消息={msg_clean[:80]}")

        uname_matches = self._check_username(uname_clean)
        content_score, hit_dims = self._check_content_score(msg_clean)
        # [Trae] v4.6.6 修复：用户显示名称本身也可能是广告（如"虚拟货币搬砖日挣1千U"）
        name_score, name_hit_dims = self._check_content_score(uname_clean)
        total_score = content_score + name_score
        # [v5.23.0 P2-5] 拼音级广告检测加分
        total_score += msg_pinyin_leak
        # [TRAE SOLO CN] 零宽字符占比高时额外加分（本身就是可疑行为）
        if zwc_ratio > 0.2:
            total_score += 2
            logger.info(f"[AD] 零宽字符可疑加分: +2 (占比={zwc_ratio:.1%})")
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

        # [TRAE SOLO CN] v5.7.5 新增：用户资料(Bio)广告检测（移到阈值检查前）
        bio_score = 0
        bio_hit_dims = []
        if bio_raw:
            # [TRAE SOLO CN] v5.13.1 使用规范化后的 bio 评分
            bio_clean, bio_zwc = self._clean_zero_width(bio_raw_norm)
            for pat in BIO_PATTERNS:
                try:
                    match = re.search(pat, bio_clean, re.IGNORECASE)
                    if match:
                        bio_score += 3  # bio命中权重+3（bio广告是强信号）
                        bio_hit_dims.append(f"bio命中({match.group()[:20]})")
                        logger.info(f"[AD] Bio命中: 匹配={match.group()[:30]}, 规则={pat[:50]}")
                        break  # 只计一次
                except re.error:
                    pass
            if bio_score > 0:
                total_score += bio_score
                matched_rules.append(f"Bio广告评分={bio_score}")
                reasons.append(f"Bio含广告: {', '.join(bio_hit_dims)}")
                logger.info(f"[AD] Bio评分: +{bio_score}, 命中={bio_hit_dims}")

        # [TRAE SOLO CN] v5.8.0 新增：CAS/SPB外部数据库辅助评分
        cas_score = 0
        spb_score = 0
        if user_id:
            try:
                cas_banned, cas_reason = self._check_cas(user_id)
                if cas_banned:
                    cas_score = 2
                    total_score += cas_score
                    matched_rules.append("CAS黑名单辅助+2")
                    reasons.append(f"CAS黑名单辅助评分+2: {cas_reason}")
                    logger.info(f"[AD] CAS黑名单辅助评分+2: uid={user_id}, reason={cas_reason}")
            except Exception as e:
                logger.debug(f"[AD] CAS查询异常: {e}")

            try:
                spb_spam_score, spb_blacklisted = self._check_spb(user_id)
                if spb_blacklisted or spb_spam_score >= 0.8:
                    spb_score = 2
                    total_score += spb_score
                    matched_rules.append("SPB高评分辅助+2")
                    reasons.append(f"SPB垃圾评分辅助+2 (score={spb_spam_score:.2f})")
                    logger.info(f"[AD] SPB高评分辅助+2: uid={user_id}, score={spb_spam_score:.2f}")
                elif spb_spam_score >= 0.5:
                    spb_score = 1
                    total_score += spb_score
                    matched_rules.append("SPB中评分辅助+1")
                    reasons.append(f"SPB垃圾评分辅助+1 (score={spb_spam_score:.2f})")
                    logger.info(f"[AD] SPB中评分辅助+1: uid={user_id}, score={spb_spam_score:.2f}")
            except Exception as e:
                logger.debug(f"[AD] SPB查询异常: {e}")

        # [TRAE SOLO CN] v5.8.0 新增：消息元数据检测
        metadata_score = 0
        metadata_reasons = []
        if message_meta is not None:
            metadata_score, metadata_reasons = self._check_metadata(msg_clean, message_meta, bio_score, uname_anomaly_score)
            if metadata_score > 0:
                total_score += metadata_score
                matched_rules.append(f"元数据评分={metadata_score}")
                reasons.extend(metadata_reasons)
                logger.info(f"[AD] 元数据评分: +{metadata_score}, 原因={metadata_reasons}")

        # [TRAE SOLO CN] 兜底：明确的高置信度招募话术，即使单维度评分不足也拦截
        explicit_recruit_patterns = [
            r"\u627e\u4eba\u5408\u4f5c",  # 找人合作
            r"\u62db\u56e2\u961f\u5408\u4f5c",  # 招团队合作
        ]
        if not is_ad and content_score > 0:
            for pat in explicit_recruit_patterns:
                if re.search(pat, msg_clean, re.IGNORECASE):
                    is_ad = True
                    action = "ban"
                    matched_rules.append("明确招募话术兜底")
                    reasons.append("内容命中: 招募/拉人(+2)")
                    logger.info(f"[AD] 明确招募话术兜底命中: {msg_clean[:80]}")
                    break

        # [Puzan-OS] v5.28.3 兜底：色情引流组合模式检测
        # 典型模式："出+年龄+色情词+可以过夜"（如"出23岁淫素，可以过夜"）
        if not is_ad:
            adult_combo_patterns = [
                # 出+年龄+色情词（核心模式）
                r"\u51fa[\s\S]{0,3}[0-9]+\u5c81[\s\S]{0,5}[\u6deb\u8272\u60c5\u7ea6\u670d\u52a1\u6bcd\u72d7SM]",
                # 年龄+可以+过夜/约
                r"[0-9]+\u5c81[\s\S]{0,5}\u53ef\u4ee5[\s\S]{0,3}[\u8fc7\u591c\u7ea6\u670d\u52a1]",
                # 出+年龄+过夜
                r"\u51fa[\s\S]{0,3}[0-9]+\u5c81[\s\S]{0,5}\u8fc7\u591c",
                # 色情词+交友信息+链接
                r"[\u6deb\u8272\u60c5\u7ea6\u670d\u52a1\u6bcd\u72d7SM][\s\S]{0,10}\u4ea4\u53cb[\s\S]{0,5}https?://",
            ]
            for pat in adult_combo_patterns:
                if re.search(pat, msg_clean, re.IGNORECASE):
                    is_ad = True
                    action = "ban"
                    total_score += 4  # 组合模式高权重
                    matched_rules.append("色情引流组合模式")
                    reasons.append(f"内容命中: 色情引流组合模式(+4)")
                    logger.info(f"[AD] 色情引流组合模式命中: {msg_clean[:80]}")
                    break

        # [Puzan-OS] v5.31.3 新增：明确色情骚扰话术兜底（单条消息直接封禁）
        # 覆盖聊天消息里常见的色情招嫖/引流黑话，如"水多多""看b吗""我的水"等
        if not is_ad:
            explicit_adult_patterns = [
                r"\u6c34\u591a\u591a",  # 水多多
                r"\u770b[b\u903c\u5c41]\u5417",  # 看b吗/看逼吗/看屁吗
                r"\u60f3\u770b[\s\S]{0,3}[b\u903c\u5c41\u4e73]",  # 想看b/逼/屁/乳
                r"\u89c6\u9891[\s\S]{0,3}\u770b[b\u903c]",  # 视频看b/逼
                r"\u6211\u7684\u6c34[\s\S]{0,5}\u591a",  # 我的水...多
                r"\u597d\u5927[\s\S]{0,5}\u597d\u75db",  # 好大...好痛
                r"\u597d\u75db[\s\S]{0,5}\u54e5\u54e5",  # 好痛...哥哥
                r"\u54e5\u54e5[\s\S]{0,8}\u6c34\u591a",  # 哥哥...水多
                r"\u5b9d\u5b9d[\s\S]{0,8}\u6c34\u591a",  # 宝宝...水多
                r"\u4e00\u5bf9\u4e00[\s\S]{0,8}\u89c6\u9891",  # 一对一视频
                r"\u88f8\u804a",  # 裸聊
                # [Puzan-OS] v5.31.5 新增：色情直播招嫖兜底（"无毛鲍鱼B我在直播"类）
                r"\u65e0\u6bdb[\s\S]{0,5}[\u9c8d\u9c7cBb\u903c][\s\S]{0,5}\u76f4\u64ad",  # 无毛+鲍鱼/B/逼+直播
                r"[\u9c8d\u9c7cBb\u903c][\s\S]{0,5}\u76f4\u64ad",  # 鲍鱼/B/逼+直播
                r"\u76f4\u64ad[\s\S]{0,5}[\u9c8d\u9c7c\u65e0\u6bdb\u767d\u864eBb\u903c]",  # 直播+鲍鱼/无毛/白虎/B/逼
                # [Puzan-OS] v5.31.5 新增：谐音支付宝+时长+价格色情交易兜底（"10分钟3Oo♠"类）
                r"[0-9]+[\s\S]{0,3}\u5206\u949f[\s\S]{0,5}[0-9Oo]+[\u2660\u2665\u2663\u2666Bb\u5143\u5757]",  # 数字+分钟+数字/Oo+♠/♥/B/元/块（色情符号或价格单位）
                r"[\u2660\u2665\u2663\u2666][\s\S]{0,5}[0-9Oo]+[\s\S]{0,3}\u5206\u949f",  # ♠/♥/♣/♦+数字+分钟（色情符号开头强信号）
                r"[\u652f\u5431][\s,，]*[\u4ed8\u4f0f][\s,，]*[\u5b9d\u5b9d][\s\S]{0,10}[0-9]+[\s\S]{0,3}\u5206\u949f",  # 支付宝谐音+数字+分钟
                r"[\u652f\u5431][\s,，]*[\u4ed8\u4f0f][\s,，]*[\u5b9d\u5b9d][\s\S]{0,5}\u5c31\u884c",  # 支付宝谐音+就行（接受支付宝付款）
            ]
            for pat in explicit_adult_patterns:
                if re.search(pat, msg_clean, re.IGNORECASE):
                    is_ad = True
                    action = "ban"
                    total_score += 4
                    matched_rules.append("明确色情骚扰话术兜底")
                    reasons.append("内容命中: 色情骚扰话术(+4)")
                    logger.info(f"[AD] 明确色情骚扰话术兜底命中: {msg_clean[:80]}")
                    break

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

        # [TRAE SOLO CN] v5.8.5 新增：多维度组合评分机制
        # 消息+用户名组合时降低阈值
        if not is_ad and name_score > 0 and content_score > 0:
            # 消息和用户名都命中广告，降低阈值到2
            if total_score >= 2:
                is_ad = True
                action = "ban"
                reasons.append(f"消息+用户名组合命中，降低阈值 (评分={total_score})")
                logger.info(f"[AD] 消息+用户名组合命中，降低阈值封禁: 评分={total_score}")
        
        # 用户名命中+Bio命中组合
        if not is_ad and uname_matches and bio_score > 0:
            is_ad = True
            action = "ban"
            reasons.append(f"用户名+Bio组合命中 (Bio评分={bio_score})")
            logger.info(f"[AD] 用户名+Bio组合命中封禁: Bio评分={bio_score}")
        
        # 消息命中+Bio命中组合
        if not is_ad and content_score > 0 and bio_score > 0:
            is_ad = True
            action = "ban"
            reasons.append(f"消息+Bio组合命中 (内容={content_score}, Bio={bio_score})")
            logger.info(f"[AD] 消息+Bio组合命中封禁: 内容={content_score}, Bio={bio_score}")

        if not is_ad and uname_matches and total_score > 0:
            is_ad = True
            action = "ban"
            reasons.append(f"用户名+内容组合命中 (评分={total_score})")
            logger.info(f"[AD] 用户名+内容组合命中: 评分={total_score}")

        # 单独用户名异常（无广告内容）→ 仅记录，不拦截（防误判）
        if not is_ad and uname_anomaly:
            matched_rules.append(f"用户名可疑(+{uname_anomaly_score})")
            logger.info(f"[AD] 用户名可疑但无广告内容，仅记录不拦截: {uname_anomaly_reason}")

        # [Puzan-OS v5.32] AI 边界复核：score=2 但规则引擎未判为广告时，调用 AI 复核升级
        ai_review_result = None
        if not is_ad and total_score == 2 and self.config.get("AD_AI_REVIEW_ENABLED", False):
            try:
                from modules.ai_advisor import review_borderline_ad
                ai_review_result = review_borderline_ad(
                    text=msg_clean,
                    score=total_score,
                    reason="；".join(reasons) if reasons else "规则边界评分",
                    config=self.config,
                    user_id=user_id,
                )
                if ai_review_result.get("used_ai") and ai_review_result.get("is_ad") \
                        and ai_review_result.get("confidence", 0.0) >= 0.7:
                    is_ad = True
                    action = "ban"
                    ai_reason = ai_review_result.get("reason", "AI复核升级")
                    matched_rules.append(f"AI边界复核升级(conf={ai_review_result.get('confidence', 0):.2f})")
                    reasons.append(f"AI复核: {ai_reason}")
                    logger.info(
                        f"[AD] AI边界复核升级为广告: uid={user_id} score={total_score} "
                        f"ai_conf={ai_review_result.get('confidence', 0):.2f} ai_reason={ai_reason}"
                    )
            except Exception as ai_err:
                logger.debug(f"[AD] AI边界复核调用失败: {ai_err}")
                ai_review_result = None

        reason_str = "；".join(reasons) if reasons else "未命中规则"

        result = {
            "is_ad": is_ad,
            "score": total_score,  # [Trae] v4.6.6 修复：返回总评分（含名称评分），延迟封禁才能正确累计
            "action": action,
            "matched_rules": matched_rules,
            "reason": reason_str,
            # 供调用方获取实际被检测的完整文本（含 caption / link preview 等）
            "ad_text": msg_clean[:500],
            # [TRAE SOLO CN] v5.7.5 新增：供 security_handlers 头像检测触发条件使用
            "bio_score": bio_score,
            "username_anomaly_score": uname_anomaly_score,
            "username_anomaly_reason": uname_anomaly_reason,
            "cas_score": cas_score,
            "spb_score": spb_score,
            "metadata_score": metadata_score,
            # [Puzan-OS v5.32] AI 复核结果（仅 AD_AI_REVIEW_ENABLED=true 且边界区间有值）
            "ai_review": ai_review_result,
        }

        if is_ad:
            self.stats["total_detected"] = self.stats.get("total_detected", 0) + 1
            zwc_info = f", 零宽字符={total_zwc}({zwc_ratio:.1%})" if total_zwc > 0 else ""
            logger.warning(f"[AD] 🚫 判定为广告: 用户={uname_clean[:30]}, 评分={total_score}, 动作={action}, 原因={reason_str}{zwc_info}")
        else:
            zwc_info = f", 零宽字符={total_zwc}({zwc_ratio:.1%})" if total_zwc > 0 else ""
            logger.debug(f"[AD] 检测通过: 用户={uname_clean[:30]}, 评分={content_score}{zwc_info}")

        return result

    # ──────────────────────────────────────────────────────
    # [Trae] v5.6.1 新增：连续消息模式检测
    # ──────────────────────────────────────────────────────

    def check_consecutive_patterns(self, user_id: int, chat_id: int, bot=None) -> dict:
        """
        检测同一用户连续发送的多条消息是否构成广告模式
        
        检测规则：
        1. 短时间内（15分钟）发送4条以上消息
        2. 消息内容相似度高（重复发送）
        3. 消息内容包含色情引流词组合
        4. [Puzan-OS] v5.31.4 新增：慢速刷屏检测（相似意图消息，非完全重复）
        
        返回: {"is_spam": bool, "reason": str, "score": int, "messages": list}
        """
        user_key = str(user_id)
        if user_key not in self.suspicious_users:
            return {"is_spam": False, "reason": "", "score": 0, "messages": []}
        
        user_track = self.suspicious_users[user_key]
        messages = user_track.get("messages", [])
        
        if len(messages) < 3:
            return {"is_spam": False, "reason": "", "score": 0, "messages": []}
        
        now = datetime.now(timezone.utc)
        
        # [Puzan-OS] v5.31.4 优化：扩大时间窗口到15分钟，捕获慢速刷屏
        # 原5分钟窗口太窄，3-4分钟间隔的广告会漏判
        recent_messages = []
        for msg in messages:
            msg_time = datetime.fromisoformat(msg.get("time", now.isoformat()))
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=timezone.utc)
            elapsed = (now - msg_time).total_seconds() / 60
            if elapsed <= 15:
                recent_messages.append(msg)
        
        if len(recent_messages) < 3:
            return {"is_spam": False, "reason": "", "score": 0, "messages": []}
        
        # 检测重复消息模式
        msg_texts = [m.get("text", "").strip() for m in recent_messages]
        unique_texts = list(set(msg_texts))
        
        # 如果重复消息超过50%，可能是刷屏
        if len(unique_texts) < len(msg_texts) * 0.5:
            return {
                "is_spam": True,
                "reason": f"重复消息模式：{len(recent_messages)}条消息中只有{len(unique_texts)}条不同内容",
                "score": 5,
                "messages": recent_messages
            }
        
        # 检测色情引流词组合
        adult_keywords = ["上門", "粉嫩", "紧", "约", "全套", "特服", "小姐", "少妇", "水多多", "看b", "看逼", "看b吗", "我的水", "好痛", "好大", "哥哥", "一对一视频", "裸聊", "約炮"]
        hit_count = 0
        for text in msg_texts:
            for kw in adult_keywords:
                if kw in text:
                    hit_count += 1
                    break
        
        if hit_count >= 2:
            return {
                "is_spam": True,
                "reason": f"色情引流词组合：{hit_count}条消息命中色情引流词",
                "score": 6,
                "messages": recent_messages
            }

        # [Trae CN] v5.14.2 新增：核心关键词重复率检测
        # 提取每条消息中的2字以上中文词组，计算共同关键词比例
        import re as _re
        def _extract_keywords(text):
            """提取2字以上中文词组"""
            return set(_re.findall(r'[\u4e00-\u9fa5]{2,}', text))

        all_keywords = []
        for text in msg_texts:
            kws = _extract_keywords(text)
            if kws:
                all_keywords.append(kws)

        if len(all_keywords) >= 2:
            # 计算所有消息共同出现的关键词
            common_keywords = all_keywords[0]
            for kws in all_keywords[1:]:
                common_keywords = common_keywords & kws

            if common_keywords:
                # 关键词重复率 = 共同关键词数 / 平均每条消息的关键词数
                avg_keywords = sum(len(kws) for kws in all_keywords) / len(all_keywords)
                keyword_overlap = len(common_keywords) / max(1, avg_keywords)
                if keyword_overlap > 0.6:
                    return {
                        "is_spam": True,
                        "reason": f"核心关键词重复模式：共同关键词{common_keywords}，重复率={keyword_overlap:.0%}",
                        "score": 5,
                        "messages": recent_messages
                    }

        # [Puzan-OS] v5.31.4 新增：慢速刷屏检测（相似意图消息）
        # 检测高频引流词组合，即使消息不完全重复
        ad_intent_keywords = [
            "点我", "发财", "翻身", "赚钱", "风口", "错过", "后悔",
            "加我", "私我", "联系", "领取", "福利", "点击", "加入",
            "唯一", "机会", "限时", "最后", "马上", "赶紧",
        ]
        hit_intent_count = 0
        for text in msg_texts:
            for kw in ad_intent_keywords:
                if kw in text:
                    hit_intent_count += 1
                    break
        
        # 15分钟内4+条消息命中引流词，判定为慢速刷屏
        if hit_intent_count >= 4:
            return {
                "is_spam": True,
                "reason": f"慢速刷屏模式：{len(recent_messages)}条消息中{hit_intent_count}条命中引流关键词",
                "score": 5,
                "messages": recent_messages
            }

        return {"is_spam": False, "reason": "", "score": 0, "messages": []}

    # ──────────────────────────────────────────────────────
    # [Trae] v4.6.2 新增：延迟封禁机制
    # ──────────────────────────────────────────────────────

    def track_suspicious_user(
        self,
        user_id: int,
        msg_id: int,
        chat_id: int,
        text: str,
        score: int,
        is_ad: bool = False,
    ) -> dict:
        """
        追踪用户消息历史（无论score多少都追踪，用于连续消息模式检测）
        同时累计可疑评分，达到阈值后触发延迟封禁
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
            "is_ad": is_ad is True,
            "time": now.isoformat(),
        })

        total_score = user_track["score"]
        msg_count = len(user_track["messages"])

        self._save_tracking_to_db(user_id)

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
            # score=0 也追踪了消息历史，返回 none 不干扰主流程
            return {"action": "none", "total_score": total_score, "messages": list(user_track["messages"])}

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
            self._delete_tracking_from_db(user_id)
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
            self._delete_tracking_from_db(user_key)
            logger.debug(f"[AD] 清理过期追踪记录: uid={user_key}")

    def process_pending_bans(self, bot, config: dict):
        """
        [TRAE SOLO CN] 启动时处理未完成的封禁任务（从数据库恢复的追踪数据）
        
        [Trae] v5.3.1 优化：
        1. 添加更详细的日志记录
        2. 改进错误处理，避免单个用户失败影响其他用户
        3. 添加启动追溯统计报告
        """
        if not bot or not self.suspicious_users:
            return

        pending_bans = []
        for user_key, track in list(self.suspicious_users.items()):
            if track["score"] >= self.SUSPICIOUS_THRESHOLD:
                pending_bans.append((user_key, track))

        if not pending_bans:
            logger.info("[AD] 启动检查：无待处理的封禁任务")
            return

        logger.warning(f"[AD] 🚨 启动追溯：发现 {len(pending_bans)} 个待封禁用户")

        admin_id = config.get("ADMIN_ID", 0)
        enable_delete = can_delete_message(config)
        
        # 统计信息
        total_deleted = 0
        total_banned = 0
        total_failed = 0
        processed_users = []

        for user_key, track in pending_bans:
            uid = int(user_key)
            total_score = track["score"]
            messages = track["messages"]
            
            user_info = {"uid": uid, "score": total_score, "deleted": 0, "banned": False}

            # 删除历史消息
            if enable_delete:
                for msg_info in messages:
                    try:
                        bot.delete_message(msg_info["chat_id"], msg_info["msg_id"])
                        user_info["deleted"] += 1
                        total_deleted += 1
                    except Exception as e:
                        err_msg = str(e)
                        # 常见错误：消息已删除、消息太旧、Bot不在群中
                        if "message to delete not found" in err_msg.lower():
                            logger.debug(f"消息已不存在 msg_id={msg_info.get('msg_id')}")
                        elif "message can't be deleted" in err_msg.lower():
                            logger.debug(f"消息无法删除（可能太旧）msg_id={msg_info.get('msg_id')}")
                        else:
                            logger.debug(f"启动追溯删除消息失败 msg_id={msg_info.get('msg_id')}: {e}")

            # [Codex] 广告治理策略：永久禁言+黑名单+删消息，不踢人
            for msg_info in messages:
                chat_id = msg_info.get("chat_id")
                if chat_id:
                    try:
                        from modules.ad_enforcement import enforce_ad_user
                        enforce_ad_user(
                            bot=bot,
                            db=self.db,
                            config=config,
                            chat_id=chat_id,
                            uid=uid,
                            uname=str(uid),
                            reason=f"启动追溯-评分{total_score}",
                            current_msg_id=msg_info.get("msg_id", 0),
                            notify_admin=False,
                        )
                        logger.warning(f"[AD] 启动追溯永久禁言: uid={uid}, 累计评分={total_score}, chat_id={chat_id}")
                        user_info["banned"] = True
                        total_banned += 1
                        break
                    except Exception as e:
                        err_msg = str(e)
                        if "403" in err_msg and "blocked" in err_msg.lower():
                            logger.debug(f"用户已屏蔽Bot，跳过启动追溯禁言: uid={uid}")
                            break
                        elif "user is not a member" in err_msg.lower():
                            logger.debug(f"用户已不在群中，跳过禁言: uid={uid}")
                            break
                        else:
                            logger.warning(f"启动追溯禁言失败: uid={uid}, {e}")
                            total_failed += 1

            processed_users.append(user_info)
            self.clear_user_tracking(uid)

        # 发送汇总报告给管理员
        if admin_id:
            try:
                report_lines = [
                    f"🚨 启动追溯封禁完成",
                    f"━━━━━━━━━━━━━━━",
                    f"👥 处理用户数：{len(pending_bans)}",
                    f"🗑 删除消息：{total_deleted}条",
                    f"🔇 成功永久禁言：{total_banned}人",
                    f"⚠️ 禁言失败：{total_failed}人",
                    f"━━━━━━━━━━━━━━━",
                ]
                
                # 显示最近5个用户的详情
                for i, ui in enumerate(processed_users[:5], 1):
                    status = "✅" if ui["banned"] else "❌"
                    report_lines.append(f"{i}. {status} uid={ui['uid']} 评分={ui['score']} 删除={ui['deleted']}条")
                
                if len(processed_users) > 5:
                    report_lines.append(f"... 还有{len(processed_users) - 5}个用户")
                
                report_lines.append(f"\n💡 如有误封请手动解禁")

                bot.send_message(admin_id, "\n".join(report_lines))
            except Exception as e:
                logger.warning(f"启动追溯报告发送失败: {e}")

        logger.info(f"[AD] 启动追溯封禁完成：处理 {len(pending_bans)} 个用户，删除 {total_deleted} 条消息，永久禁言 {total_banned} 人")

    def retroactive_scan(self, bot, chat_id: int, start_msg_id: int, end_msg_id: int, admin_id: int = 0, config: dict = None) -> dict:
        """
        [TRAE SOLO CN] 追溯扫描群内历史消息，识别并删除广告

        双模式：
        1. forwardMessage 模式：逐条转发读取内容，用 detect() 判断是否为广告
        2. 数据库驱动模式：群组有保护内容时，从追踪记录获取消息ID直接删除

        Args:
            bot: TeleBot 实例
            chat_id: 群组 ID
            start_msg_id: 起始消息 ID（含）
            end_msg_id: 结束消息 ID（含）
            admin_id: 管理员 ID（用于转发读取内容）
            config: 配置字典（None时跳过ENABLE_MESSAGE_DELETION检查，用于管理员手动命令）

        Returns:
            dict: {scanned, ads_found, deleted, failed, skipped, not_found, details, mode}
        """
        import time as _time

        result = {
            "scanned": 0,
            "ads_found": 0,
            "deleted": 0,
            "failed": 0,
            "skipped": 0,
            "not_found": 0,
            "details": [],
            "mode": "forward",
        }

        if start_msg_id > end_msg_id:
            return result

        total_range = end_msg_id - start_msg_id + 1
        logger.info(f"[AD] 🔍 追溯扫描开始: chat_id={chat_id}, range={start_msg_id}~{end_msg_id} ({total_range}条)")

        # 先测试 forwardMessage 是否可用
        use_forward = True
        try:
            test_fwd = bot.forward_message(admin_id, chat_id, end_msg_id, disable_notification=True)
            if test_fwd:
                bot.delete_message(admin_id, test_fwd.message_id)
        except Exception as e:
            err_str = str(e).lower()
            if "protected content" in err_str:
                use_forward = False
                logger.info("[AD] 追溯扫描: 群组有保护内容，切换到数据库驱动模式")
            elif "not found" in err_str:
                pass
            else:
                use_forward = False
                logger.info(f"[AD] 追溯扫描: forwardMessage不可用({err_str[:60]})，切换到数据库驱动模式")

        if use_forward:
            result["mode"] = "forward"
            result = self._retroactive_scan_forward(bot, chat_id, start_msg_id, end_msg_id, admin_id, result, config)
        else:
            result["mode"] = "database"
            result = self._retroactive_scan_database(bot, chat_id, start_msg_id, end_msg_id, result, config)

        logger.info(
            f"[AD] 🔍 追溯扫描完成(mode={result['mode']}): 扫描={result['scanned']}, "
            f"广告={result['ads_found']}, 删除={result['deleted']}, "
            f"失败={result['failed']}, 跳过={result['skipped']}, "
            f"不存在={result['not_found']}"
        )
        return result

    def _retroactive_scan_forward(self, bot, chat_id, start_msg_id, end_msg_id, admin_id, result, config=None):
        """forwardMessage 模式：逐条转发读取内容判断广告"""
        import time as _time

        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                fwd_msg_id = None
                try:
                    fwd = bot.forward_message(admin_id, chat_id, msg_id, disable_notification=True)
                    if not fwd:
                        result["not_found"] += 1
                        continue
                    fwd_msg_id = fwd.message_id
                except Exception as fwd_err:
                    err_str = str(fwd_err).lower()
                    if "not found" in err_str:
                        result["not_found"] += 1
                        continue
                    elif "protected content" in err_str:
                        logger.info("[AD] 追溯扫描: 检测到保护内容，切换到数据库驱动模式")
                        return self._retroactive_scan_database(bot, chat_id, start_msg_id, end_msg_id, result, config)
                    elif "forbidden" in err_str or "bot was blocked" in err_str:
                        result["not_found"] += 1
                        continue
                    elif "429" in err_str or "flood" in err_str:
                        retry_after = 5
                        try:
                            import re as _re
                            _m = _re.search(r"retry after (\d+)", str(fwd_err), _re.IGNORECASE)
                            if _m:
                                retry_after = int(_m.group(1))
                        except Exception as e:
                            logger.debug(f"操作异常: {e}")
                        logger.warning(f"[AD] 追溯扫描: API限速, 等待{retry_after}秒后继续")
                        _time.sleep(retry_after)
                        continue
                    else:
                        result["not_found"] += 1
                        continue

                result["scanned"] += 1

                text = fwd.text or fwd.caption or ""
                from_user = fwd.forward_from or fwd.from_user
                display_name = ""
                uid = 0
                if from_user:
                    display_name = (from_user.first_name or "") + " " + (from_user.last_name or "")
                    uid = from_user.id

                ad_result = self.detect(display_name.strip(), text, uid, bot)
                is_ad = ad_result.get("is_ad", False)

                if is_ad:
                    result["ads_found"] += 1
                    if config is None or can_delete_message(config):
                        try:
                            bot.delete_message(chat_id, msg_id)
                            result["deleted"] += 1
                            preview = text[:60].replace("\n", " ") if text else "(无文本)"
                            logger.info(f"[AD] 🗑️ 追溯删除: msg_id={msg_id} | {preview}")
                            result["details"].append({"msg_id": msg_id, "uid": uid, "text_preview": preview, "score": ad_result.get("score", 0), "deleted": True})
                        except Exception as del_err:
                            result["failed"] += 1
                            result["details"].append({"msg_id": msg_id, "uid": uid, "text_preview": text[:60] if text else "", "score": ad_result.get("score", 0), "deleted": False, "error": str(del_err)[:100]})
                    else:
                        result["details"].append({"msg_id": msg_id, "uid": uid, "text_preview": text[:60] if text else "", "score": ad_result.get("score", 0), "deleted": False, "reason": "deletion_disabled"})
                else:
                    result["skipped"] += 1

                if fwd_msg_id:
                    try:
                        bot.delete_message(admin_id, fwd_msg_id)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
                if result["scanned"] % 20 == 0:
                    _time.sleep(1)

            except Exception as e:
                logger.debug(f"[AD] 追溯扫描异常: msg_id={msg_id}, {e}")
                result["failed"] += 1

        return result

    def _retroactive_scan_database(self, bot, chat_id, start_msg_id, end_msg_id, result, config=None):
        """数据库驱动模式：仅删除有明确广告证据的已追踪消息。"""

        # 1. 只读取当前追踪窗口内的记录，过期记录不能参与启动追溯。
        tracked_messages = []
        try:
            if self.db:
                cutoff = datetime.now(timezone.utc).timestamp() - (self.SUSPICIOUS_WINDOW_MINUTES * 60)
                rows = self.db.conn.execute(
                    "SELECT user_id, messages FROM ad_suspicious_users WHERE updated_at > ?",
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    try:
                        msgs = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                        for m in msgs:
                            if isinstance(m, dict) and "msg_id" in m and "chat_id" in m:
                                if m["chat_id"] == chat_id and start_msg_id <= m["msg_id"] <= end_msg_id:
                                    m.setdefault("uid", row[0])
                                    tracked_messages.append(m)
                    except Exception as e:
                        logger.debug(f"操作异常: {e}")
        except Exception as e:
            logger.debug(f"[AD] 追溯扫描: 读取追踪记录失败: {e}")

        # 2. 从 suspicious_users 内存获取
        for user_key, track in self.suspicious_users.items():
            for m in track.get("messages", []):
                if isinstance(m, dict) and "msg_id" in m and "chat_id" in m:
                    if m["chat_id"] == chat_id and start_msg_id <= m["msg_id"] <= end_msg_id:
                        if not any(tm["msg_id"] == m["msg_id"] for tm in tracked_messages):
                            tracked_messages.append(m)

        if not tracked_messages:
            # 保护内容群无法重新读取消息正文。没有逐条证据时必须 fail-close，
            # 禁止按消息 ID 范围盲删，否则会删除正常聊天。
            logger.info("[AD] 追溯扫描(数据库模式): 无可核验追踪记录，安全跳过，不执行范围删除")
            return result

        # 有追踪记录也不等于广告。只有显式 is_ad=True，或单条评分已达到
        # 广告阈值的旧记录，才允许进入删除链。
        logger.info(f"[AD] 追溯扫描(数据库模式): 发现 {len(tracked_messages)} 条追踪消息")
        allow_delete = config is None or can_delete_message(config)
        for m in tracked_messages:
            msg_id = m["msg_id"]
            result["scanned"] += 1
            try:
                stored_score = int(m.get("score", 0) or 0)
            except (TypeError, ValueError):
                stored_score = 0
            confirmed_ad = m.get("is_ad") is True or stored_score >= self.SUSPICIOUS_THRESHOLD
            if not confirmed_ad:
                result["skipped"] += 1
                text_preview = m.get("text", "")[:60].replace("\n", " ") if m.get("text") else "(无文本)"
                logger.info(
                    f"[AD] 追溯安全跳过: msg_id={msg_id} score={stored_score} "
                    f"is_ad={m.get('is_ad', False)!r} | {text_preview}"
                )
                result["details"].append({
                    "msg_id": msg_id,
                    "uid": m.get("uid", 0),
                    "text_preview": text_preview,
                    "score": stored_score,
                    "deleted": False,
                    "reason": "unconfirmed_ad_evidence",
                })
                continue
            result["ads_found"] += 1
            if not allow_delete:
                result["details"].append({"msg_id": msg_id, "uid": m.get("uid", 0), "text_preview": m.get("text", "")[:60] if m.get("text") else "(无文本)", "score": stored_score, "deleted": False, "reason": "deletion_disabled"})
                continue
            try:
                bot.delete_message(chat_id, msg_id)
                result["deleted"] += 1
                text_preview = m.get("text", "")[:60].replace("\n", " ") if m.get("text") else "(无文本)"
                logger.info(f"[AD] 🗑️ 追溯删除(追踪): msg_id={msg_id} | {text_preview}")
                result["details"].append({"msg_id": msg_id, "uid": m.get("uid", 0), "text_preview": text_preview, "score": stored_score, "deleted": True})
                try:
                    if self.db and hasattr(self.db, "mark_message_deleted"):
                        self.db.mark_message_deleted(chat_id, msg_id)
                except Exception as mark_err:
                    logger.warning(f"[AD] 追溯删除后审计标记失败: chat_id={chat_id} msg_id={msg_id}: {mark_err}")
            except Exception as e:
                result["failed"] += 1
                err_str = str(e).lower()
                if "not found" in err_str:
                    result["not_found"] += 1
                    result["failed"] -= 1
                else:
                    result["details"].append({"msg_id": msg_id, "uid": m.get("uid", 0), "deleted": False, "error": str(e)[:100]})

        return result

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
