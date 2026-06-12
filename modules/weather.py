# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  modules/weather.py  ·  天气查询模块                                    ║
║                                                                        ║
║  功能：                                                                ║
║    handle_weather_query - 查询城市天气                                  ║
║                                                                        ║
║  数据源：和风天气免费API (https://dev.qweather.com/)                    ║
║  API Key：从 config["WEATHER_API_KEY"] 读取                            ║
║  无Key时优雅降级：提示管理员配置                                        ║
║  被调用：main.py 指令分发                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from datetime import datetime, timedelta, timezone
from core.logging_util import get_logger

logger = get_logger("weather")

_CST = timezone(timedelta(hours=8))


def handle_weather_query(bot, m, config, db, city: str):
    """查询城市天气

    Args:
        bot: TeleBot实例
        m: Message对象
        config: 配置字典
        db: DB类实例
        city: 城市名（支持中文）
    """
    api_key = config.get("WEATHER_API_KEY", "")
    if not api_key:
        bot.reply_to(m, "❌ 天气功能未配置API Key，请联系管理员在config中设置 WEATHER_API_KEY")
        return

    if not city.strip():
        bot.reply_to(m, "❌ 请输入城市名，例如：天气 北京")
        return

    city = city.strip()

    try:
        import requests

        # 和风天气API - 先查询城市ID
        lookup_url = f"https://geoapi.qweather.com/v2/city/lookup?location={city}&key={api_key}"
        resp = requests.get(lookup_url, timeout=5)
        data = resp.json()

        if data.get("code") != "200" or not data.get("location"):
            bot.reply_to(m, f"❌ 未找到城市「{city}」")
            return

        loc = data["location"][0]
        loc_id = loc["id"]
        loc_name = loc["name"]

        # 查询实时天气
        weather_url = f"https://devapi.qweather.com/v7/weather/now?location={loc_id}&key={api_key}"
        resp = requests.get(weather_url, timeout=5)
        wdata = resp.json()

        if wdata.get("code") != "200":
            bot.reply_to(m, "❌ 天气查询失败，API返回异常")
            return

        now = wdata["now"]
        text = f"🌤 {loc_name}天气\n"
        text += f"━━━━━━━━━━━━━\n"
        text += f"🌡 温度：{now['temp']}°C\n"
        text += f"🤗 体感：{now['feelsLike']}°C\n"
        text += f"☁️ 天气：{now['text']}\n"
        text += f"💧 湿度：{now['humidity']}%\n"
        text += f"🌬 风向：{now['windDir']} {now['windScale']}级\n"

        # 穿衣建议
        try:
            temp = int(now['temp'])
        except (ValueError, TypeError):
            temp = 20  # 默认值

        if temp >= 30:
            text += "\n👗 建议穿短袖、短裤等清凉衣物"
        elif temp >= 20:
            text += "\n👕 建议穿薄长袖、薄外套"
        elif temp >= 10:
            text += "\n🧥 建议穿厚外套、毛衣"
        else:
            text += "\n🧣 建议穿羽绒服、棉衣，注意保暖"

        bot.reply_to(m, text)

    except requests.Timeout:
        logger.warning(f"天气查询超时: city={city}")
        bot.reply_to(m, "❌ 天气查询超时，请稍后再试")
    except requests.RequestException as e:
        logger.error(f"天气查询网络异常: {e}")
        bot.reply_to(m, "❌ 天气查询网络异常，请稍后再试")
    except Exception as e:
        logger.error(f"天气查询异常: {e}")
        bot.reply_to(m, "❌ 天气查询失败，请稍后再试")
