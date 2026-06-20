"""
搜索工具 - Google(DuckDuckGo)和Wikipedia搜索

命令：
  /google 关键词 → handle_google
  /wiki 关键词 → handle_wiki
"""
import json
from core.logging_util import get_logger
from core.http_client import get_http_client, HTTPRequestError

logger = get_logger("search")


def handle_google(bot, m, config, db):
    """Google搜索（使用DuckDuckGo Instant Answer API）"""
    text = (m.text or "").strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/google 关键词")
        return

    query = parts[1].strip()

    try:
        # 使用统一HTTP客户端
        client = get_http_client()

        # 使用DuckDuckGo Instant Answer API
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": "1"
        }
        data = client.get(url, params=params, timeout=10)

        results = []
        # Abstract
        if data.get("AbstractText"):
            results.append(f"📖 {data['AbstractText']}")
            if data.get("AbstractURL"):
                results.append(f"🔗 {data['AbstractURL']}")

        # Related Topics
        for topic in (data.get("RelatedTopics") or [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(f"• {topic['Text']}")
                if topic.get("FirstURL"):
                    results.append(f"  🔗 {topic['FirstURL']}")

        if not results:
            # 回退：使用HTML搜索链接
            search_url = f"https://www.google.com/search?q={query}"
            results.append(f"🔍 未找到即时结果，点击搜索：\n🔗 {search_url}")

        reply = f"🔍 搜索：{query}\n━━━━━━━━━━━━━\n" + "\n".join(results)
        bot.reply_to(m, reply[:4000])

    except HTTPRequestError as e:
        logger.error(f"搜索请求失败: {e}")
        bot.reply_to(m, "❌ 搜索失败，请稍后再试")
    except Exception as e:
        logger.error(f"搜索异常: {e}")
        bot.reply_to(m, "❌ 搜索失败，请稍后再试")


def handle_wiki(bot, m, config, db):
    """Wikipedia搜索"""
    text = (m.text or "").strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/wiki 关键词")
        return

    query = parts[1].strip()

    try:
        # 使用统一HTTP客户端
        client = get_http_client()

        url = f"https://zh.wikipedia.org/api/rest_v1/page/summary/{query}"
        data = client.get(url, timeout=10)

        if data.get("type") == "disambiguation":
            bot.reply_to(m, f"📚 该词条有多个含义，请更精确搜索\n🔗 {data.get('content_urls', {}).get('desktop', {}).get('page', '')}")
            return

        title = data.get("title", query)
        extract = data.get("extract", "无摘要")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        reply = f"📚 {title}\n━━━━━━━━━━━━━\n{extract}"
        if page_url:
            reply += f"\n\n🔗 {page_url}"

        bot.reply_to(m, reply[:4000])

    except HTTPRequestError as e:
        logger.error(f"Wiki搜索请求失败: {e}")
        bot.reply_to(m, "❌ Wikipedia搜索失败，请稍后再试")
    except Exception as e:
        logger.error(f"Wiki搜索异常: {e}")
        bot.reply_to(m, "❌ Wikipedia搜索失败，请稍后再试")
