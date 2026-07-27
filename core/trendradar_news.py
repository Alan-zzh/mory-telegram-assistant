"""
TrendRadar 新闻获取模块
多源混合：主源(TrendRadar全量) + 娱乐源(微博/抖音)，确保新闻内容多样化
"""

import random
import threading
import concurrent.futures
import re
import json
import time
from datetime import datetime, timezone, timedelta
import requests
from core.logging_util import get_logger
from core.http_client import get_http_client, HTTPRequestError

logger = get_logger("trendradar_news")

# 【v5.31.2 修复】VPS 运行在 UTC，时段/日期相关逻辑必须用 CST（UTC+8）
_CST = timezone(timedelta(hours=8))

_NEWSNOW_BASE = "https://newsnow.busiyi.world/api/s"

_ENTERTAINMENT_SOURCES = ["weibo", "douyin"]

_SOURCE_NAME_MAP = {
    "weibo": "微博",
    "douyin": "抖音",
    "bilibili": "B站",
    "zhihu": "知乎",
    "baidu": "百度",
}

_CATEGORY_ORDER = ["社会", "综合", "国际", "生活", "体育", "文娱", "财经", "科技"]
_CLASSIFICATION_ORDER = ["社会", "体育", "生活", "国际", "文娱", "财经", "科技"]
_SOURCE_CATEGORY = {
    "百度热搜": "综合",
    "微博热搜": "综合",
    "今日头条": "社会",
    "知乎热榜": "综合",
    "抖音热点": "文娱",
    "36氪快讯": "科技",
    "澎湃新闻": "社会",
    "NewsNow微博": "综合",
    "NewsNow抖音": "文娱",
    "NewsNow知乎": "综合",
    "NewsNowB站": "文娱",
    "NewsNow百度": "综合",
    "NewsNow头条": "社会",
    "NewsNow澎湃": "社会",
    "NewsNow早报": "国际",
}
_SOURCE_PRIORITY = {
    "NewsNow澎湃": 110,
    "NewsNow头条": 108,
    "今日头条": 107,
    "百度热搜": 105,
    "NewsNow百度": 104,
    "NewsNow早报": 103,
    "NewsNow微博": 90,
    "NewsNow知乎": 88,
    "抖音热点": 72,
    "NewsNow抖音": 70,
    "NewsNowB站": 65,
    "36氪快讯": 60,
}

# 2026-07-24 VPS 实测：微博/知乎/澎湃直连稳定返回 403，禁止继续请求。
# 同名 NewsNow 接口均返回 200，并新增头条、澎湃、早报作为综合头条主干。
_ACTIVE_NEWS_SOURCE_SPECS = [
    {"name": "百度热搜", "url": "https://top.baidu.com/board?tab=realtime", "timeout": 10, "min_len": 500, "parser": "baidu"},
    {"name": "今日头条", "url": "https://tophub.today/n/KqndgxeLl9", "timeout": 8, "min_len": 1000, "parser": "toutiao"},
    {"name": "抖音热点", "url": "https://tophub.today/n/DpQvNABoNE", "timeout": 8, "min_len": 500, "parser": "douyin"},
    {"name": "36氪快讯", "url": "https://36kr.com/newsflashes", "timeout": 8, "min_len": 500, "parser": "36kr"},
    {"name": "NewsNow头条", "url": f"{_NEWSNOW_BASE}?id=toutiao", "timeout": 6, "min_len": 0, "parser": "newsnow"},
    {"name": "NewsNow澎湃", "url": f"{_NEWSNOW_BASE}?id=thepaper", "timeout": 6, "min_len": 0, "parser": "newsnow"},
    {"name": "NewsNow早报", "url": f"{_NEWSNOW_BASE}?id=zaobao", "timeout": 6, "min_len": 0, "parser": "newsnow"},
    {"name": "NewsNow微博", "url": f"{_NEWSNOW_BASE}?id=weibo", "timeout": 6, "min_len": 0, "parser": "newsnow"},
    {"name": "NewsNow知乎", "url": f"{_NEWSNOW_BASE}?id=zhihu", "timeout": 6, "min_len": 0, "parser": "newsnow"},
]
_CATEGORY_KEYWORDS = {
    "社会": (
        "警方", "法院", "检察院", "救援", "事故", "灾情", "防汛", "台风",
        "诈骗", "犯罪", "被判", "新规", "政策", "公共服务", "民生",
    ),
    "科技": (
        "AI", "人工智能", "大模型", "机器人", "芯片", "算力", "科技", "手机",
        "苹果", "华为", "小米", "特斯拉", "OpenAI", "互联网", "算法",
    ),
    "财经": (
        "A股", "港股", "美股", "基金", "债券", "降息", "央行", "人民币",
        "经济", "楼市", "房价", "消费", "财报", "关税", "油价", "黄金",
        "股票", "股价", "退市", "融资", "回购", "上市", "营收", "利润",
        "金条", "外贸", "外资",
    ),
    "文娱": (
        "电影", "电视剧", "综艺", "演唱会", "歌手", "演员", "明星", "票房",
        "直播", "网红", "游戏", "动漫", "电竞", "抖音", "微博",
    ),
    "生活": (
        "高考", "中考", "教育", "医院", "医生", "健康", "天气", "出行",
        "旅游", "食品", "餐饮", "育儿", "学校", "地铁", "航班",
    ),
    "国际": (
        "美国", "日本", "韩国", "欧洲", "俄罗斯", "乌克兰", "以色列",
        "伊朗", "联合国", "特朗普", "拜登", "国际", "外交",
    ),
    "体育": (
        "世界杯", "欧冠", "中超", "NBA", "CBA", "网球", "足球", "篮球",
        "比赛", "联赛", "夺冠", "奥运", "运动员", "女排", "男足", "男篮",
    ),
}


def _normalize_news_title(title: str) -> str:
    """去掉来源、序号和热度，得到稳定的标题去重键。"""
    text = (title or "").strip()
    text = re.sub(r"^\d+[\.\、]\s*", "", text)
    if text.startswith("【") and "】" in text:
        text = text.split("】", 1)[-1].strip()
    if " 🔥" in text:
        text = text.split(" 🔥", 1)[0].strip()
    return text


def _classify_news_title(title: str, source_name: str = "") -> str:
    """按标题关键词分类，避免新闻卡片长期被科技/AI占满。"""
    text = _normalize_news_title(title)
    for category in _CLASSIFICATION_ORDER:
        if any(keyword in text for keyword in _CATEGORY_KEYWORDS.get(category, ())):
            return category
    return _SOURCE_CATEGORY.get(source_name, "综合")


def get_active_news_sources() -> list[dict]:
    """返回当前生产新闻源清单；供诊断和回归测试复核，不暴露给最终用户。"""
    return [dict(item) for item in _ACTIVE_NEWS_SOURCE_SPECS]


def _group_news_sources(sources: list[dict]) -> list[tuple[str, list[dict], int]]:
    """按域名隔离并发：直连可4路，NewsNow同域最多2路。"""
    direct = [item for item in sources if not item["url"].startswith(_NEWSNOW_BASE)]
    newsnow = [item for item in sources if item["url"].startswith(_NEWSNOW_BASE)]
    groups = []
    if direct:
        groups.append(("direct", direct, min(4, len(direct))))
    if newsnow:
        groups.append(("newsnow", newsnow, min(2, len(newsnow))))
    return groups


def _select_balanced_news(items: list[dict], limit: int = 12) -> list[str]:
    """综合头条优先：科技最多1条、财经最多2条、单源常态最多2条。"""
    seen_titles = set()
    buckets: dict[str, list[dict]] = {category: [] for category in _CATEGORY_ORDER}
    for item in items:
        title = _normalize_news_title(item.get("title", ""))
        if not title or len(title) < 4 or title in seen_titles:
            continue
        seen_titles.add(title)
        category = item.get("category") or _classify_news_title(title, item.get("source", ""))
        if category not in buckets:
            category = "综合"
        buckets[category].append({
            "title": title,
            "source": item.get("source", "未知来源"),
            "category": category,
            "rank": max(1, int(item.get("rank", 999) or 999)),
            "priority": int(
                item.get("priority", _SOURCE_PRIORITY.get(item.get("source", ""), 50))
            ),
        })

    for bucket in buckets.values():
        bucket.sort(key=lambda candidate: (
            -candidate["priority"],
            candidate["rank"],
            candidate["title"],
        ))

    selected = []
    source_count: dict[str, int] = {}
    category_cap = {
        "科技": 1,
        "文娱": 2,
        "社会": 3,
        "财经": 2,
        "生活": 3,
        "国际": 2,
        "体育": 2,
        "综合": 3,
    }

    def _pick_round(source_cap: int) -> bool:
        changed = False
        for category in _CATEGORY_ORDER:
            if len(selected) >= limit:
                break
            if not buckets[category]:
                continue
            current_category_count = sum(1 for item in selected if item["category"] == category)
            if current_category_count >= category_cap.get(category, 3):
                continue
            if category in {"科技", "财经"}:
                vertical_count = sum(
                    1 for item in selected
                    if item["category"] in {"科技", "财经"}
                )
                if vertical_count >= 3:
                    continue
            pick = None
            for index, candidate in enumerate(buckets[category]):
                if source_count.get(candidate["source"], 0) < source_cap:
                    pick = buckets[category].pop(index)
                    break
            if pick is None:
                continue
            selected.append(pick)
            source_count[pick["source"]] = source_count.get(pick["source"], 0) + 1
            changed = True
        return changed

    while len(selected) < limit:
        changed = _pick_round(source_cap=2)
        if not changed:
            break

    # 候选源较少时把单源上限放宽到3，但不放宽科技/财经配额。
    while len(selected) < limit:
        changed = _pick_round(source_cap=3)
        if not changed:
            break

    # 上游部分失效、类目变少时逐级放宽类目/单源限制，但科技/财经硬上限不变。
    # 这样有10条真实候选就尽量发满10条，不会因“综合/社会”类目集中被截成6条。
    remaining = [
        candidate
        for category in _CATEGORY_ORDER
        for candidate in buckets[category]
    ]
    remaining.sort(key=lambda candidate: (
        -candidate["priority"],
        candidate["rank"],
        candidate["title"],
    ))
    for source_cap in (4, 5, limit):
        if len(selected) >= limit:
            break
        for candidate in list(remaining):
            if len(selected) >= limit:
                break
            if source_count.get(candidate["source"], 0) >= source_cap:
                continue
            if candidate["category"] == "科技":
                if sum(item["category"] == "科技" for item in selected) >= 1:
                    continue
            if candidate["category"] == "财经":
                if sum(item["category"] == "财经" for item in selected) >= 2:
                    continue
            if candidate["category"] in {"科技", "财经"}:
                if sum(
                    item["category"] in {"科技", "财经"}
                    for item in selected
                ) >= 3:
                    continue
            selected.append(candidate)
            source_count[candidate["source"]] = (
                source_count.get(candidate["source"], 0) + 1
            )
            remaining.remove(candidate)

    return [f"【{item['category']}·{item['source']}】{item['title']}" for item in selected[:limit]]


def _get_shared_cache():
    """获取共享的新闻去重缓存（与 auto_tasks.py 共用）"""
    try:
        import modules.auto_tasks as at
        if hasattr(at, '_news_pushed_today'):
            return at._news_pushed_today
    except Exception as e:
        logger.debug(f"操作异常: {e}")
    global _local_pushed_today
    if not hasattr(_get_shared_cache, "_local_pushed_today"):
        _get_shared_cache._local_pushed_today = set()
    return _get_shared_cache._local_pushed_today


def _clear_shared_cache_if_new_day():
    """每日凌晨自动清空共享缓存"""
    cache = _get_shared_cache()
    today = datetime.now(_CST).strftime("%Y-%m-%d")
    if not getattr(_clear_shared_cache_if_new_day, "last_day", None) == today:
        cache.clear()
        _clear_shared_cache_if_new_day.last_day = today


def _fetch_source_news(source_id: str, limit: int = 10) -> list[str]:
    """从 NewsNow 指定来源获取新闻标题列表"""
    try:
        client = get_http_client()
        data = client.get(
            _NEWSNOW_BASE,
            params={"id": source_id, "_": int(time.time())},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            timeout=6,
        )

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

    except HTTPRequestError as e:
        logger.debug(f"NewsNow source={source_id} 获取失败: {e}")
        return []
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
        client = get_http_client()
        data = client.get(
            _NEWSNOW_BASE,
            params={"_": int(time.time())},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            timeout=8,
        )

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

    except HTTPRequestError as e:
        logger.warning(f"TrendRadar 主源获取失败: {e}")
        return []
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


def fetch_real_news() -> str:
    """
    从网络实时抓取今日热点新闻（多源并行容错）。
    数据源：百度/头条直连 + NewsNow 头条、澎湃、早报及社交热点。
    不同域并行、NewsNow同域最多2路，总超时15秒；按榜单位置和来源权重挑选综合头条，
    科技最多1条、财经最多2条，避免垂直行业内容占满整张卡。
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

    def _parse_newsnow(text):
        try:
            data = json.loads(text)
            items = data.get("items") or data.get("data") or []
            return [(item.get("title") or "").strip() for item in items[:15]]
        except Exception:
            return []

    parsers = {
        "baidu": _parse_baidu,
        "toutiao": _parse_toutiao,
        "douyin": _parse_douyin,
        "36kr": _parse_36kr,
        "newsnow": _parse_newsnow,
    }
    NEWS_SOURCES = get_active_news_sources()
    for source in NEWS_SOURCES:
        source["parser"] = parsers[source["parser"]]

    def _fetch_news_source(src):
        started_at = time.monotonic()
        try:
            # 新闻源允许部分失败，直接用 requests 获取并在汇总层统一记健康结果，
            # 避免每个可降级源分别打 ERROR/WARNING 污染生产日志。
            response = requests.get(
                src["url"],
                params={"_": int(time.time())},
                timeout=src["timeout"],
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            response.raise_for_status()
            resp_text = response.text
            if src["min_len"] and len(resp_text) < src["min_len"]:
                return None
            titles = src["parser"](resp_text)
            unique = _dedup(titles)
            if unique:
                return {
                    "source": src["name"],
                    "titles": unique[:12],
                    "elapsed": time.monotonic() - started_at,
                }
        except Exception as e:
            logger.debug(f"📰 {src['name']}本轮不可用：{type(e).__name__}")
        return None

    collected = []
    failed_sources = set()
    executors = []
    futures = {}
    try:
        for _, sources, max_workers in _group_news_sources(NEWS_SOURCES):
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
            executors.append(executor)
            for source in sources:
                futures[executor.submit(_fetch_news_source, source)] = source["name"]
        try:
            for future in concurrent.futures.as_completed(futures, timeout=15):
                result = future.result()
                if not result:
                    failed_sources.add(futures[future])
                    continue
                source_name = result["source"]
                for rank, title in enumerate(result["titles"], 1):
                    collected.append({
                        "source": source_name,
                        "title": title,
                        "category": _classify_news_title(title, source_name),
                        "rank": rank,
                        "priority": _SOURCE_PRIORITY.get(source_name, 50),
                    })
        except concurrent.futures.TimeoutError:
            failed_sources.update(
                source_name
                for future, source_name in futures.items()
                if not future.done()
            )
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        for executor in executors:
            executor.shutdown(wait=False, cancel_futures=True)

    if collected:
        balanced = _select_balanced_news(collected, limit=12)
        categories = {}
        for line in balanced:
            category = line.split("】", 1)[0].lstrip("【").split("·", 1)[0]
            categories[category] = categories.get(category, 0) + 1
        logger.info(
            f"📰 多源新闻汇总成功：候选源{len(set(i['source'] for i in collected))}个，"
            f"失败源{len(failed_sources)}个，输出{len(balanced)}条，类目{categories}"
        )
        return "\n".join(f"{i}. {title}" for i, title in enumerate(balanced, 1))

    logger.error(f"📰 所有{len(NEWS_SOURCES)}个新闻源均失败")
    return ""
