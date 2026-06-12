"""
Telegraph贴图 - 创建Telegraph页面

命令：
  /telegraph 标题 → handle_telegraph
"""
import json
import urllib.request
from core.logging_util import get_logger

logger = get_logger("telegraph")


def handle_telegraph(bot, m, config, db):
    """创建Telegraph页面"""
    text = (m.text or "").strip()
    parts = text.split(None, 1)

    # 获取标题
    title = "Telegraph"
    if len(parts) >= 2 and parts[1].strip():
        title = parts[1].strip()[:256]

    # 获取内容：优先回复消息，否则使用命令后的文本
    content = ""
    if m.reply_to_message:
        content = m.reply_to_message.text or m.reply_to_message.caption or ""
    elif len(parts) >= 2:
        content = parts[1].strip()

    if not content:
        bot.reply_to(m, "❌ 用法：回复消息 + /telegraph 标题\n或 /telegraph 标题 内容")
        return

    try:
        # 创建Telegraph页面
        # 先创建账户（匿名）
        create_account_url = "https://telegra.ph/createAccount?short_name=MoryBot&author_name=Mory&author_url="
        req = urllib.request.Request(create_account_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            account_data = json.loads(resp.read().decode("utf-8"))

        if not account_data.get("ok"):
            bot.reply_to(m, "❌ 创建Telegraph账户失败")
            return

        access_token = account_data["result"]["access_token"]

        # 构建页面内容（简单HTML）
        html_content = f"<p>{content.replace(chr(10), '</p><p>')}</p>"

        # 创建页面
        page_data = json.dumps({
            "access_token": access_token,
            "title": title,
            "author_name": "Mory Bot",
            "content": [html_content]
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://telegra.ph/createPage",
            data=page_data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_result = json.loads(resp.read().decode("utf-8"))

        if page_result.get("ok"):
            page_url = page_result["result"]["url"]
            bot.reply_to(m, f"📄 Telegraph页面已创建\n🔗 {page_url}")
            logger.info(f"Telegraph创建: uid={m.from_user.id} url={page_url}")
        else:
            bot.reply_to(m, "❌ 创建页面失败")

    except Exception as e:
        logger.error(f"Telegraph异常: {e}")
        bot.reply_to(m, "❌ 创建失败，请稍后再试")
