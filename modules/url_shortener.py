"""
URL缩短 - 缩短长链接

命令：
  /shorten URL → handle_shorten
"""
import urllib.parse
from core.logging_util import get_logger
from core.http_client import get_http_client, HTTPRequestError

logger = get_logger("url_shortener")


def handle_shorten(bot, m, config, db):
    """缩短URL"""
    text = (m.text or "").strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        bot.reply_to(m, "❌ 用法：/shorten URL")
        return

    url = parts[1].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        # 使用统一HTTP客户端
        client = get_http_client()

        # 使用 is.gd 免费API
        api_url = "https://is.gd/create.php"
        params = {
            "format": "json",
            "url": url
        }
        data = client.get(api_url, params=params, timeout=10)

        if data.get("shorturl"):
            bot.reply_to(m, f"🔗 短链接：{data['shorturl']}\n📎 原链接：{url}")
        elif data.get("errormessage"):
            bot.reply_to(m, f"❌ 缩短失败：{data['errormessage']}")
        else:
            bot.reply_to(m, "❌ 缩短失败，请稍后再试")

    except HTTPRequestError as e:
        logger.error(f"URL缩短请求失败: {e}")
        bot.reply_to(m, "❌ 缩短失败，请稍后再试")
    except Exception as e:
        logger.error(f"URL缩短异常: {e}")
        bot.reply_to(m, "❌ 缩短失败，请稍后再试")
