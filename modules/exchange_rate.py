# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/exchange_rate.py  ·  汇率查询模块                              ║
║                                                                        ║
║  功能：                                                                ║
║    handle_exchange_rate - 查询实时汇率                                  ║
║                                                                        ║
║  数据源：免费汇率API (https://open.er-api.com/v6/latest/USD)           ║
║  支持格式："汇率 USD/CNY"、"美元汇率"、"人民币汇率"                     ║
║  无需API Key（免费API），有Key时使用付费API                             ║
║  被调用：main.py 指令分发                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("exchange_rate")

_CST = timezone(timedelta(hours=8))

# 货币名称映射（中文名 -> 货币代码）
CURRENCY_NAMES = {
    "美元": "USD",
    "人民币": "CNY",
    "欧元": "EUR",
    "日元": "JPY",
    "英镑": "GBP",
    "韩元": "KRW",
    "港币": "HKD",
    "台币": "TWD",
    "泰铢": "THB",
    "新加坡元": "SGD",
    "澳元": "AUD",
    "加元": "CAD",
    "瑞士法郎": "CHF",
    "新西兰元": "NZD",
    "卢布": "RUB",
    "印度卢比": "INR",
}

# 货币代码 -> 中文名（反向映射，用于显示）
CURRENCY_DISPLAY = {v: k for k, v in CURRENCY_NAMES.items()}


def _parse_currency_query(query: str) -> tuple:
    """解析汇率查询字符串，返回 (base_currency, target_currency)

    支持格式：
        "USD/CNY" -> ("USD", "CNY")
        "美元汇率" -> ("USD", "CNY")
        "人民币汇率" -> ("CNY", "USD")
        "日元" -> ("JPY", "CNY")

    Args:
        query: 查询字符串

    Returns:
        (base_currency_code, target_currency_code)
    """
    base = "USD"
    target = "CNY"

    query = query.strip()

    # 尝试解析 "USD/CNY" 格式
    if "/" in query:
        parts = query.upper().replace("汇率", "").replace(" ", "").split("/")
        if len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3:
            return parts[0], parts[1]

    # 中文货币名解析
    found_codes = []
    for cn_name, code in CURRENCY_NAMES.items():
        if cn_name in query:
            found_codes.append(code)

    if len(found_codes) == 2:
        # 找到两个货币，第一个为base，第二个为target
        return found_codes[0], found_codes[1]
    elif len(found_codes) == 1:
        # 只找到一个货币，另一个默认为CNY
        found = found_codes[0]
        if found == "CNY":
            return "CNY", "USD"
        else:
            return found, "CNY"

    # 尝试直接匹配3字母货币代码
    import re
    codes = re.findall(r'\b([A-Z]{3})\b', query.upper())
    if len(codes) >= 2:
        return codes[0], codes[1]
    elif len(codes) == 1:
        found = codes[0]
        if found == "CNY":
            return "CNY", "USD"
        return found, "CNY"

    return base, target


def handle_exchange_rate(bot, m, config, db, query: str):
    """查询实时汇率

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
        query: 查询字符串（如 "USD/CNY"、"美元汇率"）
    """
    if not query.strip():
        # 默认查询美元兑人民币
        query = "美元"

    base, target = _parse_currency_query(query)

    try:
        import requests

        # 使用免费汇率API（无需Key）
        url = f"https://open.er-api.com/v6/latest/{base}"
        resp = requests.get(url, timeout=10)
        data = resp.json()

        if data.get("result") != "success":
            bot.reply_to(m, "❌ 汇率查询失败，API返回异常")
            return

        rates = data.get("rates", {})
        if target not in rates:
            bot.reply_to(m, f"❌ 不支持的货币代码：{target}")
            return

        rate = rates[target]
        update_time = data.get("time_last_update_utc", "未知")

        # 货币显示名
        base_display = CURRENCY_DISPLAY.get(base, base)
        target_display = CURRENCY_DISPLAY.get(target, target)

        text = f"💱 实时汇率\n"
        text += f"━━━━━━━━━━━━━\n"
        text += f"1 {base}（{base_display}）= {rate} {target}（{target_display}）\n"
        text += f"🕐 更新时间：{update_time}"

        # 如果base不是CNY，额外显示反向汇率
        if base != "CNY" and "CNY" in rates:
            cny_rate = rates["CNY"]
            if cny_rate > 0:
                text += f"\n💡 1 CNY ≈ {1/cny_rate:.4f} {base}"

        # 如果target不是CNY且base是CNY的某种形式，补充常用汇率
        if base == "USD" and target == "CNY":
            # 补充几个常用货币兑CNY
            extras = []
            for code in ["EUR", "JPY", "GBP", "HKD", "KRW"]:
                if code in rates:
                    cny_in_base = rates.get("CNY", 1)
                    if cny_in_base > 0:
                        # 1 unit of code = (rate/CNY_rate) CNY
                        code_to_cny = rates[code] / cny_in_base if code != "CNY" else 1
                        # 实际上 rates[code] 是 1 USD = rates[code] CODE
                        # 1 CODE = 1/rates[code] USD = (1/rates[code]) * cny_in_base CNY
                        if rates[code] > 0:
                            one_code_to_cny = cny_in_base / rates[code]
                            cn_name = CURRENCY_DISPLAY.get(code, code)
                            extras.append(f"1 {code}（{cn_name}）≈ {one_code_to_cny:.4f} CNY")
            if extras:
                text += f"\n\n📌 常用汇率参考：\n"
                for ext in extras:
                    text += f"  {ext}\n"

        bot.reply_to(m, text)

    except requests.Timeout:
        logger.warning(f"汇率查询超时: query={query}")
        bot.reply_to(m, "❌ 汇率查询超时，请稍后再试")
    except requests.RequestException as e:
        logger.error(f"汇率查询网络异常: {e}")
        bot.reply_to(m, "❌ 汇率查询网络异常，请稍后再试")
    except Exception as e:
        logger.error(f"汇率查询异常: {e}")
        bot.reply_to(m, "❌ 汇率查询失败，请稍后再试")
