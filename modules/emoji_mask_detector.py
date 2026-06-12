"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/emoji_mask_detector.py  ·  反emoji面具破解模块                ║
║  (参考 OmniGest 思路)                                                    ║
║                                                                        ║
║  功能：检测用户名中用emoji间隔的广告词，如 "看📱我📱简📱介"。             ║
║        剥离emoji后检查是否包含引流关键词。                              ║
║                                                                        
║  流程：                                                                ║
║    1. 提取用户名中的纯文本部分（去除emoji）                            ║
║    2. 检查纯文本是否包含广告关键词                                    ║
║    3. 如果包含，按广告处理流程封禁                                    ║
║                                                                        
║  被调用：main.py P0 新人入群处理 + P3.5 广告检测                     ║
══════════════════════════════════════════════════════════════════════════╝
"""

import re
from core.logging_util import get_logger
from modules.ad_patterns_encoded import BIO_PATTERNS, USERNAME_PATTERNS

logger = get_logger("emoji_mask_detector")


def remove_emojis(text: str) -> str:
    """
    移除文本中的所有emoji字符
    返回纯文本部分
    """
    # Unicode emoji范围
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002500-\U00002BEF"  # chinese char
        "\U00002702-\U000027B0"
        "\U00002702-\U000027B0"
        # [Codex] 不使用 U+24C2-U+1F251 这种超宽区间，避免把中文一起删掉。
        "\U0001F170-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"  # dingbats
        "\u3030"
        "]+", 
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def detect_emoji_mask(text: str, config: dict) -> tuple:
    """
    检测emoji面具
    返回 (is_masked, detected_keyword, pure_text)
    """
    # 首先检查是否包含emoji
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\u2640-\u2642\u2600-\u2B55"
        "\U0001f926-\U0001f937\U00010000-\U0010ffff\u200d\u23cf\u23e9\u231a\ufe0f\u3030]"
    )
    
    if not emoji_pattern.search(text):
        return False, None, text
    
    # 移除emoji得到纯文本
    pure_text = remove_emojis(text)
    pure_text = re.sub(r'\s+', '', pure_text)  # 移除所有空白字符
    
    if not pure_text or len(pure_text) < 2:
        return False, None, pure_text
    
    # [Codex] 优先复用广告主规则，避免 emoji 面具维护一份过期小词表。
    for pattern in USERNAME_PATTERNS + BIO_PATTERNS:
        try:
            if re.search(pattern, pure_text, re.IGNORECASE):
                return True, f"广告正则:{pattern[:30]}", pure_text
        except re.error:
            logger.debug(f"emoji_mask_detector 跳过异常正则: {pattern[:30]}")

    # 配置关键词只作为兜底，兼容老配置。
    auto_mute_names = config.get("AUTO_MUTE_NAMES", [])
    
    for keyword in auto_mute_names:
        # 关键词在纯文本中出现
        if keyword.lower() in pure_text.lower():
            return True, keyword, pure_text
    
    # 检查是否是连续字母数字被emoji分割的情况（如 ytzrgwnqc6 被分割）
    alphanumeric_pattern = re.compile(r'[a-zA-Z0-9]+')
    alphanums = alphanumeric_pattern.findall(pure_text)
    for alphanum in alphanums:
        if len(alphanum) >= 6:  # 6位以上认为是可疑用户名
            for keyword in auto_mute_names:
                if keyword.lower() in alphanum.lower():
                    return True, keyword, pure_text
    
    return False, None, pure_text


def check_emoji_mask_in_username(user_name: str, config: dict) -> tuple:
    """
    检查用户名中的emoji面具
    返回 (is_suspicious, reason)
    """
    is_masked, detected_keyword, pure_text = detect_emoji_mask(user_name, config)
    
    if is_masked:
        reason = f"Emoji面具检测命中关键词: '{detected_keyword}' (原文: '{user_name}' → 纯文本: '{pure_text}')"
        return True, reason
    
    return False, None


def check_emoji_mask_in_message(message_text: str, config: dict) -> tuple:
    """
    检查消息内容中的emoji面具
    返回 (is_suspicious, reason)
    """
    is_masked, detected_keyword, pure_text = detect_emoji_mask(message_text, config)
    
    if is_masked:
        reason = f"消息Emoji面具检测命中关键词: '{detected_keyword}' (原文: '{message_text}' → 纯文本: '{pure_text}')"
        return True, reason
    
    return False, None
