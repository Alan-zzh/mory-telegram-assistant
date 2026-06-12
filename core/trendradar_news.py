"""
TrendRadar 新闻获取模块
多源混合：主源(TrendRadar全量) + 娱乐源(微博/抖音)，确保新闻内容多样化
"""

import requests
import random
import threading
import concurrent.futures
import re
import json
from datetime import datetime
from core.logging_util import get_logger

logger = get_logger("trendradar_news")

_NEWSNOW_BASE = "https://newsnow.busiyi.world/api/s"

_ENTERTAINMENT_SOURCES = ["weibo", "douyin"]

_SOURCE_NAME_MAP = {
    "weibo": "微博",
    "douyin": "抖音",
    "bilibili": "B站",
    "zhihu": "知乎",
    "baidu": "百度",
}


def _get_shared_cache():
    """获取共享的新闻去重缓存（与 auto_tasks.py 共用）"""
    try:
        import modules.auto_tasks as at
        if hasattr(at, '_news_pushed_today'):
            return at._news_pushed_today
    except Exception:
        pass
    global _local_pushed_today
    if not hasattr(_get_shared_cache, "_local_pushed_today"):
        _get_shared_cache._local_pushed_today = set()
    return _get_shared_cache._local_pushed_today


def _clear_shared_cache_if_new_day():
    """每日凌晨自动清空共享缓存"""
    cache = _get_shared_cache()
    today = datetime.now().strftime("%Y-%m-%d")
    if not getattr(_clear_shared_cache_if_new_day, "last_day", None) == today:
        cache.clear()
        _clear_shared_cache_if_new_day.last_day = today


def _fetch_source_news(source_id: str, limit: int = 10) -> list[str]:
    """从 NewsNow 指定来源获取新闻标题列表"""
    try:
        resp = requests.get(
            _NEWSNOW_BASE,
            params={"id": source_id},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            timeout=6,
        )
        if resp.status_code != 200:
            logger.debug(f"NewsNow source={source_id} 返回 HTTP {resp.status_code}")
            return []

        data = resp.json()
        items = data.get("items") or data.get("data") or []
        source_name = _SOURCE_NAME_MAP.get(source_id, source_id)

        result = []
        for item in items:
            title = (item.get("title") or "").strip()
            if not title or len(title) < 4:
                continue
            hot_value = item.get("hot", "")
            line = f"【{source_name}】{title}"
            if hot_value:
                line += f" 🔥{hot_value}"
            result.append(line)
            if len(result) >= limit:
                break

        logger.info(f"NewsNow source={source_id} 获取 {len(result)} 条")
        return result

    except Exception as e:
        logger.debug(f"NewsNow source={source_id} 获取失败: {e}")
        return []


def _fetch_entertainment_news(limit: int = 5) -> list[str]:
    """从娱乐类源（微博+抖音）获取新闻，去重后返回"""
    all_lines = []
    seen_titles = set()

    for src in _ENTERTAINMENT_SOURCES:
        lines = _fetch_source_news(src, limit=limit)
        for line in lines:
            title_core = line.split("】", 1)[-1].split("🔥")[0].strip()
            if title_core not in seen_titles:
                seen_titles.add(title_core)
                all_lines.append(line)

    random.shuffle(all_lines)
    return all_lines[:limit]


def _is_entertainment_title(title: str) -> bool:
    """判断标题是否属于娱乐/生活类（用于从主源中识别娱乐内容）"""
    keywords = [
        "综艺", "演唱会", "电影", "电视剧", "明星", "歌手", "偶像", "出道",
        "恋情", "分手", "结婚", "离婚", "官宣", "塌房", "翻车", "热搜",
        "直播", "网红", "粉丝", "追星", "音乐节", "红毯", "颁奖", "票房",
        "游戏", "动漫", "番剧", "电竞", "主播", "剧本杀", "密室",
        "美食", "旅行", "穿搭", "健身", "减肥", "宠物", "萌宠",
    ]
    return any(kw in title for kw in keywords)


def fetch_trendradar_news(_depth: int = 0) -> str:
    """
    多源混合获取新闻：主源(TrendRadar全量) + 娱乐源(微博/抖音)
    确保每批新闻至少包含1-2条娱乐/生活类内容
    """
    # 递归深度保护：最多重试1次（2层深度），防止无限递归（Bug 4a）
    if _depth >= 2:
        logger.warning(f"递归深度超过上限({_depth})，终止递归")
        return ""
    try:
        _clear_shared_cache_if_new_day()
        cache = _get_shared_cache()

        main_lines = _fetch_main_news(cache, max_count=8)
        ent_lines = _fetch_entertainment_news(limit=5)

        ent_lines = [l for l in ent_lines if l not in cache]
        main_titles = set()
        for ml in main_lines:
            core = ml.split("】", 1)[-1].split("🔥")[0].strip()
            main_titles.add(core)
        ent_lines = [l for l in ent_lines if l.split("】", 1)[-1].split("🔥")[0].strip() not in main_titles]

        mixed = _mix_news(main_lines, ent_lines, target=10)

        if not mixed:
            if cache:
                logger.info("今日新闻已全部推送过，清空缓存重新获取")
                cache.clear()
                return fetch_trendradar_news(_depth + 1)
            return ""

        logger.info(f"多源混合新闻: 主源{len(main_lines)}条 + 娱乐{len([l for l in mixed if _is_entertainment_title(l)])}条, 共{len(mixed)}条")
        return "\n".join(mixed)

    except Exception as e:
        logger.warning(f"多源混合新闻获取失败: {e}")
        return _fallback_single_source(cache)


def _fetch_main_news(cache: set, max_count: int = 8) -> list[str]:
    """从 TrendRadar 主源获取新闻（不带 id 参数，返回全量聚合）"""
    try:
        resp = requests.get(
            _NEWSNOW_BASE,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
            },
            timeout=8,
        )
        if resp.status_code != 200:
            logger.warning(f"TrendRadar 主源返回 HTTP {resp.status_code}")
            return []

        data = resp.json()
        if not data or "data" not in data:
            return []

        news_items = data["data"][:20]
        formatted = []
        for item in news_items:
            title = item.get("title", "").strip()
            source = item.get("source", "").strip()
            hot_value = item.get("hot", "")

            if not title or len(title) < 5:
                continue
            if title in cache:
                continue

            line = f"【{source}】{title}"
            if hot_value:
                line += f" 🔥{hot_value}"
            formatted.append(line)

            if len(formatted) >= max_count:
                break

        return formatted

    except Exception as e:
        logger.warning(f"TrendRadar 主源获取失败: {e}")
        return []


def _mix_news(main_lines: list[str], ent_lines: list[str], target: int = 10) -> list[str]:
    """
    混合主源和娱乐源新闻，确保娱乐内容均匀分布
    策略：主源最多7条 + 娱乐至少2条，娱乐内容穿插在主源之间
    """
    if not main_lines and not ent_lines:
        return []

    max_main = target - 2
    main_selected = main_lines[:max_main]

    ent_count = min(len(ent_lines), 3)
    ent_selected = ent_lines[:ent_count]

    remaining = target - len(main_selected) - len(ent_selected)
    if remaining > 0 and len(main_lines) > max_main:
        main_selected.extend(main_lines[max_main:max_main + remaining])

    if not ent_selected:
        return main_selected[:target]

    mixed = []
    main_idx = 0
    ent_idx = 0
    total_slots = len(main_selected) + len(ent_selected)
    ent_interval = max(2, total_slots // (ent_count + 1))
    next_ent_pos = ent_interval

    for i in range(total_slots):
        if ent_idx < len(ent_selected) and i >= next_ent_pos and len(mixed) < target:
            mixed.append(ent_selected[ent_idx])
            ent_idx += 1
            next_ent_pos += ent_interval
        elif main_idx < len(main_selected) and len(mixed) < target:
            mixed.append(main_selected[main_idx])
            main_idx += 1

    while main_idx < len(main_selected) and len(mixed) < target:
        mixed.append(main_selected[main_idx])
        main_idx += 1
    while ent_idx < len(ent_selected) and len(mixed) < target:
        mixed.append(ent_selected[ent_idx])
        ent_idx += 1

    return mixed[:target]


def _fallback_single_source(cache: set) -> str:
    """降级：只用主源获取（与旧版逻辑一致）"""
    try:
        main_lines = _fetch_main_news(cache, max_count=10)
        if main_lines:
            return "\n".join(main_lines)
        return ""
    except Exception:
        return ""


# ── 多源并行新闻获取（从 ai_engine.py 迁移）──────────────────────

_news_session_local = threading.local()


def _get_news_session():
    """线程级Session复用，避免每次fetch创建7个TCP连接"""
    if not hasattr(_news_session_local, 'session'):
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        _news_session_local.session = session
    return _news_session_local.session


def fetch_real_news() -> str:
    """
    从网络实时抓取今日热点新闻（多源并行容错）。
    数据源：百度热搜 > 微博热搜API > 今日头条 > 知乎热榜 > 抖音热点 > 36氪 > 澎湃新闻
    七源同时请求，最快返回的优先使用，总超时15秒。
    """

    def _dedup(raw_list):
        seen, unique = set(), []
        for t in raw_list:
            t = t.strip()
            if t and t not in seen and len(t) > 2 and not t.startswith('http') and not t.isdigit():
                seen.add(t)
                unique.append(t)
        return unique

    def _parse_baidu(text):
        titles = re.findall(r'"word":"([^"]+)"', text)
        if not titles:
            titles = re.findall(r'<a[^>]*title="([^"]+)"[^>]*>', text)
        return titles

    def _parse_weibo(text):
        try:
            items = json.loads(text).get("data", {}).get("realtime", [])
            return [item.get("word", "") for item in items[:15]]
        except Exception:
            return []

    def _parse_toutiao(text):
        return re.findall(r'<td class="al"><a[^>]*>([^<]+)</a>', text)

    def _parse_zhihu(text):
        titles = re.findall(r'<meta itemprop="name" content="([^"]+)"', text)
        if not titles:
            titles = re.findall(r'"title":"([^"]+)"', text)
        return titles

    def _parse_douyin(text):
        return re.findall(r'<td class="al"><a[^>]*>([^<]+)</a>', text)

    def _parse_36kr(text):
        titles = re.findall(r'"title":"([^"]+)"', text)
        if not titles:
            titles = re.findall(r'<a[^>]*class="item-title"[^>]*>([^<]+)</a>', text)
        return titles

    def _parse_thepaper(text):
        titles = re.findall(r'<h2 class="news_title">[^<]*<a[^>]*>([^<]+)</a>', text)
        if not titles:
            titles = re.findall(r'"title":"([^"]+)"', text)
        return titles

    NEWS_SOURCES = [
        {"name": "百度热搜", "url": "https://top.baidu.com/board?tab=realtime", "timeout": 10, "min_len": 500, "parser": _parse_baidu},
        {"name": "微博热搜", "url": "https://weibo.com/ajax/side/hotSearch", "timeout": 8, "min_len": 0, "parser": _parse_weibo},
        {"name": "今日头条", "url": "https://tophub.today/n/KqndgxeLl9", "timeout": 8, "min_len": 1000, "parser": _parse_toutiao},
        {"name": "知乎热榜", "url": "https://www.zhihu.com/hot", "timeout": 8, "min_len": 500, "parser": _parse_zhihu},
        {"name": "抖音热点", "url": "https://tophub.today/n/DpQvNABoNE", "timeout": 8, "min_len": 500, "parser": _parse_douyin},
        {"name": "36氪快讯", "url": "https://36kr.com/newsflashes", "timeout": 8, "min_len": 500, "parser": _parse_36kr},
        {"name": "澎湃新闻", "url": "https://www.thepaper.cn/", "timeout": 8, "min_len": 500, "parser": _parse_thepaper},
    ]

    def _fetch_news_source(src):
        try:
            resp = _get_news_session().get(src["url"], timeout=src["timeout"])
            if resp.status_code != 200:
                return None
            if src["min_len"] and len(resp.text) < src["min_len"]:
                return None
            titles = src["parser"](resp.text)
            unique = _dedup(titles)
            if unique:
                logger.info(f"📰 {src['name']}成功：{min(len(unique), 12)}条")
                return "\n".join(f"{i}. {t}" for i, t in enumerate(unique[:12], 1))
        except Exception as e:
            logger.warning(f"📰 {src['name']}失败：{e}")
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        futures = {
            executor.submit(_fetch_news_source, src): src["name"]
            for src in NEWS_SOURCES
        }
        for f in concurrent.futures.as_completed(futures, timeout=15):
            result = f.result()
            if result:
                return result

    logger.error("📰 所有7个新闻源均失败")
    return ""
