"""
core/i18n.py  ·  多语言支持模块

提供简单的语言包加载和翻译功能：
- JSON 格式语言文件（易于维护）
- _() 函数用于翻译
- 支持按用户 language_code 切换语言
- 默认语言：中文（zh-CN）
"""

import json
import os
from typing import Dict, Any
from threading import local

from core.logging_util import get_logger

logger = get_logger("i18n")

# ── 线程本地存储（每个线程独立的当前语言）────────────────────────
_thread_local = local()

# ── 语言包缓存（避免重复加载）────────────────────────────────────
_lang_cache: Dict[str, Dict[str, str]] = {}

# ── 默认配置 ─────────────────────────────────────────────────────
DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_LANGUAGES = ["zh-CN", "en-US"]
I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "i18n")


def load_language(lang_code: str) -> Dict[str, str]:
    """加载指定语言的翻译包

    Args:
        lang_code: 语言代码，如 "zh-CN", "en-US"

    Returns:
        翻译字典，key 为翻译键，value 为翻译文本
    """
    # 检查缓存
    if lang_code in _lang_cache:
        return _lang_cache[lang_code]

    # 规范化语言代码
    lang_code = _normalize_lang(lang_code)

    # 再次检查缓存（规范化后可能命中）
    if lang_code in _lang_cache:
        return _lang_cache[lang_code]

    # 加载语言文件
    lang_file = os.path.join(I18N_DIR, f"{lang_code}.json")
    try:
        with open(lang_file, "r", encoding="utf-8") as f:
            translations = json.load(f)
        _lang_cache[lang_code] = translations
        logger.debug(f"加载语言包成功: {lang_code}")
        return translations
    except FileNotFoundError:
        logger.warning(f"语言包文件不存在: {lang_file}，回退到默认语言")
        # 回退到默认语言
        if lang_code != DEFAULT_LANGUAGE:
            return load_language(DEFAULT_LANGUAGE)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"语言包 JSON 解析失败: {lang_file}, 错误: {e}")
        return {}


def _normalize_lang(lang_code: str) -> str:
    """规范化语言代码

    支持常见变体：
    - zh, zh_CN, zh-CN → zh-CN
    - en, en_US, en-US → en-US
    """
    if not lang_code:
        return DEFAULT_LANGUAGE

    lang_code = lang_code.strip()

    # 中文变体
    if lang_code.lower() in ("zh", "zh_cn", "zh-cn", "zh_cn"):
        return "zh-CN"

    # 英文变体
    if lang_code.lower() in ("en", "en_us", "en-us", "en_us"):
        return "en-US"

    # 检查是否支持
    if lang_code in SUPPORTED_LANGUAGES:
        return lang_code

    # 尝试匹配前缀
    prefix = lang_code.split("-")[0].split("_")[0].lower()
    for supported in SUPPORTED_LANGUAGES:
        if supported.lower().startswith(prefix):
            return supported

    return DEFAULT_LANGUAGE


def set_language(lang_code: str) -> None:
    """设置当前线程的语言

    Args:
        lang_code: 语言代码，如 "zh-CN", "en-US", "zh", "en"
    """
    normalized = _normalize_lang(lang_code)
    _thread_local.language = normalized
    # 预加载语言包
    load_language(normalized)


def get_language() -> str:
    """获取当前线程的语言代码

    Returns:
        当前语言代码，默认返回 DEFAULT_LANGUAGE
    """
    return getattr(_thread_local, "language", DEFAULT_LANGUAGE)


def _(key: str, default: str = None, **kwargs) -> str:
    """翻译函数

    Args:
        key: 翻译键
        default: 默认文本（当翻译不存在时使用）
        **kwargs: 格式化参数，用于替换翻译文本中的 {placeholder}

    Returns:
        翻译后的文本

    Examples:
        >>> _("welcome_message")
        '欢迎使用 Mory 小助理！'
        >>> _("hello_user", name="张三")
        '你好，张三！'
        >>> _("unknown_key", default="默认文本")
        '默认文本'
    """
    lang = get_language()
    translations = load_language(lang)

    # 获取翻译
    text = translations.get(key)

    # 翻译不存在时使用默认值或键本身
    if text is None:
        text = default if default is not None else key

    # 格式化参数替换
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.debug(f"翻译格式化失败: key={key}, error={e}")

    return text


def t(key: str, lang_code: str = None, default: str = None, **kwargs) -> str:
    """指定语言的翻译函数（不改变当前线程语言）

    Args:
        key: 翻译键
        lang_code: 语言代码（为 None 时使用当前线程语言）
        default: 默认文本
        **kwargs: 格式化参数

    Returns:
        翻译后的文本
    """
    if lang_code is None:
        return _(key, default=default, **kwargs)

    normalized = _normalize_lang(lang_code)
    translations = load_language(normalized)

    text = translations.get(key)
    if text is None:
        text = default if default is not None else key

    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError) as e:
            logger.debug(f"翻译格式化失败: key={key}, lang={normalized}, error={e}")

    return text


def get_user_language(user) -> str:
    """从 Telegram 用户对象获取语言代码

    Args:
        user: Telegram User 对象（有 language_code 属性）

    Returns:
        规范化的语言代码
    """
    lang_code = getattr(user, "language_code", None)
    return _normalize_lang(lang_code)


def set_user_language(user) -> None:
    """根据 Telegram 用户对象设置当前线程语言

    Args:
        user: Telegram User 对象
    """
    lang_code = get_user_language(user)
    set_language(lang_code)


def reload_languages() -> None:
    """重新加载所有语言包（用于开发调试）"""
    global _lang_cache
    _lang_cache.clear()
    logger.info("语言包缓存已清空")


def get_supported_languages() -> list:
    """获取支持的语言列表

    Returns:
        语言代码列表
    """
    return SUPPORTED_LANGUAGES.copy()


# ── 便捷装饰器 ────────────────────────────────────────────────────
def with_language(lang_code: str):
    """装饰器：临时设置语言执行函数

    Usage:
        @with_language("en-US")
        def send_english_message():
            return _("welcome_message")
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            old_lang = get_language()
            try:
                set_language(lang_code)
                return func(*args, **kwargs)
            finally:
                set_language(old_lang)
        return wrapper
    return decorator
