"""
URL缩短 - 缩短长链接

命令：
  /shorten URL → handle_shorten
"""
import json
import urllib.request
import urllib.parse
from core.logging_util import get_logger

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
        # 使用 is.gd 免费API
        api_url = f"https://is.gd/create.php?format=json&url={urllib.parse.quote(url, safe='')}"
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("shorturl"):
            bot.reply_to(m, f"🔗 短链接：{data['shorturl']}\n📎 原链接：{url}")
        elif data.get("errormessage"):
            bot.reply_to(m, f"❌ 缩短失败：{data['errormessage']}")
        else:
            bot.reply_to(m, "❌ 缩短失败，请稍后再试")

    except Exception as e:
        logger.error(f"URL缩短异常: {e}")
        bot.reply_to(m, "❌ 缩短失败，请稍后再试")
