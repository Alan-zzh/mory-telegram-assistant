"""
花式字体 - 将文本转为花式Unicode字体

命令：
  /font 样式 文本 → handle_fancy_text
  /fonts → handle_font_list

样式：bubble, square, bold, italic, mono, upside, small, caps
"""
from core.logging_util import get_logger

logger = get_logger("fancy_text")

# Unicode字体映射表
FONT_MAPS = {
    "bubble": {
        "name": "气泡字",
        "lower": "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ",
        "upper": "⒜⒝⒞⒟⒠⒡⒢⒣⒤⒥⒦⒧⒨⒩⒪⒫⒬⒭⒮⒯⒰⒱⒲⒳⒴⒵",
    },
    "square": {
        "name": "方块字",
        "lower": "🄰🄱🄲🄳🄴🄵🄶🄷🄸🄹🄺🄻🄼🄽🄾🄿🅀🅁🅂🅃🅄🅅🅆🅇🅈🅉",
        "upper": "🄰🄱🄲🄳🄴🄵🄶🄷🄸🄹🄺🄻🄼🄽🄾🄿🅀🅁🅂🅃🅄🅅🅆🅇🅈🅉",
    },
    "bold": {
        "name": "粗体",
        "chars": "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙",
    },
    "italic": {
        "name": "斜体",
        "chars": "𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧𝐴𝐵𝐶𝐷𝐸𝐹𝐺𝐻𝐼𝐽𝐾𝐿𝑀𝑁𝑂𝑃𝑄𝑅𝑆𝑇𝑈𝑉𝑊𝑋𝑌𝑍",
    },
    "mono": {
        "name": "等宽体",
        "chars": "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉",
    },
    "small": {
        "name": "上标小字",
        "chars": "ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖqʳˢᵗᵘᵛʷˣʸᶻ",
    },
    "upside": {
        "name": "倒转字",
        "chars": "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz",
    },
}


def _convert_font(text, style):
    """将文本转换为指定花式字体"""
    if style in ("bubble",):
        lower_map = FONT_MAPS[style]["lower"]
        upper_map = FONT_MAPS[style]["upper"]
        result = ""
        for c in text:
            if 'a' <= c <= 'z':
                result += lower_map[ord(c) - ord('a')]
            elif 'A' <= c <= 'Z':
                result += upper_map[ord(c) - ord('A')]
            else:
                result += c
        return result

    elif style in ("bold", "italic", "mono"):
        chars = FONT_MAPS[style]["chars"]
        result = ""
        for c in text:
            if 'a' <= c <= 'z' and len(chars) >= 26:
                result += chars[ord(c) - ord('a')]
            elif 'A' <= c <= 'Z' and len(chars) >= 52:
                result += chars[26 + ord(c) - ord('A')]
            else:
                result += c
        return result

    elif style == "small":
        chars = FONT_MAPS[style]["chars"]
        result = ""
        for c in text:
            if 'a' <= c <= 'z' and len(chars) >= 26:
                result += chars[ord(c) - ord('a')]
            elif 'A' <= c <= 'Z':
                # 小字不支持大写，转小写
                result += chars[ord(c.lower()) - ord('a')] if len(chars) >= 26 else c
            else:
                result += c
        return result

    elif style == "upside":
        chars = FONT_MAPS[style]["chars"]
        result = ""
        for c in text[::-1]:  # 反转
            if 'a' <= c <= 'z':
                result += chars[ord(c) - ord('a')]
            else:
                result += c
        return result

    elif style == "square":
        lower_map = FONT_MAPS[style]["lower"]
        result = ""
        for c in text:
            if c.isalpha():
                idx = ord(c.lower()) - ord('a')
                if idx < len(lower_map):
                    result += lower_map[idx]
                else:
                    result += c
            else:
                result += c
        return result

    return text


def handle_fancy_text(bot, m, config, db):
    """处理花式字体命令"""
    text = (m.text or "").strip()
    parts = text.split(None, 2)

    if len(parts) < 3:
        bot.reply_to(m, "❌ 用法：/font 样式 文本\n💡 发送 /fonts 查看可用样式")
        return

    style = parts[1].lower()
    content = parts[2]

    if style not in FONT_MAPS:
        bot.reply_to(m, f"❌ 未知样式：{style}\n💡 可用样式：{', '.join(FONT_MAPS.keys())}")
        return

    result = _convert_font(content, style)
    style_name = FONT_MAPS[style]["name"]
    bot.reply_to(m, f"✨ {style_name}：\n{result}")


def handle_font_list(bot, m, config, db):
    """查看可用字体样式"""
    lines = ["🎨 可用花式字体样式：\n"]
    for key, info in FONT_MAPS.items():
        sample = _convert_font("Hello", key)
        lines.append(f"  • {key}（{info['name']}）：{sample}")

    lines.append("\n💡 用法：/font 样式 文本\n示例：/font bold Hello World")
    bot.reply_to(m, "\n".join(lines))
