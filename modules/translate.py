# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/translate.py  ·  翻译模块                                      ║
║                                                                        ║
║  功能：                                                                ║
║    handle_translate - 翻译文本                                          ║
║                                                                        ║
║  数据源：MyMemory免费API                                                ║
║  无需API Key（免费额度充足）                                            ║
║  支持格式：/tr en Hello world、回复消息 /tr en                          ║
║  被调用：main.py 指令分发                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from core.logging_util import get_logger

logger = get_logger("translate")

# 常用语言代码映射（方便用户输入）
LANG_ALIASES = {
    "中文": "zh", "中": "zh", "汉": "zh", "zh": "zh",
    "英文": "en", "英": "en", "英语": "en", "en": "en",
    "日文": "ja", "日": "ja", "日语": "ja", "ja": "ja",
    "韩文": "ko", "韩": "ko", "韩语": "ko", "ko": "ko",
    "法文": "fr", "法": "fr", "法语": "fr", "fr": "fr",
    "德文": "de", "德": "de", "德语": "de", "de": "de",
    "西班牙文": "es", "西": "es", "西班牙语": "es", "es": "es",
    "俄文": "ru", "俄": "ru", "俄语": "ru", "ru": "ru",
    "葡萄牙文": "pt", "葡": "pt", "葡萄牙语": "pt", "pt": "pt",
    "意大利文": "it", "意": "it", "意大利语": "it", "it": "it",
    "阿拉伯文": "ar", "阿": "ar", "阿拉伯语": "ar", "ar": "ar",
    "泰文": "th", "泰": "th", "泰语": "th", "th": "th",
    "越南文": "vi", "越": "vi", "越南语": "vi", "vi": "vi",
}


def _resolve_lang(lang_input: str) -> str:
    """解析语言代码，支持中文别名和标准代码"""
    lang_input = lang_input.strip().lower()
    return LANG_ALIASES.get(lang_input, lang_input)


def handle_translate(bot, m, config, db):
    """翻译文本

    支持格式：
        /tr en Hello world   → 翻译Hello world到英文
        /tr                  → 回复消息翻译到中文（默认）
        /tr en               → 回复消息翻译到英文
        /tr 你好             → 翻译"你好"到中文（默认目标语言）

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
    """
    text = m.text or ""
    # 去掉命令部分
    parts = text.split(None, 2)
    # parts[0] = "/tr" 或 "/tr@bot"

    target_lang = "zh"  # 默认翻译到中文
    query_text = ""

    if len(parts) >= 2:
        # 第二个参数可能是语言代码或要翻译的文本
        second = parts[1]
        resolved = _resolve_lang(second)
        # 判断是否为语言代码（2-3个字母，或已解析的别名）
        if len(resolved) <= 3 and resolved.isalpha():
            target_lang = resolved
            if len(parts) >= 3:
                query_text = parts[2].strip()
        else:
            # 不是语言代码，当作翻译文本
            query_text = " ".join(parts[1:]).strip()

    # 如果没有文本，尝试从回复消息获取
    if not query_text and m.reply_to_message:
        replied = m.reply_to_message
        query_text = replied.text or replied.caption or ""

    if not query_text:
        bot.reply_to(m, "❌ 请输入要翻译的文本，或回复一条消息使用 /tr\n"
                        "用法：/tr [目标语言] <文本>\n"
                        "示例：/tr en 你好 / /tr Hello world")
        return

    # 限制文本长度，避免API超限
    if len(query_text) > 500:
        query_text = query_text[:500]
        bot.reply_to(m, "⚠️ 文本过长，已截取前500字符翻译")

    try:
        from core.http_client import get_http_client, HTTPRequestError
        client = get_http_client()

        url = "https://api.mymemory.translated.net/get"
        params = {
            "q": query_text,
            "langpair": f"auto|{target_lang}"
        }
        data = client.get(url, params=params, timeout=10)

        if data.get("responseStatus") == 200 or data.get("responseData", {}).get("translatedText"):
            translated = data["responseData"]["translatedText"]
            # MyMemory有时返回和原文一样的大写结果，表示翻译失败
            if translated and translated.upper() != query_text.upper():
                result = f"🌐 翻译结果\n"
                result += f"━━━━━━━━━━━━━\n"
                result += f"📝 原文：{query_text}\n"
                result += f"✅ 译文：{translated}\n"
                result += f"🎯 目标语言：{target_lang}"
                bot.reply_to(m, result)
            else:
                bot.reply_to(m, "❌ 翻译失败，可能不支持该语言对或文本过短")
        else:
            error_msg = data.get("responseData", {}).get("translatedText", "未知错误")
            bot.reply_to(m, f"❌ 翻译失败：{error_msg}")

    except HTTPRequestError as e:
        logger.error(f"翻译失败: {e}")
        bot.reply_to(m, "❌ 翻译失败，请稍后再试")
    except Exception as e:
        logger.error(f"翻译异常: {e}")
        bot.reply_to(m, "❌ 翻译失败，请稍后再试")
