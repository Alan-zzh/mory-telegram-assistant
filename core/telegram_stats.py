"""
core/telegram_stats.py · Telegram getChatStatistics API 封装

Bot API 7.0+ 支持 getChatStatistics / getMessageStatistics
前提：Bot 必须是频道/群组的管理员
提供准确的成员增长、消息数、浏览量、互动数据
"""

import time
import requests
from datetime import datetime, timedelta
from core.logging_util import get_logger

logger = get_logger("telegram_stats")

try:
    import pytz
    _CST = pytz.timezone('Asia/Shanghai')
except ImportError:
    from datetime import timezone as _timezone, timedelta
    _CST = _timezone(timedelta(hours=8))  # 回退到固定+8时区

_stats_cache = {}
_CACHE_TTL = 3600


def _call_api(token: str, method: str, params: dict, timeout: int = 10) -> dict | None:
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        resp = requests.post(url, json=params, timeout=timeout)
        data = resp.json()
        if data.get("ok"):
            return data["result"]
        desc = data.get("description", "")
        logger.debug(f"Telegram API {method} 失败: {desc}")
        return None
    except requests.Timeout:
        logger.warning(f"Telegram API {method} 超时")
        return None
    except Exception as e:
        logger.error(f"Telegram API {method} 异常: {e}")
        return None


def get_chat_statistics(token: str, chat_id: int, is_dark: bool = False) -> dict | None:
    cache_key = f"stats_{chat_id}"
    cached = _stats_cache.get(cache_key)
    if cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    result = _call_api(token, "getChatStatistics", {
        "chat_id": chat_id,
        "is_dark": is_dark
    })

    if result:
        _stats_cache[cache_key] = {"data": result, "ts": time.time()}
    return result


def get_message_statistics(token: str, chat_id: int, message_id: int, is_dark: bool = False) -> dict | None:
    return _call_api(token, "getMessageStatistics", {
        "chat_id": chat_id,
        "message_id": message_id,
        "is_dark": is_dark
    })


def _normalize_day(day_str: str) -> str:
    """统一日期格式为 YYYY-MM-DD，兼容带时间后缀的格式"""
    if not isinstance(day_str, str):
        return ""
    # 处理 "2026-05-20T00:00:00" 或 "2026-05-20" 格式
    return day_str[:10] if len(day_str) >= 10 else day_str


def extract_daily_member_stats(stats: dict) -> dict:
    result = {
        "current_count": 0,
        "growth_today": 0,
        "enabled_notifications_pct": 0,
    }
    try:
        mc = stats.get("member_count", {})
        result["current_count"] = mc.get("current", 0) if isinstance(mc, dict) else 0

        growth = stats.get("growth", [])
        if isinstance(growth, list) and growth:
            today_str = datetime.now(_CST).strftime("%Y-%m-%d")
            for item in growth:
                if isinstance(item, dict):
                    day_str = _normalize_day(item.get("day", ""))
                    if day_str == today_str:
                        result["growth_today"] = item.get("growth", 0)
                        break

        en = stats.get("enabled_notifications", {})
        if isinstance(en, dict):
            total = en.get("total", 0)
            enabled = en.get("enabled", 0)
            if total > 0:
                result["enabled_notifications_pct"] = round(enabled / total * 100)
    except Exception as e:
        logger.error(f"解析成员统计失败: {e}")
    return result


def extract_daily_message_stats(stats: dict) -> dict:
    result = {
        "messages_today": 0,
        "views_today": 0,
        "forwards_today": 0,
        "interactions_today": 0,
        "yesterday_messages": 0,
        "yesterday_views": 0,
    }
    try:
        today_str = datetime.now(_CST).strftime("%Y-%m-%d")
        yesterday_str = (datetime.now(_CST) - timedelta(days=1)).strftime("%Y-%m-%d")

        for field, key in [
            ("messages", "messages_today"),
            ("views", "views_today"),
            ("forwards", "forwards_today"),
            ("interactions", "interactions_today"),
        ]:
            data = stats.get(field, [])
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        day_str = _normalize_day(item.get("day", ""))
                        if day_str == today_str:
                            result[key] = item.get("value", 0)
                            break

        for field, key in [
            ("messages", "yesterday_messages"),
            ("views", "yesterday_views"),
        ]:
            data = stats.get(field, [])
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        day_str = _normalize_day(item.get("day", ""))
                        if day_str == yesterday_str:
                            result[key] = item.get("value", 0)
                            break
    except Exception as e:
        logger.error(f"解析消息统计失败: {e}")
    return result


def get_group_daily_stats(token: str, chat_id: int) -> dict | None:
    stats = get_chat_statistics(token, chat_id)
    if not stats:
        return None
    member_info = extract_daily_member_stats(stats)
    message_info = extract_daily_message_stats(stats)
    return {**member_info, **message_info}


def get_channel_daily_stats(token: str, chat_id: int) -> dict | None:
    stats = get_chat_statistics(token, chat_id)
    if not stats:
        return None
    member_info = extract_daily_member_stats(stats)
    message_info = extract_daily_message_stats(stats)
    return {**member_info, **message_info}


def test_api_availability(token: str, chat_ids: list) -> dict:
    results = {}
    for cid in chat_ids:
        result = _call_api(token, "getChatStatistics", {"chat_id": cid}, timeout=15)
        if result:
            results[cid] = {"available": True, "has_data": bool(result)}
            logger.info(f"✅ getChatStatistics 可用: chat_id={cid}")
        else:
            results[cid] = {"available": False, "has_data": False}
            logger.info(f"❌ getChatStatistics 不可用: chat_id={cid}")
    return results
